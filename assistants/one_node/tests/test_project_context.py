from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest
import yaml
from langchain_core.messages import HumanMessage

from app.assistant.project_context import (
    ProjectContextStats,
    SenseiProjectError,
    UserContextStats,
    _flatten_yaml_list,
    _load_yaml,
    format_project_context_for_prompt,
    format_user_context_for_prompt,
    parse_project_context,
    parse_user_context,
    resolve_project_context,
    resolve_user_context,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SENSEI_PROJECTS = REPO_ROOT / "sensei_projects"
USERS_ROOT = REPO_ROOT / "users"


def _collect_field(entries: Iterable[object], field: str) -> set[str]:
    values: set[str] = set()
    for item in entries:
        if isinstance(item, dict):
            value = item.get(field)
            if isinstance(value, str):
                values.add(value)
    return values


def test_load_yaml_reads_demo_profiles() -> None:
    profiles_dir = SENSEI_PROJECTS / "bikeshop" / "profiles"

    docs, files = _load_yaml(profiles_dir)
    names = _collect_field(docs, "test_name")

    assert {"appointment", "qa", "user_sim_bikesqa"}.issubset(names)
    assert {"appointment.yml", "qa.yml", "user_sim_bikesqa.yml"}.issubset({file.name for file in files})


def test_flatten_yaml_list_round_trips_data() -> None:
    yaml_list = [
        {"profile": "mentor-alpha", "skills": ["python", "pytest"]},
        {"profile": "mentor-beta", "skills": ["langchain"]},
    ]

    flattened = _flatten_yaml_list(yaml_list)
    reconstructed = list(yaml.safe_load_all(flattened))

    assert reconstructed == yaml_list


def test_parse_project_context_without_path_returns_blank_string() -> None:
    assert parse_project_context() == ""
    assert parse_project_context(project_path="") == ""


def test_parse_project_context_reads_demo_project() -> None:
    project_root = SENSEI_PROJECTS / "pizza_shop"

    result, stats = parse_project_context(str(project_root), include_stats=True)
    parsed_docs = list(yaml.safe_load_all(result))
    profile_names = _collect_field(parsed_docs, "test_name")
    rule_names = _collect_field(parsed_docs, "name")

    assert {"pizza_order_test_custom", "pizza_order_test_predefined"}.issubset(profile_names)
    assert "more_toppings_cost_more" in rule_names
    assert isinstance(stats, ProjectContextStats)
    assert stats.root == project_root.resolve()
    assert all(file.parent.name == "profiles" for file in stats.profiles)
    assert all(file.parent.name == "rules" for file in stats.rules)


def test_format_project_context_for_prompt_includes_metadata() -> None:
    raw_context, stats = parse_project_context(SENSEI_PROJECTS / "bikeshop", include_stats=True)
    formatted = format_project_context_for_prompt(raw_context, stats)

    assert formatted.startswith("### User Project Context")
    assert "Project root:" in formatted
    assert "Profile files:" in formatted
    assert "appointment.yml" in formatted
    assert "Rule files: none" in formatted
    assert "Project structure:" in formatted
    assert "profiles/" in formatted
    assert "profiles/appointment.yml" in formatted
    assert "test_name: appointment" in formatted


def test_resolve_project_context_includes_full_project_content() -> None:
    messages = [HumanMessage(content="listame todas las reglas")]

    result = resolve_project_context(messages, SENSEI_PROJECTS / "pizza_shop", state=True)

    assert result.startswith("### User Project Context")
    assert "Project structure:" in result
    assert "pizza_order_test_custom" in result
    assert "more_toppings_cost_more" in result
    assert "ordering_conversation_turns" in result


def test_parse_user_context_reads_demo_user_folder() -> None:
    result, stats = parse_user_context(USERS_ROOT / "user_1", include_stats=True)

    assert "### connectors/ada-uam.yaml" in result
    assert "### connectors/postman.yaml" in result
    assert isinstance(stats, UserContextStats)
    assert stats.root == (USERS_ROOT / "user_1").resolve()
    assert any(file.parent.name == "connectors" for file in stats.files)


def test_format_user_context_for_prompt_includes_metadata() -> None:
    raw_context, stats = parse_user_context(USERS_ROOT / "user_1", include_stats=True)
    formatted = format_user_context_for_prompt(raw_context, stats)

    assert formatted.startswith("### User Folder Context")
    assert "User root:" in formatted
    assert "User files:" in formatted
    assert "User structure:" in formatted
    assert "connectors/" in formatted
    assert "connectors/ada-uam.yaml" in formatted
    assert "ada-uam.yaml" in formatted


def test_resolve_user_context_includes_full_user_folder_content() -> None:
    messages = [HumanMessage(content="que conectores tengo")]

    result = resolve_user_context(messages, USERS_ROOT / "user_1", state=True)

    assert result.startswith("### User Folder Context")
    assert "User structure:" in result
    assert "connectors/ada-uam.yaml" in result
    assert "connectors/postman.yaml" in result


def test_parse_project_context_requires_profiles_and_rules(tmp_path: Path) -> None:
    project_root = tmp_path / "invalid_project"
    project_root.mkdir()
    (project_root / "profiles").mkdir()

    with pytest.raises(SenseiProjectError):
        parse_project_context(project_root)


def test_parse_project_context_requires_yaml_files(tmp_path: Path) -> None:
    project_root = tmp_path / "empty_project"
    profiles = project_root / "profiles"
    rules = project_root / "rules"
    profiles.mkdir(parents=True)
    rules.mkdir()
    (profiles / "README.txt").write_text("placeholder", encoding="utf-8")
    (rules / "README.txt").write_text("placeholder", encoding="utf-8")

    with pytest.raises(SenseiProjectError):
        parse_project_context(project_root)


def test_parse_project_context_invalid_path() -> None:
    with pytest.raises(FileNotFoundError):
        parse_project_context(Path("does-not-exist-xyz"))


def test_parse_user_context_invalid_path() -> None:
    with pytest.raises(FileNotFoundError):
        parse_user_context(Path("missing-user-folder-xyz"))


def test_parse_user_context_ignores_non_yaml_files(tmp_path: Path) -> None:
    user_root = tmp_path / "user_x"
    connectors = user_root / "connectors"
    connectors.mkdir(parents=True)
    (connectors / "valid.yaml").write_text("name: demo", encoding="utf-8")
    (connectors / "ignored.txt").write_text("should not appear", encoding="utf-8")

    result, stats = parse_user_context(user_root, include_stats=True)

    assert "valid.yaml" in result
    assert "ignored.txt" not in result
    assert tuple(file.name for file in stats.files) == ("valid.yaml",)


def test_parse_user_context_ignores_yaml_outside_connectors_subtree(tmp_path: Path) -> None:
    user_root = tmp_path / "user_x"
    connectors = user_root / "connectors"
    notes = user_root / "notes"
    connectors.mkdir(parents=True)
    notes.mkdir()
    (connectors / "valid.yaml").write_text("name: connector_demo", encoding="utf-8")
    (notes / "leak.yaml").write_text("name: should_not_be_loaded", encoding="utf-8")

    result, stats = parse_user_context(user_root, include_stats=True)

    assert "connectors/valid.yaml" in result
    assert "should_not_be_loaded" not in result
    assert tuple(file.relative_to(user_root).as_posix() for file in stats.files) == ("connectors/valid.yaml",)
