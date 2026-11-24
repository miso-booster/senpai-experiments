"""Tests for the Assistant high-level interface."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command, Interrupt

from app.assistant.assistant import Assistant, _resolve_db_path
from app.assistant.status_messages import StatusEvent


class DummyAgent:
    """Imitation of the LangChain agent for testing."""

    def __init__(self, snapshots: List[Dict[str, Any] | str], checkpoint: Any = None) -> None:  # noqa: ANN401
        self._snapshots = snapshots
        self._checkpoint = checkpoint
        self.stream_calls: List[Dict[str, Any]] = []
        self.get_state_calls: List[Dict[str, Any]] = []

    def stream(
        self, state: Dict[str, Any] | Command[object], config: Dict[str, Any], stream_mode: str | list[str]
    ) -> Iterator[Any]:
        self.stream_calls.append({"state": state, "config": config, "stream_mode": stream_mode})
        yield from self._snapshots

    def get_state(self, config: Dict[str, Any]) -> Any:  # noqa: ANN401
        self.get_state_calls.append(config)
        return self._checkpoint


class DummyModel:
    """Imitation of a language model for testing."""

    def __init__(self, response: AIMessage | None = None) -> None:
        self.response = response or AIMessage(content="unused")

    def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
        return self.response


@pytest.fixture
def make_assistant(monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: ANN401
    """Replace the assistant's agent creation with a dummy agent."""

    def _factory(agent: DummyAgent) -> Assistant:
        monkeypatch.setattr(
            "app.assistant.assistant.create_assistant_agent",
            lambda _model, _checkpointer, project_path=None, embedding_path=None, **_: agent,
        )

        # Replace model initialization to return a dummy model
        monkeypatch.setattr(
            "app.assistant.assistant.init_chat_model",
            lambda *a, **_: DummyModel(AIMessage(content="unused")),
        )

        # Return the assistant instance
        return Assistant(model=None, checkpointer=None)

    return _factory


def test_resolve_db_path_custom(tmp_path: Path) -> None:
    """Test that it correctly uses a custom database path."""

    custom_path = tmp_path / "memory.db"

    resolved = _resolve_db_path(custom_path)

    assert resolved == custom_path


def test_resolve_db_path_default_location() -> None:
    """Test that it uses the default database path."""

    resolved = _resolve_db_path(None)

    assert resolved.name == "senpai_memory.db"
    assert resolved.parent.name == "data"


def test_send_message_returns_streamed_ai_response(make_assistant: Any) -> None:  # noqa: ANN401
    """Check the send_message method returns the AI response from the agent stream."""

    agent = DummyAgent([{"messages": [AIMessage(content="ready")]}])
    assistant = make_assistant(agent)

    response = assistant.send_message("Hello")

    assert response == "ready"
    call = agent.stream_calls[0]
    sent_message = call["state"]["messages"][0]
    assert isinstance(sent_message, HumanMessage)
    assert sent_message.content == "Hello"
    assert call["config"]["configurable"]["thread_id"] == assistant.thread_id


def test_send_message_uses_checkpoint_fallback(make_assistant: Any) -> None:  # noqa: ANN401
    """Check that the conversation resumes from the checkpoint."""

    checkpoint = SimpleNamespace(values={"messages": [AIMessage(content="from checkpoint")]})
    agent = DummyAgent([{}], checkpoint=checkpoint)
    assistant = make_assistant(agent)

    response = assistant.send_message("Hola")

    assert response == "from checkpoint"
    assert agent.get_state_calls


