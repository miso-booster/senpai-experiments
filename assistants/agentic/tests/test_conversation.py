"""Tests for the interactive conversation loop."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Tuple, cast

import pytest
from langgraph.types import Interrupt
from prompt_toolkit.formatted_text import HTML

import app.assistant.conversation as conversation
from app.assistant.assistant import Assistant
from app.assistant.status_messages import StatusEvent, StatusUpdate

NoConsoleError = cast(
    type[BaseException],
    getattr(conversation, "NoConsoleScreenBufferError"),  # noqa: B009 (access is guarded at runtime)
)


class StubAssistant:
    """Mock assistant for testing the conversation loop."""

    def __init__(self) -> None:
        self.messages: List[str] = []
        self.replies: Deque[str] = deque(["response"])

    def send_message(self, message: str, **_: Any) -> str:
        self.messages.append(message)
        return self.replies.popleft()


def test_run_single_turn_returns_resumed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_single_turn should send the message and return the resumed response."""

    assistant = StubAssistant()
    assistant.replies = deque(["initial"])

    captured: Dict[str, object] = {}

    def fake_resume(assistant_arg: Assistant, response: str, **_: object) -> str:
        captured["assistant"] = assistant_arg
        captured["response"] = response
        return "resumed"

    monkeypatch.setattr(conversation, "_resume_after_interrupts", fake_resume)

    result = conversation.run_single_turn(cast(Assistant, assistant), "hola")

    assert assistant.messages == ["hola"]
    assert captured["assistant"] is cast(Assistant, assistant)
    assert captured["response"] == "initial"
    assert result == "resumed"


def test_run_single_turn_returns_fallback_on_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_single_turn should fall back when the response is empty."""

    assistant = StubAssistant()
    assistant.replies = deque([""])

    monkeypatch.setattr(conversation, "_resume_after_interrupts", lambda _assistant, _resp, **_: "")

    result = conversation.run_single_turn(cast(Assistant, assistant), "hola")

    assert result == "(no response)"


def test_run_single_turn_handles_pending_approval_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_single_turn should return fallback when approvals are pending."""

    class PendingApprovalAssistant(StubAssistant):
        def send_message(self, message: str, **_: Any) -> str:
            raise RuntimeError("Pending approvals must be resolved before sending a new message.")

    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: printed.append((args, kwargs)))

    assistant = PendingApprovalAssistant()

    result = conversation.run_single_turn(cast(Assistant, assistant), "hola")

    assert result == "(no response)"
    printed_args = [entry[0] for entry in printed]
    assert any(
        "Pending approvals must be resolved before continuing." in (args[0] if args else "") for args in printed_args
    )


def test_run_conversation_processes_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the conversation loop works correctly and exits on 'exit'."""
    inputs: Deque[str] = deque(["hola", "exit"])
    monkeypatch.setattr("builtins.input", lambda: inputs.popleft())

    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    def capture_print(*args: Any, **kwargs: Any) -> None:
        printed.append((args, kwargs))

    monkeypatch.setattr(conversation.console, "print", capture_print)

    assistant = StubAssistant()
    conversation.run_conversation(cast(Assistant, assistant))

    assert assistant.messages == ["hola"]
    printed_args = [entry[0] for entry in printed]
    assert any("Press Ctrl+C" in (args[0] if args else "") for args in printed_args)
    assert any("Ending session" in (args[0] if args else "") for args in printed_args)
    assert ("[bold blue]Senpai:[/bold blue] response",) in printed_args


def test_run_conversation_allows_spanish_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the conversation loop exits on 'salir'."""
    inputs: Deque[str] = deque(["salir"])
    monkeypatch.setattr("builtins.input", lambda: inputs.popleft())

    assistant = StubAssistant()
    conversation.run_conversation(cast(Assistant, assistant))

    assert assistant.messages == []


