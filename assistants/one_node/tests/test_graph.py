from __future__ import annotations

from typing import Any, List, cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver

from app.assistant.graph import create_assistant_graph
from app.assistant.prompt import PROMPT_NODE_GUIDELINES
from app.nodes.answer import node_prompt


class RecordingModel:
    """Mock LLM that records prompts and returns a preset reply."""

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: List[List[Any]] = []

    def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
        self.calls.append(messages)
        return AIMessage(content=self.reply)


def _get_system_message(messages: List[Any]) -> SystemMessage:
    return next(msg for msg in messages if isinstance(msg, SystemMessage))


def test_graph_uses_single_unified_node() -> None:
    model = RecordingModel("ready")
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)

    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-1"}})
    snapshots = list(graph.stream({"messages": [HumanMessage(content="hola")]}, config, stream_mode="values"))

    assert snapshots, "graph produced no snapshots"
    final_messages = snapshots[-1]["messages"]
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "ready"

    assert len(model.calls) == 1, "expected a single model call in the unified flow"
    system_message = _get_system_message(model.calls[0])
    assert "Assistant Responsibilities" in cast(str, system_message.content)
    assert PROMPT_NODE_GUIDELINES.strip().splitlines()[1] in cast(str, system_message.content)


def test_graph_streams_without_checkpointer_and_config() -> None:
    model = RecordingModel("no-checkpoint")
    graph = create_assistant_graph(cast(BaseChatModel, model), checkpointer=None)

    snapshots = list(
        graph.stream(
            {"messages": [HumanMessage(content="hola sin cid")]},
            None,
            stream_mode="values",
        )
    )

    assert snapshots, "graph produced no snapshots without a checkpointer"
    final_messages = snapshots[-1]["messages"]
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "no-checkpoint"
    assert model.calls, "model was not invoked by the node"


def test_graph_writes_checkpoint() -> None:
    model = RecordingModel("yo")
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-2"}})

    list(graph.stream({"messages": [HumanMessage(content="hola de nuevo")]}, config, stream_mode="values"))

    state = graph.get_state(config)
    assert getattr(state, "values", None), "no state values found"
    msgs = state.values.get("messages", [])
    assert msgs and isinstance(msgs[-1], AIMessage) and msgs[-1].content == "yo"


def test_graph_includes_project_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_context(_messages: list[Any], _project: Any, state: bool = False) -> str:  # noqa: ANN401
        assert state is True
        return "### User Project Context\nrule: sample"

    monkeypatch.setattr(node_prompt, "resolve_project_context", fake_context)
    monkeypatch.setattr(node_prompt, "resolve_user_context", lambda *_args, **_kwargs: "### User Folder Context\nx: y")

    model = RecordingModel("with-context")
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver, project_path=None, user_path=None)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-ctx"}})

    list(graph.stream({"messages": [HumanMessage(content="hola")]}, config, stream_mode="values"))

    system_message = _get_system_message(model.calls[0])
    assert "rule: sample" in cast(str, system_message.content)
    assert "### User Folder Context" in cast(str, system_message.content)
