"""Tests for project tools."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from textwrap import dedent

import pytest
from langchain_core.tools import BaseTool

from app.assistant.tools import build_project_tools

REPO_ROOT = Path(__file__).resolve().parents[1]
SENSEI_PROJECTS = REPO_ROOT / "sensei_projects"
SENSEI_USER = REPO_ROOT / "users" / "user_1"


def _get_tool(tools: Sequence[BaseTool], name: str) -> BaseTool:
    for tool in tools:
        if getattr(tool, "name", None) == name:
            return tool
    raise KeyError(name)


def _make_sensei_project(tmp_path: Path) -> Path:
    project = tmp_path / "sensei_project"
    (project / "profiles").mkdir(parents=True)
    (project / "rules").mkdir()
    return project


def _make_connectors_dir(tmp_path: Path) -> Path:
    connectors_dir = tmp_path / "connectors"
    connectors_dir.mkdir()
    return connectors_dir


def _valid_profile_yaml(test_name: str = "Demo") -> str:
    return dedent(
        f"""\
        test_name: {test_name}
        llm:
          temperature: 0.3
          model: gpt-4o
        user:
          language: en
          role: customer
          goals:
            - Find a product
        chatbot:
          is_starter: true
          fallback: "Sorry, I didn't get that."
          output:
            - result:
                type: string
                description: Final result
        conversation:
          number: 1
          goal_style:
            steps: 3
          interaction_style:
            - default
        """
    )


def test_list_and_read_profiles(tmp_path: Path) -> None:
    project = SENSEI_PROJECTS / "pizza_shop"
    tools = build_project_tools(project, SENSEI_USER / "connectors")

    list_profiles = _get_tool(tools, "list_profiles")
    read_profile = _get_tool(tools, "read_profile")

    profiles = list_profiles.invoke({})

    assert "pizza_order_test_custom.yml" in profiles

    content = read_profile.invoke({"filename": "pizza_order_test_custom.yml"})
    assert "pizza_order_test_custom" in content


def test_list_and_read_connectors(tmp_path: Path) -> None:
    connectors_dir = _make_connectors_dir(tmp_path)
    (connectors_dir / "alpha.yml").write_text("name: alpha\n", encoding="utf-8")

    tools = build_project_tools(None, connectors_dir)
    list_connectors = _get_tool(tools, "list_connectors")
    read_connector = _get_tool(tools, "read_connector")

    connectors = list_connectors.invoke({})
    assert "alpha.yml" in connectors

    content = read_connector.invoke({"filename": "alpha.yml"})
    assert "name: alpha" in content


def test_search_connectors_returns_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connectors_dir = _make_connectors_dir(tmp_path)
    tools = build_project_tools(None, connectors_dir)
    search_connectors = _get_tool(tools, "search_connectors")

    monkeypatch.setattr("app.assistant.tools.get_or_build_index", lambda path: Path("fake-index"))
    monkeypatch.setattr(
        "app.assistant.tools.search_files",
        lambda *_args, **_kwargs: {"results": [{"filename": "alpha.yml", "score": 0.42}]},
    )

    results = search_connectors.invoke({"query": "alpha", "top_k": 1})
    assert results == [{"filename": "alpha.yml", "score": 0.42}]


def test_list_and_read_rules(tmp_path: Path) -> None:
    project = SENSEI_PROJECTS / "pizza_shop"
    tools = build_project_tools(project, SENSEI_USER / "connectors")

    list_rules = _get_tool(tools, "list_rules")
    read_rule = _get_tool(tools, "read_rule")

    rules = list_rules.invoke({})
    assert any(name.endswith(".yml") or name.endswith(".yaml") for name in rules)

    first_rule = rules[0]
    content = read_rule.invoke({"filename": first_rule})
    assert first_rule.split(".")[0] in content


def test_read_profile_rejects_missing_file(tmp_path: Path) -> None:
    project = SENSEI_PROJECTS / "pizza_shop"
    tools = build_project_tools(project, SENSEI_USER / "connectors")
    read_profile = _get_tool(tools, "read_profile")

    result = read_profile.invoke({"filename": "nope.yml"})
    assert "File not found" in result


def test_save_profile_writes_file(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    save_profile = _get_tool(tools, "save_profile")

    content = _valid_profile_yaml("alpha")
    result = save_profile.invoke({"filename": "alpha.yml", "content": content})
    assert result == {"status": "created", "filename": "alpha.yml"}

    profile_path = project / "profiles" / "alpha.yml"
    assert profile_path.exists()
    assert profile_path.read_text(encoding="utf-8") == content.rstrip() + "\n"


def test_build_tools_excludes_create_tools_when_disabled(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    connectors_dir = _make_connectors_dir(tmp_path)
    tools = build_project_tools(project, connectors_dir, include_create_tools=False)

    tool_names = {tool.name for tool in tools}

    assert "save_profile" not in tool_names
    assert "save_rule" not in tool_names
    assert "save_connector" not in tool_names

    assert "delete_profile" in tool_names
    assert "delete_rule" in tool_names
    assert "delete_connector" in tool_names


def test_save_profile_rejects_empty_content(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    save_profile = _get_tool(tools, "save_profile")

    result = save_profile.invoke({"filename": "alpha.yml", "content": "   "})
    assert result.get("error") == "Content is empty."


def test_save_profile_rejects_invalid_filename(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    save_profile = _get_tool(tools, "save_profile")

    result = save_profile.invoke({"filename": ".", "content": "name: alpha"})
    assert result == {"error": "Invalid filename."}


def test_save_profile_rejects_invalid_suffix(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    save_profile = _get_tool(tools, "save_profile")

    result = save_profile.invoke({"filename": "alpha.txt", "content": "name: alpha"})
    assert result == {"error": "Unsupported file type: .txt"}


def test_save_profile_rejects_missing_directory(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    (project / "profiles").rmdir()
    save_profile = _get_tool(tools, "save_profile")

    result = save_profile.invoke({"filename": "alpha.yml", "content": "name: alpha"})

    assert result["error"].startswith("Directory not found:")


def test_save_profile_refuses_overwrite_by_default(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    save_profile = _get_tool(tools, "save_profile")

    alpha = _valid_profile_yaml("alpha")
    beta = _valid_profile_yaml("beta")
    save_profile.invoke({"filename": "alpha.yml", "content": alpha})
    result = save_profile.invoke({"filename": "alpha.yml", "content": beta})

    assert "File already exists" in result["error"]
    profile_path = project / "profiles" / "alpha.yml"
    assert profile_path.read_text(encoding="utf-8") == alpha.rstrip() + "\n"


def test_save_profile_allows_overwrite(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    save_profile = _get_tool(tools, "save_profile")

    alpha = _valid_profile_yaml("alpha")
    beta = _valid_profile_yaml("beta")
    save_profile.invoke({"filename": "alpha.yml", "content": alpha})
    result = save_profile.invoke({"filename": "alpha.yml", "content": beta, "overwrite": True})

    assert result == {"status": "overwritten", "filename": "alpha.yml"}
    profile_path = project / "profiles" / "alpha.yml"
    assert profile_path.read_text(encoding="utf-8") == beta.rstrip() + "\n"


def test_save_profile_sanitizes_path_traversal(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    save_profile = _get_tool(tools, "save_profile")

    content = _valid_profile_yaml("outside")
    result = save_profile.invoke({"filename": "../outside.yml", "content": content})
    assert result == {"status": "created", "filename": "outside.yml"}

    assert (project / "profiles" / "outside.yml").exists()
    assert not (project / "outside.yml").exists()


def test_delete_profile_deletes_file(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    profile_path = project / "profiles" / "alpha.yml"
    profile_path.write_text("name: alpha\n", encoding="utf-8")

    tools = build_project_tools(project, None)
    delete_profile = _get_tool(tools, "delete_profile")

    result = delete_profile.invoke({"filename": "alpha.yml"})
    assert result == {"status": "deleted", "filename": "alpha.yml"}
    assert not profile_path.exists()


def test_delete_profile_rejects_missing_file(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    delete_profile = _get_tool(tools, "delete_profile")

    result = delete_profile.invoke({"filename": "missing.yml"})
    assert "File not found" in result["error"]


def test_delete_profile_rejects_invalid_suffix(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    delete_profile = _get_tool(tools, "delete_profile")

    result = delete_profile.invoke({"filename": "alpha.txt"})
    assert result == {"error": "Unsupported file type: .txt"}


def test_delete_profile_rejects_invalid_filename(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    delete_profile = _get_tool(tools, "delete_profile")

    result = delete_profile.invoke({"filename": "."})
    assert result == {"error": "Invalid filename."}


def test_delete_profile_rejects_missing_directory(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    tools = build_project_tools(project, None)
    (project / "profiles").rmdir()
    delete_profile = _get_tool(tools, "delete_profile")

    result = delete_profile.invoke({"filename": "alpha.yml"})
    assert result["error"].startswith("Directory not found:")


def test_delete_profile_sanitizes_path_traversal(tmp_path: Path) -> None:
    project = _make_sensei_project(tmp_path)
    (project / "profiles" / "outside.yml").write_text("name: inside\n", encoding="utf-8")
    (project / "outside.yml").write_text("name: outside\n", encoding="utf-8")

    tools = build_project_tools(project, None)
    delete_profile = _get_tool(tools, "delete_profile")

    result = delete_profile.invoke({"filename": "../outside.yml"})
    assert result == {"status": "deleted", "filename": "outside.yml"}
    assert not (project / "profiles" / "outside.yml").exists()
    assert (project / "outside.yml").exists()


def test_get_docs_returns_full_docs_by_type() -> None:
    tools = build_project_tools(None, None)
    get_docs = _get_tool(tools, "get_docs")

    profiles_docs = get_docs.invoke({"doc_types": ["profiles"]})
    assert profiles_docs
    assert all(doc.get("doc_type") == "profiles" for doc in profiles_docs)
    assert any("Sensei Profiles" in doc.get("content", "") for doc in profiles_docs)


def test_get_docs_default_returns_all() -> None:
    tools = build_project_tools(None, None)
    get_docs = _get_tool(tools, "get_docs")

    docs = get_docs.invoke({"doc_types": ["rules", "profiles", "connectors"]})
    filenames = {doc.get("filename") for doc in docs}
    expected = {
        "sensei-check-doc.md",
        "rules-examples.md",
        "sensei-chat-guide.md",
        "custom-connector-guide.md",
        "connector-examples.md",
    }
    assert expected.issubset(filenames)


def test_get_docs_rules_only() -> None:
    tools = build_project_tools(None, None)
    get_docs = _get_tool(tools, "get_docs")

    docs = get_docs.invoke({"doc_types": ["rules"]})
    filenames = {doc.get("filename") for doc in docs}
    assert filenames == {"sensei-check-doc.md", "rules-examples.md"}
    assert all(doc.get("doc_type") == "rules" for doc in docs)


def test_get_docs_connectors_only() -> None:
    tools = build_project_tools(None, None)
    get_docs = _get_tool(tools, "get_docs")

    docs = get_docs.invoke({"doc_types": ["connectors"]})
    filenames = {doc.get("filename") for doc in docs}
    assert filenames == {"custom-connector-guide.md", "connector-examples.md"}
    assert all(doc.get("doc_type") == "connectors" for doc in docs)


def test_get_docs_nonexistent_returns_error() -> None:
    tools = build_project_tools(None, None)
    get_docs = _get_tool(tools, "get_docs")

    docs = get_docs.invoke({"doc_types": ["nonexistent"]})
    assert docs and "error" in docs[0]


def test_get_docs_empty_list_returns_error() -> None:
    tools = build_project_tools(None, None)
    get_docs = _get_tool(tools, "get_docs")

    docs = get_docs.invoke({"doc_types": []})
    assert docs and "error" in docs[0]
    assert "Provide at least one doc_type" in docs[0]["error"]


def test_get_docs_all_types_returns_all_docs() -> None:
    tools = build_project_tools(None, None)
    get_docs = _get_tool(tools, "get_docs")

    docs = get_docs.invoke({"doc_types": ["rules", "profiles", "connectors"]})
    filenames = {doc.get("filename") for doc in docs}
    assert "sensei-check-doc.md" in filenames
    assert "sensei-chat-guide.md" in filenames
