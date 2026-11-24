from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest
import yaml

from app.assistant.project_context import (
    ProjectContextStats,
    SenseiProjectError,
    UserContextStats,
    _flatten_yaml_list,
    _load_yaml,
    build_prompt_contexts,
    format_project_context_for_prompt,
    parse_project_context,
    parse_user_context,
    resolve_project_context,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SENSEI_PROJECTS = REPO_ROOT / "sensei_projects"


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
    assert "test_name: appointment" in formatted


def test_resolve_project_context_accepts_path_objects() -> None:
    context = resolve_project_context(SENSEI_PROJECTS / "bikeshop")
    assert context.startswith("### User Project Context")
    assert "Profile files:" in context
    assert "appointment.yml" in context
    assert "test_name: appointment" in context


def test_resolve_project_context_accepts_string_paths() -> None:
    project_path = SENSEI_PROJECTS / "pizza_shop"
    context = resolve_project_context(str(project_path))
    assert context.startswith("### User Project Context")
    assert "name: more_toppings_cost_more" in context


def test_resolve_project_context_returns_literal_strings() -> None:
    literal = "profiles:\n- demo"
    assert resolve_project_context(literal) == literal
    multiline = "profiles:\n- demo\n---\nrules:\n- example"
    assert resolve_project_context(multiline) == multiline


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


def test_parse_user_context_without_path_returns_blank_string() -> None:
    assert parse_user_context() == ""
    assert parse_user_context(user_path="") == ""


def test_parse_user_context_reads_connectors_from_user_root(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    user_root.mkdir()
    connector_file = user_root / "echo.yml"
    connector_file.write_text(
        'name: "Echo Bot"\nbase_url: "https://example.com"\nsend_message:\n  path: "/chat"\nresponse_path: "answer"\n',
        encoding="utf-8",
    )

    result, stats = parse_user_context(user_root, include_stats=True)
    parsed_docs = list(yaml.safe_load_all(result))

    assert isinstance(stats, UserContextStats)
    assert stats.root == user_root.resolve()
    assert stats.connectors_root == user_root.resolve()
    assert stats.connectors == (connector_file.resolve(),)
    assert parsed_docs[0]["name"] == "Echo Bot"


def test_parse_user_context_reads_connectors_from_nested_folder(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    connectors_root = user_root / "connectors"
    connectors_root.mkdir(parents=True)
    connector_file = connectors_root / "nested.yml"
    connector_file.write_text(
        'name: "Nested Bot"\nbase_url: "https://example.com"\nsend_message:\n  path: "/chat"\nresponse_path: "answer"\n',
        encoding="utf-8",
    )

    _, stats = parse_user_context(user_root, include_stats=True)

    assert stats.root == user_root.resolve()
    assert stats.connectors_root == connectors_root.resolve()
    assert stats.connectors == (connector_file.resolve(),)


def test_build_prompt_contexts_splits_context_by_domain(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    profiles = project_root / "profiles"
    rules = project_root / "rules"
    profiles.mkdir(parents=True)
    rules.mkdir()
    (profiles / "profile_alpha.yml").write_text("test_name: profile_alpha\nrole: tester\n", encoding="utf-8")
    (rules / "rule_alpha.yml").write_text("name: rule_alpha\ndescription: sample\n", encoding="utf-8")

    user_root = tmp_path / "user"
    user_root.mkdir()
    (user_root / "connector_alpha.yml").write_text(
        'name: "connector_alpha"\nbase_url: "https://example.com"\nsend_message:\n  path: "/chat"\nresponse_path: "answer"\n',
        encoding="utf-8",
    )

    prompt_contexts, _, _ = build_prompt_contexts(project_root, user_root)

    assert "### User Profile Context" in prompt_contexts["profile"]
    assert "Profile names: profile_alpha" in prompt_contexts["profile"]
    assert "rule_alpha" not in prompt_contexts["profile"]
    assert "### User Rule Context" in prompt_contexts["rule"]
    assert "Rule names: rule_alpha" in prompt_contexts["rule"]
    assert "profile_alpha" not in prompt_contexts["rule"]
    assert "### User Connector Context" in prompt_contexts["connector"]
    assert "Connector names: connector_alpha" in prompt_contexts["connector"]
    assert "Profile names: profile_alpha" in prompt_contexts["explain"]
    assert "Rule names: rule_alpha" in prompt_contexts["explain"]
    assert "Connector names: connector_alpha" in prompt_contexts["explain"]
