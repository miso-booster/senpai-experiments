from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from app.embeddings.embedding_build import get_or_build_index
from app.embeddings.manage_embeddings import load_index
from app.embeddings.search_content import search_files


def _write_profile(path: Path, marker: str) -> None:
    """Write a minimal profile YAML containing a unique marker string."""
    path.write_text(f'user:\n  role: "{marker}"\n', encoding="utf-8")


def _write_rule(path: Path, marker: str) -> None:
    """Write a minimal rule YAML containing a unique marker string."""
    path.write_text(f'rule:\n  name: "{marker}"\n', encoding="utf-8")


@pytest.fixture()
def fake_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic embedding stub keyed off marker tokens."""

    def _fake(text: str) -> np.ndarray:
        if "ALPHA_MARKER" in text:
            return np.array([1.0, 0.0, 0.0], dtype="float32")
        if "BRAVO_MARKER" in text:
            return np.array([0.0, 1.0, 0.0], dtype="float32")
        if "CHARLIE_MARKER" in text:
            return np.array([0.0, 0.0, 1.0], dtype="float32")
        return np.zeros(3, dtype="float32")

    def _fake_batch(texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype="float32")
        return np.array([_fake(text) for text in texts], dtype="float32")

    monkeypatch.setattr("app.embeddings.embedding_build.get_embedding", _fake)
    monkeypatch.setattr("app.embeddings.embedding_build.get_embeddings_batch", _fake_batch)
    monkeypatch.setattr("app.embeddings.search_content.get_embedding", _fake)
    return None


@pytest.fixture(autouse=True)
def _sandbox_embedding_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep embedding files under tmp_path to avoid polluting the repo."""
    monkeypatch.setattr("app.embeddings.manage_embeddings.SENPAI_PROJECT_ROOT", tmp_path)
    return None