def test_multiline_input_uses_prompt_toolkit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the multiline path returns prompt_toolkit input."""
    captured_kwargs: Dict[str, Any] = {}
    recorded_bindings: List[Tuple[str, ...]] = []
    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    class DummyKeyBindings:
        def add(self, *keys: str, **_: Any) -> Callable[[Any], Any]:
            def decorator(func: Any) -> Any:
                recorded_bindings.append(tuple(keys))
                return func

            return decorator

    class DummySession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

        def prompt(self) -> str:
            return "line 1\nline 2"

    monkeypatch.setattr(conversation, "KeyBindings", DummyKeyBindings)
    monkeypatch.setattr(conversation, "PromptSession", DummySession)
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: printed.append((args, kwargs)))

    message = conversation._multiline_input()

    assert message == "line 1\nline 2"
    assert captured_kwargs.get("multiline") is True
    prompt_message = captured_kwargs.get("message")
    assert isinstance(prompt_message, HTML)
    assert prompt_message.value == "<ansigreen><b>You:</b></ansigreen> "
    assert isinstance(captured_kwargs.get("key_bindings"), DummyKeyBindings)
    assert ("c-k",) in recorded_bindings and ("enter",) in recorded_bindings
    assert printed == []


def test_multiline_input_fallbacks_on_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback to standard input when the console buffer is unavailable."""

    def raising_session(*args: Any, **kwargs: Any) -> Any:
        raise NoConsoleError()

    inputs: Deque[str] = deque(["fallback message"])
    recorded: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    monkeypatch.setattr(conversation, "PromptSession", raising_session)
    monkeypatch.setattr(conversation.console, "input", lambda *args, **kwargs: inputs.popleft())
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: recorded.append((args, kwargs)))

    message = conversation._multiline_input()

    assert message == "fallback message"
    assert recorded == []


def test_multiline_input_fallbacks_on_eof_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback to standard input when prompt_toolkit raises EOFError."""

    class EOFSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def prompt(self) -> str:
            raise EOFError

    inputs: Deque[str] = deque(["typed input"])
    monkeypatch.setattr(conversation, "PromptSession", EOFSession)
    monkeypatch.setattr(conversation.console, "input", lambda *args, **kwargs: inputs.popleft())
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: None)

    message = conversation._multiline_input()

    assert message == "typed input"


def test_multiline_input_verbose_message(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Log a helpful message when verbose mode is enabled."""

    def raising_session(*args: Any, **kwargs: Any) -> Any:
        raise NoConsoleError()

    inputs: Deque[str] = deque(["msg"])

    monkeypatch.setattr(conversation, "PromptSession", raising_session)
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(conversation.console, "input", lambda *args, **kwargs: inputs.popleft())

    with caplog.at_level(logging.WARNING, logger=conversation.logger.name):
        conversation._multiline_input()

    assert any("Multiline mode is not available" in record.message for record in caplog.records)


def test_run_with_status_keeps_tool_status_during_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    updates: List[str] = []

    class DummyStatus:
        def update(self, text: str) -> None:
            updates.append(text)

        def __enter__(self) -> "DummyStatus":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(conversation.console, "status", lambda *args, **kwargs: DummyStatus())

    def action(update: Callable[[StatusUpdate], None]) -> str:
        update(StatusEvent(text="Reading docs...", is_tool=True))
        time.sleep(0.6)
        return "done"

    result = conversation._run_with_status(action)

    assert result == "done"
    assert updates == ["Reading docs..."]


def test_run_conversation_interrupts_from_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl+C during input should end the loop gracefully without sending a message."""

    def raising_input() -> str:
        raise KeyboardInterrupt

    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    monkeypatch.setattr(conversation, "_multiline_input", raising_input)
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: printed.append((args, kwargs)))

    assistant = StubAssistant()

    conversation.run_conversation(cast(Assistant, assistant))

    assert assistant.messages == []
    assert any("Session interrupted (Ctrl+C)" in (args[0] if args else "") for args, _ in printed)


def test_run_conversation_interrupts_during_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl+C while sending a message should exit cleanly."""

    class InterruptingAssistant(StubAssistant):
        def send_message(self, message: str, **_: Any) -> str:
            self.messages.append(message)
            raise KeyboardInterrupt

    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    monkeypatch.setattr(conversation, "_multiline_input", lambda: "hola")
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: printed.append((args, kwargs)))

    assistant = InterruptingAssistant()

    conversation.run_conversation(cast(Assistant, assistant))

    assert assistant.messages == ["hola"]
    assert any("Session interrupted (Ctrl+C)" in (args[0] if args else "") for args, _ in printed)


def test_run_conversation_handles_pending_approval_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class PendingApprovalAssistant(StubAssistant):
        def send_message(self, message: str, **_: Any) -> str:
            raise RuntimeError("Pending approvals must be resolved before sending a new message.")

    inputs: Deque[str] = deque(["hola", "exit"])
    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    monkeypatch.setattr(conversation, "_multiline_input", lambda: inputs.popleft())
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: printed.append((args, kwargs)))

    assistant = PendingApprovalAssistant()

    conversation.run_conversation(cast(Assistant, assistant))

    printed_args = [entry[0] for entry in printed]
    assert any(
        "Pending approvals must be resolved before continuing." in (args[0] if args else "") for args in printed_args
    )