def test_send_message_requires_string(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that send_message fails if it is not a string."""

    agent = DummyAgent([])
    assistant = make_assistant(agent)

    with pytest.raises(TypeError):
        assistant.send_message(123)


def test_send_message_raises_when_closed(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that send_message fails if the assistant is closed."""

    agent = DummyAgent([])
    assistant = make_assistant(agent)
    assistant.close()

    with pytest.raises(RuntimeError):
        assistant.send_message("again")


def test_close_is_idempotent(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that calling close multiple times is safe."""

    agent = DummyAgent([])
    assistant = make_assistant(agent)

    assistant.close()
    assistant.close()

    assert assistant._closed is True  # noqa: SLF001


def test_send_message_uses_custom_thread_id(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that send_message uses the provided thread ID over the default."""

    agent = DummyAgent([{"messages": [AIMessage(content="ok")]}])
    assistant = make_assistant(agent)

    assistant.thread_id = "custom-thread"
    assistant.send_message("Hi", thread_id="manual-thread")

    assert agent.stream_calls[-1]["config"]["configurable"]["thread_id"] == "manual-thread"


def test_refresh_pending_interrupts_reads_checkpoint_interrupts(make_assistant: Any) -> None:  # noqa: ANN401
    """Ensure pending interrupts are loaded from checkpoint metadata."""
    checkpoint = SimpleNamespace(values={}, interrupts=(Interrupt(value={"ok": True}, id="hitl-1"),))
    agent = DummyAgent([], checkpoint=checkpoint)
    assistant = make_assistant(agent)

    interrupts = assistant.refresh_pending_interrupts()

    assert len(interrupts) == 1
    assert interrupts[0].id == "hitl-1"


def test_send_message_blocks_when_pending_interrupts(make_assistant: Any) -> None:  # noqa: ANN401
    """Prevent new model calls while pending approvals exist."""
    checkpoint = SimpleNamespace(values={}, interrupts=(Interrupt(value={"ok": True}, id="hitl-2"),))
    agent = DummyAgent([], checkpoint=checkpoint)
    assistant = make_assistant(agent)

    with pytest.raises(RuntimeError, match="Pending approvals must be resolved"):
        assistant.send_message("hi")


def test_resume_pending_interrupts_returns_empty_without_interrupts(make_assistant: Any) -> None:  # noqa: ANN401
    """Return empty string when there are no pending interrupts."""
    agent = DummyAgent([])
    assistant = make_assistant(agent)

    result = assistant.resume_pending_interrupts([{"decision": "approve"}])

    assert result == ""
    assert agent.stream_calls == []


def test_resume_pending_interrupts_uses_list_decisions(make_assistant: Any) -> None:  # noqa: ANN401
    """Wrap list decisions in the expected resume payload."""
    agent = DummyAgent([{"messages": [AIMessage(content="resumed")]}])
    assistant = make_assistant(agent)
    assistant._last_interrupts = [Interrupt(value={"tool": "save_profile"}, id="hitl-1")]  # noqa: SLF001

    result = assistant.resume_pending_interrupts([{"decision": "approve"}])

    assert result == "resumed"
    assert assistant._last_interrupts == []  # noqa: SLF001
    state = agent.stream_calls[0]["state"]
    assert isinstance(state, Command)
    assert state.resume == {"decisions": [{"decision": "approve"}]}


def test_resume_pending_interrupts_rejects_list_for_multiple(make_assistant: Any) -> None:  # noqa: ANN401
    """Require decision mappings when multiple interrupts are pending."""
    agent = DummyAgent([])
    assistant = make_assistant(agent)
    assistant._last_interrupts = [  # noqa: SLF001
        Interrupt(value={}, id="hitl-1"),
        Interrupt(value={}, id="hitl-2"),
    ]

    with pytest.raises(ValueError, match="Multiple interrupts"):
        assistant.resume_pending_interrupts([{"decision": "approve"}])


def test_resume_pending_interrupts_accepts_mapping(make_assistant: Any) -> None:  # noqa: ANN401
    """Pass decision mappings through unchanged."""
    agent = DummyAgent([{"messages": [AIMessage(content="done")]}])
    assistant = make_assistant(agent)
    assistant._last_interrupts = [  # noqa: SLF001
        Interrupt(value={}, id="hitl-1"),
        Interrupt(value={}, id="hitl-2"),
    ]
    decisions = {"hitl-1": {"decision": "approve"}, "hitl-2": {"decision": "reject"}}

    result = assistant.resume_pending_interrupts(decisions)

    assert result == "done"
    assert assistant._last_interrupts == []  # noqa: SLF001
    state = agent.stream_calls[0]["state"]
    assert isinstance(state, Command)
    assert state.resume == decisions


def test_stream_response_updates_interrupts_and_returns_latest_message(make_assistant: Any) -> None:  # noqa: ANN401
    interrupts = [Interrupt(value={"action_requests": []}, id="hitl-3")]
    agent = DummyAgent(
        [
            {"__interrupt__": interrupts, "messages": [HumanMessage(content="hi"), AIMessage(content="first")]},
            {"messages": [AIMessage(content="final")]},
        ]
    )
    assistant = make_assistant(agent)

    run_config = assistant._build_run_config(assistant.thread_id)  # noqa: SLF001
    result = assistant._stream_response({"messages": []}, run_config)  # noqa: SLF001

    assert result == "final"
    assert assistant._last_interrupts == interrupts  # noqa: SLF001


def test_stream_response_falls_back_to_checkpoint(make_assistant: Any) -> None:  # noqa: ANN401
    checkpoint = SimpleNamespace(
        values={"messages": [AIMessage(content="from checkpoint")]},
        interrupts=(Interrupt(value={"action_requests": []}, id="hitl-4"),),
    )
    agent = DummyAgent([{"messages": [AIMessage(content=[{"text": "ignored"}])]}], checkpoint=checkpoint)
    assistant = make_assistant(agent)

    run_config = assistant._build_run_config(assistant.thread_id)  # noqa: SLF001
    result = assistant._stream_response({"messages": []}, run_config)  # noqa: SLF001

    assert result == "from checkpoint"
    assert assistant._last_interrupts and assistant._last_interrupts[0].id == "hitl-4"  # noqa: SLF001


def test_send_message_emits_tool_status_events(make_assistant: Any) -> None:  # noqa: ANN401
    events: List[Any] = []

    def status_callback(update: Any) -> None:  # noqa: ANN401
        events.append(update)

    agent = DummyAgent(
        [
            {
                "messages": [
                    AIMessage(
                        content="step",
                        tool_calls=[{"name": "search_rules", "args": {"q": "hi"}, "id": "tool-1"}],
                    )
                ]
            },
            {
                "messages": [
                    AIMessage(
                        content="final",
                        tool_calls=[{"name": "search_rules", "args": {"q": "hi"}, "id": "tool-1"}],
                    )
                ]
            },
        ]
    )
    assistant = make_assistant(agent)

    response = assistant.send_message("Hello", status_callback=status_callback)

    assert response == "final"
    assert events and events[0] == "Thinking..."
    tool_events = [event for event in events if isinstance(event, StatusEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].text == "Using tool: search_rules..."
    assert tool_events[0].is_tool is True


def test_resume_pending_interrupts_emits_status_callback(make_assistant: Any) -> None:  # noqa: ANN401
    events: List[Any] = []

    def status_callback(update: Any) -> None:  # noqa: ANN401
        events.append(update)

    agent = DummyAgent([{"messages": [AIMessage(content="resumed")]}])
    assistant = make_assistant(agent)
    assistant._last_interrupts = [Interrupt(value={"tool": "approve"}, id="hitl-1")]  # noqa: SLF001

    response = assistant.resume_pending_interrupts([{"decision": "approve"}], status_callback=status_callback)

    assert response == "resumed"
    assert events and events[0] == "Thinking..."


def test_stream_response_checkpoint_skips_empty_ai_message(make_assistant: Any) -> None:  # noqa: ANN401
    checkpoint = SimpleNamespace(
        values={"messages": [AIMessage(content="from checkpoint"), AIMessage(content="")]},
    )
    agent = DummyAgent([{"messages": [AIMessage(content=[{"text": "ignored"}])]}], checkpoint=checkpoint)
    assistant = make_assistant(agent)

    run_config = assistant._build_run_config(assistant.thread_id)  # noqa: SLF001
    result = assistant._stream_response({"messages": []}, run_config)  # noqa: SLF001

    assert result == "from checkpoint"


def test_stream_response_handles_non_dict_snapshots(make_assistant: Any) -> None:  # noqa: ANN401
    agent = DummyAgent(["noop", {"messages": [HumanMessage(content="hi")]}])
    assistant = make_assistant(agent)

    run_config = assistant._build_run_config(assistant.thread_id)  # noqa: SLF001
    result = assistant._stream_response({"messages": []}, run_config)  # noqa: SLF001

    assert result == ""