@pytest.mark.usefixtures("fake_embed")
def test_index_refresh_on_add_modify_delete(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    profiles_dir = project / "profiles"
    rules_dir = project / "rules"
    profiles_dir.mkdir(parents=True)
    rules_dir.mkdir()

    alpha = profiles_dir / "alpha.yaml"
    bravo = profiles_dir / "bravo.yaml"

    # Build with one profile
    _write_profile(alpha, "ALPHA_MARKER")
    index_path = get_or_build_index(project)
    result = search_files("ALPHA_MARKER", index_path, file_types="profiles", top_k=1)["results"][0]
    assert result["filename"] == "alpha.yaml"

    # Add a new profile and ensure it is discoverable
    _write_profile(bravo, "BRAVO_MARKER")
    index_path = get_or_build_index(project)
    result = search_files("BRAVO_MARKER", index_path, file_types="profiles", top_k=1)["results"][0]
    assert result["filename"] == "bravo.yaml"

    # Modify the profile and ensure the updated content is used
    _write_profile(bravo, "CHARLIE_MARKER")
    # Force an mtime bump to guarantee stale detection on coarse filesystems.
    current_mtime = bravo.stat().st_mtime
    os.utime(bravo, (current_mtime + 2, current_mtime + 2))
    index_path = get_or_build_index(project)
    result = search_files("CHARLIE_MARKER", index_path, file_types="profiles", top_k=1)["results"][0]
    assert result["filename"] == "bravo.yaml"

    # Delete a profile and ensure it no longer appears in results
    alpha.unlink()
    index_path = get_or_build_index(project)
    results = search_files("ALPHA_MARKER", index_path, file_types="profiles", top_k=2)["results"]
    filenames = [item["filename"] for item in results]
    assert "alpha.yaml" not in filenames


@pytest.mark.usefixtures("fake_embed")
def test_builds_index_with_empty_profiles_and_rules(tmp_path: Path) -> None:
    """Ensure embedding index creation does not fail when profiles/rules folders are empty."""

    project = tmp_path / "proj"
    profiles_dir = project / "profiles"
    rules_dir = project / "rules"
    profiles_dir.mkdir(parents=True)
    rules_dir.mkdir()

    index_path = get_or_build_index(project)
    assert index_path.exists()

    index = load_index(index_path)
    for file_type in ("profiles", "rules"):
        data = index[file_type]
        assert data["records"] == []
        assert data["file_state"] == {"state": {}, "files": []}
        assert data["embeddings"].shape[0] == 1
        assert data["embeddings"].shape[1] > 0


def test_partial_rebuild_skips_unchanged_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "proj"
    profiles_dir = project / "profiles"
    rules_dir = project / "rules"
    profiles_dir.mkdir(parents=True)
    rules_dir.mkdir()

    calls: list[str] = []

    def _spy(text: str) -> np.ndarray:
        calls.append(text)
        if "ALPHA_MARKER" in text:
            return np.array([1.0, 0.0, 0.0], dtype="float32")
        if "BRAVO_MARKER" in text:
            return np.array([0.0, 1.0, 0.0], dtype="float32")
        if "CHARLIE_MARKER" in text:
            return np.array([0.0, 0.0, 1.0], dtype="float32")
        return np.zeros(3, dtype="float32")

    def _spy_batch(texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype="float32")
        return np.array([_spy(text) for text in texts], dtype="float32")

    monkeypatch.setattr("app.embeddings.embedding_build.get_embedding", _spy)
    monkeypatch.setattr("app.embeddings.embedding_build.get_embeddings_batch", _spy_batch)

    profile = profiles_dir / "alpha.yaml"
    rule = rules_dir / "order.yaml"

    _write_profile(profile, "ALPHA_MARKER")
    _write_rule(rule, "BRAVO_MARKER")
    get_or_build_index(project)
    calls.clear()

    _write_rule(rule, "CHARLIE_MARKER")
    current_mtime = rule.stat().st_mtime
    os.utime(rule, (current_mtime + 2, current_mtime + 2))
    index_path = get_or_build_index(project)

    assert any("CHARLIE_MARKER" in call for call in calls)
    assert all("ALPHA_MARKER" not in call for call in calls)

    index = load_index(index_path)
    rule_record = index["rules"]["records"][0]
    assert "CHARLIE_MARKER" in rule_record["yaml_text"]


def test_partial_rebuild_only_updates_changed_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "proj"
    profiles_dir = project / "profiles"
    rules_dir = project / "rules"
    profiles_dir.mkdir(parents=True)
    rules_dir.mkdir()

    calls: list[str] = []

    def _spy(text: str) -> np.ndarray:
        calls.append(text)
        if "ALPHA_MARKER" in text:
            return np.array([1.0, 0.0, 0.0], dtype="float32")
        if "BRAVO_MARKER" in text:
            return np.array([0.0, 1.0, 0.0], dtype="float32")
        if "CHARLIE_MARKER" in text:
            return np.array([0.0, 0.0, 1.0], dtype="float32")
        return np.zeros(3, dtype="float32")

    def _spy_batch(texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype="float32")
        return np.array([_spy(text) for text in texts], dtype="float32")

    monkeypatch.setattr("app.embeddings.embedding_build.get_embedding", _spy)
    monkeypatch.setattr("app.embeddings.embedding_build.get_embeddings_batch", _spy_batch)

    alpha = profiles_dir / "alpha.yaml"
    bravo = profiles_dir / "bravo.yaml"
    _write_profile(alpha, "ALPHA_MARKER")
    _write_profile(bravo, "BRAVO_MARKER")

    get_or_build_index(project)
    calls.clear()

    _write_profile(bravo, "CHARLIE_MARKER")
    current_mtime = bravo.stat().st_mtime
    os.utime(bravo, (current_mtime + 2, current_mtime + 2))

    index_path = get_or_build_index(project)

    assert len(calls) == 1
    assert "CHARLIE_MARKER" in calls[0]

    index = load_index(index_path)
    records = index["profiles"]["records"]
    yaml_texts = [record["yaml_text"] for record in records]
    assert any("ALPHA_MARKER" in text for text in yaml_texts)
    assert any("CHARLIE_MARKER" in text for text in yaml_texts)


def test_mtime_change_same_content_reuses_embeddings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "proj"
    profiles_dir = project / "profiles"
    rules_dir = project / "rules"
    profiles_dir.mkdir(parents=True)
    rules_dir.mkdir()

    calls: list[str] = []

    def _spy(text: str) -> np.ndarray:
        calls.append(text)
        if "ALPHA_MARKER" in text:
            return np.array([1.0, 0.0, 0.0], dtype="float32")
        return np.zeros(3, dtype="float32")

    def _spy_batch(texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype="float32")
        return np.array([_spy(text) for text in texts], dtype="float32")

    monkeypatch.setattr("app.embeddings.embedding_build.get_embedding", _spy)
    monkeypatch.setattr("app.embeddings.embedding_build.get_embeddings_batch", _spy_batch)

    alpha = profiles_dir / "alpha.yaml"
    _write_profile(alpha, "ALPHA_MARKER")

    get_or_build_index(project)
    calls.clear()

    current_mtime = alpha.stat().st_mtime
    os.utime(alpha, (current_mtime + 2, current_mtime + 2))

    get_or_build_index(project)

    assert calls == []


@pytest.mark.usefixtures("fake_embed")
def test_index_refresh_when_rules_change(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    profiles_dir = project / "profiles"
    rules_dir = project / "rules"
    profiles_dir.mkdir(parents=True)
    rules_dir.mkdir()

    profile = profiles_dir / "alpha.yaml"
    rule = rules_dir / "order.yaml"

    _write_profile(profile, "ALPHA_MARKER")
    _write_rule(rule, "BRAVO_MARKER")
    index_path = get_or_build_index(project)

    result = search_files("BRAVO_MARKER", index_path, file_types="rules", top_k=1)["results"][0]
    assert "BRAVO_MARKER" in result["yaml_text"]

    _write_rule(rule, "CHARLIE_MARKER")
    current_mtime = rule.stat().st_mtime
    os.utime(rule, (current_mtime + 2, current_mtime + 2))
    index_path = get_or_build_index(project)

    result = search_files("CHARLIE_MARKER", index_path, file_types="rules", top_k=1)["results"][0]
    assert "CHARLIE_MARKER" in result["yaml_text"]
