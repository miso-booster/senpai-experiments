"""Tests for the CLI entry point."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from app import main as app_main

REPO_ROOT = Path(__file__).resolve().parents[1]
SENSEI_PROJECT = REPO_ROOT / "sensei_projects" / "pizza_shop"
SENSEI_USER = REPO_ROOT / "users" / "user_1"


class DummyAssistant:
    def __init__(
        self,
        *,
        thread_id: str,
        project_path: Path | str,
        embedding_path: str,
        connectors_path: Path | str | None = None,
        connectors_embedding_path: Path | str | None = None,
        checkpointer: object | None = None,
        include_create_tools: bool = True,
    ) -> None:
        self.thread_id = thread_id
        self.embedding_path = embedding_path
        self.project_path = project_path
        self.connectors_path = connectors_path
        self.connectors_embedding_path = connectors_embedding_path
        self.checkpointer = checkpointer
        self.include_create_tools = include_create_tools
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def patch_dependencies(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    # Emulate parsing CLI arguments
    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-123",
            verbose=True,
            debug=False,
            log_file="",
            project_path=str(SENSEI_PROJECT),
            user_path=str(SENSEI_USER),
        ),
    )

    # Skip building a real embedding index
    monkeypatch.setattr("app.main.get_or_build_index", lambda project_dir: "fake-embedding-path")

    # Store the assistant passed to run_conversation
    def fake_run(assistant: DummyAssistant) -> None:
        captured["run_called_with"] = assistant

    # Replace run_conversation with fake_run
    monkeypatch.setattr("app.main.run_conversation", fake_run)
    # Replace Assistant with DummyAssistant
    monkeypatch.setattr("app.main.Assistant", DummyAssistant)

    return captured


def test_main_wires_components_and_closes(patch_dependencies: dict[str, Any]) -> None:
    """Ensure the main entrypoint sets up CLI args, creates the assistant, runs the conversation, and closes resources."""

    captured = patch_dependencies

    app_main.main()

    assistant = captured["run_called_with"]
    assert isinstance(assistant, DummyAssistant)
    assert assistant.thread_id == "cid-123"
    assert assistant.embedding_path == "fake-embedding-path"
    assert assistant.project_path == SENSEI_PROJECT
    assert assistant.connectors_path == SENSEI_USER / "connectors"
    assert assistant.include_create_tools is True
    assert assistant.closed is True


def test_main_single_turn_runs_and_prints(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-single",
            verbose=True,
            debug=False,
            log_file="",
            project_path=str(SENSEI_PROJECT),
            user_path=str(SENSEI_USER),
            single_turn_prompt="hola",
        ),
    )
    monkeypatch.setattr("app.main.get_or_build_index", lambda project_dir: "fake-embedding-path")

    def fake_run_single_turn(assistant: DummyAssistant, prompt: str) -> str:
        calls["assistant"] = assistant
        calls["prompt"] = prompt
        return "single answer"

    monkeypatch.setattr("app.main.run_single_turn", fake_run_single_turn)
    monkeypatch.setattr("app.main.run_conversation", lambda _assistant: pytest.fail("run_conversation should not run"))
    monkeypatch.setattr("app.main.Assistant", DummyAssistant)

    app_main.main()

    out = capsys.readouterr().out
    assert calls["prompt"] == "hola"
    assert "conversation ID: cid-single" in out
    assert "single answer" in out
    assert calls["assistant"].include_create_tools is False


def test_main_closes_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant = DummyAssistant(thread_id="cid-777", embedding_path="fake-path", project_path=SENSEI_PROJECT)

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-777",
            project_path=str(SENSEI_PROJECT),
            verbose=False,
            debug=False,
            log_file="",
            user_path=str(SENSEI_USER),
        ),
    )
    monkeypatch.setattr("app.main.get_or_build_index", lambda project_dir: "fake-path")
    monkeypatch.setattr(
        "app.main.Assistant",
        lambda **_kwargs: assistant,
    )

    def blowing_run(_assistant: DummyAssistant) -> None:
        raise RuntimeError("fake error")

    monkeypatch.setattr("app.main.run_conversation", blowing_run)

    with pytest.raises(RuntimeError):
        app_main.main()

    assert assistant.closed is True


def test_main_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """KeyboardInterrupt should be caught so the process exits quietly."""

    def fake_setup() -> SimpleNamespace:
        return SimpleNamespace(
            conversation_id="cid-int",
            verbose=False,
            debug=False,
            log_file="",
            project_path=str(SENSEI_PROJECT),
            user_path=str(SENSEI_USER),
        )

    called: dict[str, Any] = {"deploy": False}

    def fake_deploy(*args: Any, **kwargs: Any) -> None:
        called["deploy"] = True
        raise KeyboardInterrupt

    monkeypatch.setattr("app.main._setup_configuration", fake_setup)
    monkeypatch.setattr("app.main._create_embedding_path", lambda project_path: "fake-embed")
    monkeypatch.setattr("app.main.deploy_assistant", fake_deploy)

    app_main.main()

    out = capsys.readouterr().out
    assert called["deploy"] is True
    assert "Session interrupted (Ctrl+C). Exiting..." in out


def test_main_rejects_non_sensei_project(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bad_project = tmp_path / "not_sensei"
    bad_project.mkdir()

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-bad",
            verbose=False,
            debug=False,
            log_file="",
            project_path=str(bad_project),
            user_path=str(SENSEI_USER),
        ),
    )

    with pytest.raises(SystemExit) as excinfo:
        app_main.main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Invalid SENSEI project" in out


def test_main_rejects_non_sensei_user(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bad_user = tmp_path / "not_sensei_user"
    bad_user.mkdir()

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-bad-user",
            verbose=False,
            debug=False,
            log_file="",
            project_path=str(SENSEI_PROJECT),
            user_path=str(bad_user),
        ),
    )

    with pytest.raises(SystemExit) as excinfo:
        app_main.main()

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Invalid SENSEI user" in out


def test_main_ephemeral_conversation_creates_in_memory_checkpointer_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When conversation_id is None, main should use an in-memory checkpointer and warn the user."""

    captured: dict[str, Any] = {}
    messages: list[str] = []

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id=None,
            verbose=False,
            debug=False,
            log_file="",
            project_path=str(SENSEI_PROJECT),
            user_path=str(SENSEI_USER),
        ),
    )
    monkeypatch.setattr("app.main.get_or_build_index", lambda project_dir: "fake-embedding-path")
    monkeypatch.setattr("app.main.conversation_console.print", lambda message: messages.append(str(message)))

    def fake_run(assistant: DummyAssistant) -> None:
        captured["assistant"] = assistant

    monkeypatch.setattr("app.main.run_conversation", fake_run)
    monkeypatch.setattr("app.main.Assistant", DummyAssistant)

    original_deploy = app_main.deploy_assistant

    def capturing_deploy(*args: Any, **kwargs: Any) -> None:
        captured["checkpointer"] = kwargs.get("checkpointer")
        captured["connection"] = kwargs.get("checkpointer_connection")
        return original_deploy(*args, **kwargs)

    monkeypatch.setattr("app.main.deploy_assistant", capturing_deploy)

    app_main.main()

    checkpointer = captured.get("checkpointer")
    connection = captured.get("connection")

    assert isinstance(checkpointer, SqliteSaver)
    assert isinstance(connection, sqlite3.Connection)

    # The deploy_assistant finally block should close the external connection.
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("select 1")

    assert any("conversation memory will not be saved" in message for message in messages)


