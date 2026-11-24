"""Tests for the CLI entry point."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import main as app_main


class DummyAssistant:
    def __init__(self, *, thread_id: str, project_path: str | Path, user_path: str | Path, verbose: bool) -> None:
        self.thread_id = thread_id
        self.verbose = verbose
        self.project_path = project_path
        self.user_path = user_path
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def patch_dependencies(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    # Emulate parsing CLI arguments
    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(conversation_id="cid-123", verbose=True, project_path="pp-123", user_path="up-123"),
    )

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
    assert assistant.verbose is True
    assert assistant.project_path == "pp-123"
    assert assistant.user_path == "up-123"
    assert assistant.closed is True


def test_main_closes_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    assistant = DummyAssistant(thread_id="cid-777", project_path="pp-777", user_path="up-777", verbose=False)

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(conversation_id="cid-777", project_path="pp-777", user_path="up-777", verbose=False),
    )
    monkeypatch.setattr("app.main.Assistant", lambda thread_id, project_path, user_path, verbose: assistant)

    def blowing_run(_assistant: DummyAssistant) -> None:
        raise RuntimeError("fake error")

    monkeypatch.setattr("app.main.run_conversation", blowing_run)

    with pytest.raises(RuntimeError):
        app_main.main()

    assert assistant.closed is True


def test_deploy_assistant_single_turn_runs_and_prints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assistant = DummyAssistant(thread_id="cid-999", project_path="pp-999", user_path="up-999", verbose=False)
    prompt = "hola"
    response_text = "respuesta"
    captured: dict[str, Any] = {}

    def fake_run_single_turn(fake_assistant: DummyAssistant, fake_prompt: str) -> str:
        captured["run_single_turn_called"] = (fake_assistant, fake_prompt)
        return response_text

    def fail_run_conversation(_assistant: DummyAssistant) -> None:
        raise AssertionError("run_conversation should not be called for single-turn prompt")

    monkeypatch.setattr("app.main.Assistant", lambda thread_id, project_path, user_path, verbose: assistant)
    monkeypatch.setattr("app.main.run_single_turn", fake_run_single_turn)
    monkeypatch.setattr("app.main.run_conversation", fail_run_conversation)

    app_main.deploy_assistant(
        thread_id="cid-999",
        verbose=False,
        project_path="pp-999",
        user_path="up-999",
        single_turn_prompt=prompt,
    )

    out = capsys.readouterr().out
    assert captured["run_single_turn_called"] == (assistant, prompt)
    assert response_text in out
    assert assistant.closed is True


def test_main_single_turn_prompt_runs_single_turn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assistant = DummyAssistant(thread_id="cid-555", project_path="pp-555", user_path="up-555", verbose=False)
    prompt = "hola"
    response_text = "respuesta"
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "app.main.parse_conversation_arguments",
        lambda: SimpleNamespace(
            conversation_id="cid-555",
            verbose=False,
            project_path="pp-555",
            user_path="up-555",
            single_turn_prompt=prompt,
        ),
    )

    def fake_run_single_turn(fake_assistant: DummyAssistant, fake_prompt: str) -> str:
        captured["run_single_turn_called"] = (fake_assistant, fake_prompt)
        return response_text

    def fail_run_conversation(_assistant: DummyAssistant) -> None:
        raise AssertionError("run_conversation should not be called for single-turn prompt")

    monkeypatch.setattr("app.main.Assistant", lambda thread_id, project_path, user_path, verbose: assistant)
    monkeypatch.setattr("app.main.run_single_turn", fake_run_single_turn)
    monkeypatch.setattr("app.main.run_conversation", fail_run_conversation)

    app_main.main()

    out = capsys.readouterr().out
    assert captured["run_single_turn_called"] == (assistant, prompt)
    assert response_text in out
    assert assistant.closed is True
