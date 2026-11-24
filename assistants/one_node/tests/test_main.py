"""Tests for the CLI entry point."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import main as app_main


class DummyAssistant:
    def __init__(
        self,
        *,
        thread_id: str | None,
        project_path: str,
        user_path: str,
        verbose: bool,
        persist: bool = True,
    ) -> None:
        self.thread_id = thread_id
        self.verbose = verbose
        self.project_path = project_path
        self.user_path = user_path
        self.persist = persist
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def patch_dependencies(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-123",
            verbose=True,
            project_path="pp-123",
            user_path="users/user_1",
            single_turn_prompt=None,
        ),
    )

    def fake_run(assistant: DummyAssistant) -> None:
        captured["run_called_with"] = assistant

    monkeypatch.setattr("app.main.run_conversation", fake_run)
    monkeypatch.setattr("app.main.Assistant", DummyAssistant)

    return captured


def test_main_wires_components_and_closes(patch_dependencies: dict[str, Any]) -> None:
    """Ensure the main entrypoint sets up CLI args, creates the assistant, runs the conversation, and closes resources."""

    captured = patch_dependencies

    app_main.main()

    assistant = captured["run_called_with"]
    assert isinstance(assistant, DummyAssistant)
    assert assistant.thread_id == "cid-123"
    assert assistant.verbose is True
    assert assistant.project_path == "pp-123"
    assert assistant.user_path == "users/user_1"
    assert assistant.closed is True


def test_main_closes_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant = DummyAssistant(thread_id="cid-777", project_path="pp-777", user_path="users/user_1", verbose=False)

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-777",
            project_path="pp-777",
            user_path="users/user_1",
            verbose=False,
            single_turn_prompt=None,
        ),
    )
    monkeypatch.setattr(
        "app.main.Assistant",
        lambda thread_id, project_path, user_path, verbose, persist=True: assistant,
    )

    def blowing_run(_assistant: DummyAssistant) -> None:
        raise RuntimeError("fake error")

    monkeypatch.setattr("app.main.run_conversation", blowing_run)

    with pytest.raises(RuntimeError):
        app_main.main()

    assert assistant.closed is True


def test_main_single_turn_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant = DummyAssistant(thread_id="cid-888", project_path="pp-888", user_path="users/user_2", verbose=False)

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-888",
            project_path="pp-888",
            user_path="users/user_2",
            verbose=False,
            single_turn_prompt="hola",
        ),
    )
    monkeypatch.setattr(
        "app.main.Assistant",
        lambda thread_id, project_path, user_path, verbose, persist=True: assistant,
    )

    called: dict[str, Any] = {"run_single_turn": 0, "run_conversation": 0, "printed": []}

    def fake_run_single_turn(_assistant: DummyAssistant, prompt: str) -> str:
        called["run_single_turn"] += 1
        assert prompt == "hola"
        return "single-answer"

    def fake_run_conversation(_assistant: DummyAssistant) -> None:
        called["run_conversation"] += 1
        raise AssertionError("run_conversation should not be called for single turn")

    def fake_print(*args: Any, **_kwargs: Any) -> None:
        called["printed"].append(args)

    monkeypatch.setattr("app.main.run_single_turn", fake_run_single_turn)
    monkeypatch.setattr("app.main.run_conversation", fake_run_conversation)
    monkeypatch.setattr("builtins.print", fake_print)

    app_main.main()

    assert called["run_single_turn"] == 1
    assert called["run_conversation"] == 0
    expected = "$$$\nsingle-answer\n$$$"
    assert any(args and args[0] == expected for args in called["printed"])


def test_main_reconfigures_stdout_and_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyStream:
        def __init__(self) -> None:
            self.encoding: str | None = None
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, *, encoding: str) -> None:
            self.encoding = encoding
            self.calls.append({"encoding": encoding})

    dummy_out = DummyStream()
    dummy_err = DummyStream()

    monkeypatch.setattr("sys.stdout", dummy_out)
    monkeypatch.setattr("sys.stderr", dummy_err)

    app_main._configure_stdio()

    assert dummy_out.encoding == "utf-8"
    assert dummy_err.encoding == "utf-8"
