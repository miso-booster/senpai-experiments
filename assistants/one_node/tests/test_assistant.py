"""Tests for the Assistant high-level interface."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.assistant.assistant import Assistant, _resolve_db_path


class DummyGraph:
    """Imitation of the LangGraph graph for testing."""

    def __init__(self, snapshots: List[Dict[str, Any]], checkpoint: Any = None) -> None:  # noqa: ANN401
        self._snapshots = snapshots
        self._checkpoint = checkpoint
        self.stream_calls: List[Dict[str, Any]] = []
        self.get_state_calls: List[Dict[str, Any]] = []

    def stream(self, state: Dict[str, Any], config: Dict[str, Any], stream_mode: str) -> Iterator[Dict[str, Any]]:
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
    """Replace that the assistant creates a LangGraph graph with a dummy graph."""

    def _factory(graph: DummyGraph) -> Assistant:
        # Replace graph creation to return the dummy graph
        monkeypatch.setattr(
            "app.assistant.assistant.create_assistant_graph",
            lambda _model, _checkpointer, project_path="", user_path="", verbose=False: graph,
        )

        # Replace model initialization to return a dummy model
        monkeypatch.setattr(
            "app.assistant.assistant.init_chat_model",
            lambda *a, **kw: DummyModel(AIMessage(content="unused")),
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
    """Check the send_message method returns the AI response from the graph stream."""

    graph = DummyGraph([{"messages": [AIMessage(content="ready")]}])
    assistant = make_assistant(graph)

    response = assistant.send_message("Hello")

    assert response == "ready"
    call = graph.stream_calls[0]
    sent_message = call["state"]["messages"][0]
    assert isinstance(sent_message, HumanMessage)
    assert sent_message.content == "Hello"
    assert call["config"]["configurable"]["thread_id"] == assistant.thread_id


def test_send_message_uses_checkpoint_fallback(make_assistant: Any) -> None:  # noqa: ANN401
    """Check that the conversation resumes from the checkpoint."""

    checkpoint = SimpleNamespace(values={"messages": [AIMessage(content="from checkpoint")]})
    graph = DummyGraph([{}], checkpoint=checkpoint)
    assistant = make_assistant(graph)

    response = assistant.send_message("Hola")

    assert response == "from checkpoint"
    assert graph.get_state_calls


def test_send_message_requires_string(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that send_message fails if it is not a string."""

    graph = DummyGraph([])
    assistant = make_assistant(graph)

    with pytest.raises(TypeError):
        assistant.send_message(123)


def test_send_message_raises_when_closed(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that send_message fails if the assistant is closed."""

    graph = DummyGraph([])
    assistant = make_assistant(graph)
    assistant.close()

    with pytest.raises(RuntimeError):
        assistant.send_message("again")


def test_close_is_idempotent(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that calling close multiple times is safe."""

    graph = DummyGraph([])
    assistant = make_assistant(graph)

    assistant.close()
    assistant.close()

    assert assistant._closed is True  # noqa: SLF001


def test_send_message_uses_custom_thread_id(make_assistant: Any) -> None:  # noqa: ANN401
    """Test that send_message uses the provided thread ID over the default."""

    graph = DummyGraph([{"messages": [AIMessage(content="ok")]}])
    assistant = make_assistant(graph)

    assistant.thread_id = "custom-thread"
    assistant.send_message("Hi", thread_id="manual-thread")

    assert graph.stream_calls[-1]["config"]["configurable"]["thread_id"] == "manual-thread"