def test_is_exit_command_accepts_variants() -> None:
    """Exit helper should recognize common exit phrases."""
    assert conversation._is_exit_command("exit")
    assert conversation._is_exit_command("  SALIR  ")
    assert conversation._is_exit_command("Quit")
    assert conversation._is_exit_command("quit")
    assert not conversation._is_exit_command("continue")


def test_print_exit_hint_outputs_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup hint should tell users how to exit."""
    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []
    monkeypatch.setattr(conversation.console, "print", lambda *args, **kwargs: printed.append((args, kwargs)))

    conversation._print_exit_hint()

    assert printed
    assert "Press Ctrl+C" in printed[-1][0][0]


def test_format_action_request_uses_description_and_fallback() -> None:
    assert conversation._format_action_request({"description": "Do it"}) == "Do it"
    assert conversation._format_action_request({"name": "tool", "args": {"x": 1}}) == "Tool: tool Args: {'x': 1}"
    assert conversation._format_action_request({}) == "Tool: unknown Args: {}"


def test_collect_interrupt_decisions_single_and_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation, "_prompt_hitl_decision", lambda _req: {"type": "approve"})

    interrupt_one = Interrupt(id="int-1", value={"action_requests": [{"name": "alpha"}]})
    interrupt_two = Interrupt(id="int-2", value={"action_requests": [{"name": "bravo"}]})

    single = conversation._collect_interrupt_decisions([interrupt_one])
    assert single == [{"type": "approve"}]

    multiple = conversation._collect_interrupt_decisions([interrupt_one, interrupt_two])
    assert multiple == {
        "int-1": {"decisions": [{"type": "approve"}]},
        "int-2": {"decisions": [{"type": "approve"}]},
    }


def test_decisions_for_interrupt_defaults_on_missing_requests() -> None:
    interrupt = Interrupt(id="int-empty", value={})

    decisions = conversation._decisions_for_interrupt(interrupt)

    assert decisions == [{"type": "reject", "message": "No action requests available for review."}]


def test_prompt_hitl_decision_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs: Deque[str] = deque(["y"])
    printed: List[str] = []

    monkeypatch.setattr("builtins.input", lambda _prompt="": inputs.popleft())
    monkeypatch.setattr(conversation.console, "print", lambda message: printed.append(message))

    decision = conversation._prompt_hitl_decision({"description": "Save profile"})

    assert decision == {"type": "approve"}
    assert any("Save profile" in message for message in printed)


def test_prompt_hitl_decision_reject_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs: Deque[str] = deque(["n", "not now"])
    printed: List[str] = []

    monkeypatch.setattr("builtins.input", lambda _prompt="": inputs.popleft())
    monkeypatch.setattr(conversation.console, "print", lambda message: printed.append(message))

    decision = conversation._prompt_hitl_decision({"name": "save_profile", "args": {"x": 1}})

    assert decision == {"type": "reject", "message": "not now"}
    assert any("Tool: save_profile" in message for message in printed)


def test_load_pending_interrupts_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    interrupt = Interrupt(id="int-3", value={})

    class PendingAssistant:
        def __init__(self) -> None:
            self.refreshed = False

        def refresh_pending_interrupts(self) -> list[Interrupt]:
            self.refreshed = True
            return [interrupt]

        def get_pending_interrupts(self) -> list[Interrupt]:
            return [interrupt]

    assistant = PendingAssistant()

    pending = conversation._load_pending_interrupts(cast(Assistant, assistant))

    assert pending == [interrupt]
    assert assistant.refreshed is True


def test_resume_after_interrupts_uses_refresh_and_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    interrupt = Interrupt(id="int-4", value={"action_requests": [{"name": "alpha"}]})

    class RefreshingAssistant:
        def __init__(self) -> None:
            self.resume_calls: List[Any] = []

        def get_pending_interrupts(self) -> list[Interrupt]:
            return []

        def refresh_pending_interrupts(self) -> list[Interrupt]:
            return [interrupt]

        def resume_pending_interrupts(self, decisions: Any) -> str:  # noqa: ANN401
            self.resume_calls.append(decisions)
            return "resumed"

    assistant = RefreshingAssistant()
    monkeypatch.setattr(conversation, "_collect_interrupt_decisions", lambda _ints: [{"type": "approve"}])

    response = conversation._resume_after_interrupts(cast(Assistant, assistant), "original")

    assert response == "resumed"
    assert assistant.resume_calls == [[{"type": "approve"}]]


def test_resume_after_interrupts_drains_nested_interrupts(monkeypatch: pytest.MonkeyPatch) -> None:
    interrupt = Interrupt(id="int-5", value={"action_requests": [{"name": "alpha"}]})

    class LoopingAssistant:
        def __init__(self) -> None:
            self.resume_calls: List[Any] = []
            self.pending_calls = 2

        def get_pending_interrupts(self) -> list[Interrupt]:
            if self.pending_calls > 0:
                self.pending_calls -= 1
                return [interrupt]
            return []

        def refresh_pending_interrupts(self) -> list[Interrupt]:
            return []

        def resume_pending_interrupts(self, decisions: Any) -> str:  # noqa: ANN401
            self.resume_calls.append(decisions)
            return "resumed"

    assistant = LoopingAssistant()
    monkeypatch.setattr(conversation, "_collect_interrupt_decisions", lambda _ints: [{"type": "approve"}])

    response = conversation._resume_after_interrupts(cast(Assistant, assistant), "original")

    assert response == "resumed"
    assert assistant.resume_calls == [[{"type": "approve"}], [{"type": "approve"}]]


def test_resolve_pending_interrupts_before_continue_prints_response(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: List[str] = []

    monkeypatch.setattr(conversation, "_load_pending_interrupts", lambda _assistant: [Interrupt(id="int-5", value={})])
    monkeypatch.setattr(conversation, "_resume_after_interrupts", lambda _assistant, _resp, **_: "done")
    monkeypatch.setattr(conversation.console, "print", lambda message: printed.append(message))

    conversation._resolve_pending_interrupts_before_continue(cast(Assistant, object()))

    assert any("Pending approvals detected" in message for message in printed)
    assert any("Senpai" in message for message in printed)


def test_handle_exit_with_pending_interrupts_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: List[str] = []
    inputs: Deque[str] = deque(["y"])

    monkeypatch.setattr(conversation, "_load_pending_interrupts", lambda _assistant: [Interrupt(id="int-6", value={})])
    monkeypatch.setattr(conversation, "_print_pending_interrupts", lambda _ints: printed.append("pending"))
    monkeypatch.setattr(conversation, "_resume_after_interrupts", lambda _assistant, _resp, **_: "follow-up")
    monkeypatch.setattr("builtins.input", lambda _prompt="": inputs.popleft())
    monkeypatch.setattr(conversation.console, "print", lambda message: printed.append(message))

    conversation._handle_exit_with_pending_interrupts(cast(Assistant, object()))

    assert "pending" in printed
    assert any("Senpai" in message for message in printed)


def test_handle_exit_with_pending_interrupts_no(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: List[str] = []
    inputs: Deque[str] = deque(["n"])

    monkeypatch.setattr(conversation, "_load_pending_interrupts", lambda _assistant: [Interrupt(id="int-7", value={})])
    monkeypatch.setattr(conversation, "_print_pending_interrupts", lambda _ints: printed.append("pending"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": inputs.popleft())
    monkeypatch.setattr(conversation.console, "print", lambda message: printed.append(message))

    conversation._handle_exit_with_pending_interrupts(cast(Assistant, object()))

    assert "pending" in printed
    assert any("Pending approvals remain" in message for message in printed)


def test_notify_pending_interrupts_prints(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: List[str] = []

    monkeypatch.setattr(conversation, "_load_pending_interrupts", lambda _assistant: [Interrupt(id="int-8", value={})])
    monkeypatch.setattr(conversation, "_print_pending_interrupts", lambda _ints: printed.append("pending"))
    monkeypatch.setattr(conversation.console, "print", lambda message: printed.append(message))

    conversation._notify_pending_interrupts(cast(Assistant, object()))

    assert "pending" in printed
    assert any("Pending approvals remain" in message for message in printed)


def test_print_pending_interrupts_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: List[str] = []
    interrupt_with_details = Interrupt(id="int-9", value={"action_requests": [{"description": "Do it"}]})
    interrupt_without_details = Interrupt(id="int-10", value={})

    monkeypatch.setattr(conversation.console, "print", lambda message: printed.append(message))

    conversation._print_pending_interrupts([interrupt_with_details, interrupt_without_details])

    assert any("Do it" in message for message in printed)
    assert any("details unavailable" in message for message in printed)