def test_deploy_assistant_single_turn_prints_and_closes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    closed: list[object] = []

    def recording_safe_close(resource: object) -> None:
        closed.append(resource)
        close = getattr(resource, "close", None)
        if callable(close):
            close()

    def fake_run_single_turn(assistant: DummyAssistant, prompt: str) -> str:
        assert prompt == "hola"
        return "single reply"

    monkeypatch.setattr("app.main.Assistant", DummyAssistant)
    monkeypatch.setattr("app.main.run_single_turn", fake_run_single_turn)
    monkeypatch.setattr("app.main.run_conversation", lambda _assistant: pytest.fail("run_conversation should not run"))
    monkeypatch.setattr("app.main.safe_close", recording_safe_close)

    connection = sqlite3.connect(":memory:")

    app_main.deploy_assistant(
        thread_id="cid-deploy",
        embedding_path=Path("fake-embed"),
        project_path=SENSEI_PROJECT,
        connectors_path=None,
        connectors_embedding_path=None,
        checkpointer=None,
        checkpointer_connection=connection,
        single_turn_prompt="hola",
    )

    out = capsys.readouterr().out
    assert "conversation ID: cid-deploy" in out
    assert "single reply" in out
    assert any(isinstance(item, DummyAssistant) for item in closed)
    assert connection in closed
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("select 1")


def test_deploy_assistant_single_turn_closes_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[object] = []

    def recording_safe_close(resource: object) -> None:
        closed.append(resource)
        close = getattr(resource, "close", None)
        if callable(close):
            close()

    def failing_run_single_turn(_assistant: DummyAssistant, _prompt: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.main.Assistant", DummyAssistant)
    monkeypatch.setattr("app.main.run_single_turn", failing_run_single_turn)
    monkeypatch.setattr("app.main.run_conversation", lambda _assistant: pytest.fail("run_conversation should not run"))
    monkeypatch.setattr("app.main.safe_close", recording_safe_close)

    connection = sqlite3.connect(":memory:")

    with pytest.raises(RuntimeError):
        app_main.deploy_assistant(
            thread_id="cid-deploy-error",
            embedding_path=Path("fake-embed"),
            project_path=SENSEI_PROJECT,
            connectors_path=None,
            connectors_embedding_path=None,
            checkpointer=None,
            checkpointer_connection=connection,
            single_turn_prompt="hola",
        )

    assert any(isinstance(item, DummyAssistant) for item in closed)
    assert connection in closed
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("select 1")
