from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Sequence, cast

from langchain.agents.middleware.types import AgentState
from langchain_core.language_models import ModelProfile
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime
from pydantic import ConfigDict

from app.assistant.agent import _format_delete_file_interrupt, _format_save_file_interrupt, create_assistant_agent
from app.assistant.prompt import build_prompt_node_system_prompt


class RecordingModel(BaseChatModel):
    """Mock LLM that records prompts and returns a preset reply."""

    model_config = ConfigDict(extra="allow")
    reply: str = "ok"

    def __init__(self, reply: str = "ok") -> None:
        super().__init__()
        self.reply = reply
        self.calls: List[List[Any]] = []

        self.profile = cast(
            ModelProfile,
            {
                "max_input_tokens": 128_000,
                "tool_calling": True,
                "structured_output": True,
            },
        )
        self.bound_tools: list[Any] | None = None
        self.bound_tool_choice: str | None = None

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: str | None = None, **_: Any) -> "RecordingModel":
        """Mimic tool binding support used by the agent factory."""
        self.bound_tools = list(tools)
        self.bound_tool_choice = tool_choice
        return self

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(  # type: ignore[override]
        self, messages: List[Any], stop: list[str] | None = None, **_: Any
    ) -> ChatResult:
        del stop
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


def _get_system_message(messages: List[Any]) -> SystemMessage:
    return next(msg for msg in messages if isinstance(msg, SystemMessage))


def _extract_text(content: Any) -> str:
    """Flatten possible structured content payloads into a text blob for assertions."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def test_agent_uses_single_unified_node() -> None:
    model = RecordingModel("ready")
    saver = InMemorySaver()
    agent = create_assistant_agent(cast(BaseChatModel, model), saver)

    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-1"}})
    snapshots = list(agent.stream({"messages": [HumanMessage(content="hola")]}, config, stream_mode="values"))

    assert snapshots, "agent produced no snapshots"
    final_messages = snapshots[-1]["messages"]
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "ready"

    assert len(model.calls) >= 1, "expected at least one model call in the unified flow"
    system_message = _get_system_message(model.calls[-1])
    sys_text = _extract_text(system_message.content)
    prompt = build_prompt_node_system_prompt()
    assert "You are Senpai" in sys_text
    assert "ABSOLUTE RULE: DOC-FIRST WORKFLOW" in sys_text
    assert "get_docs" in sys_text
    assert prompt.strip() in sys_text


def test_agent_writes_checkpoint() -> None:
    model = RecordingModel("yo")
    saver = InMemorySaver()
    agent = create_assistant_agent(cast(BaseChatModel, model), saver)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-2"}})

    list(agent.stream({"messages": [HumanMessage(content="hola de nuevo")]}, config, stream_mode="values"))

    state = agent.get_state(config)
    assert getattr(state, "values", None), "no state values found"
    msgs = state.values.get("messages", [])
    assert msgs and isinstance(msgs[-1], AIMessage) and msgs[-1].content == "yo"


def test_agent_configures_hitl_for_profile_changes() -> None:
    model = RecordingModel("ok")
    saver = InMemorySaver()
    agent = create_assistant_agent(cast(BaseChatModel, model), saver)

    graph = agent.get_graph()
    node = graph.nodes["HumanInTheLoopMiddleware.after_model"]
    middleware = node.data.__dict__["func"].__self__

    interrupt_on = middleware.interrupt_on
    assert "save_profile" in interrupt_on
    assert "delete_profile" in interrupt_on
    config = interrupt_on["save_profile"]
    assert config["allowed_decisions"] == ["approve", "reject"]
    assert callable(config["description"])

    tool_call = cast(ToolCall, {"id": "tool-1", "name": "save_profile", "args": {}})
    text = config["description"](
        tool_call, cast(AgentState[Any], {"messages": []}), cast(Runtime[Any], SimpleNamespace())
    )
    assert "- target: (unknown)" in text

    delete_config = interrupt_on["delete_profile"]
    assert delete_config["allowed_decisions"] == ["approve", "reject"]
    assert callable(delete_config["description"])


def test_agent_skips_save_tools_in_single_turn_mode() -> None:
    model = RecordingModel("ok")
    saver = InMemorySaver()
    agent = create_assistant_agent(cast(BaseChatModel, model), saver, include_create_tools=False)

    graph = agent.get_graph()
    node = graph.nodes["HumanInTheLoopMiddleware.after_model"]
    middleware = node.data.__dict__["func"].__self__

    interrupt_on = middleware.interrupt_on
    assert "save_profile" not in interrupt_on
    assert "save_rule" not in interrupt_on
    assert "save_connector" not in interrupt_on
    assert "delete_profile" in interrupt_on
    assert "delete_rule" in interrupt_on
    assert "delete_connector" in interrupt_on


def test_format_save_profile_interrupt_includes_args() -> None:
    tool_call = cast(
        ToolCall,
        {
            "id": "tool-1",
            "name": "save_profile",
            "args": {
                "filename": "alpha.yml",
                "overwrite": True,
                "content": "  name: alpha\n  kind: demo",
            },
        },
    )

    text = _format_save_file_interrupt(
        tool_call,
        cast(AgentState[Any], {"messages": []}),
        cast(Runtime[Any], SimpleNamespace()),
        label="Profile",
        target_dir=None,
    )

    assert text == (
        "Profile save request:\n"
        "- target: (unknown)\n"
        "- filename: alpha.yml\n"
        "- overwrite: True\n"
        "---- content preview ----\n"
        "  name: alpha\n"
        "  kind: demo\n"
        "-------------------------"
    )


def test_format_save_profile_interrupt_defaults() -> None:
    text = _format_save_file_interrupt(
        cast(ToolCall, {"id": "tool-2", "name": "save_profile", "args": {}}),
        cast(AgentState[Any], {"messages": []}),
        cast(Runtime[Any], SimpleNamespace()),
        label="Profile",
        target_dir=None,
    )

    assert text == (
        "Profile save request:\n"
        "- target: (unknown)\n"
        "- filename: \n"
        "- overwrite: False\n"
        "---- content preview ----\n"
        "\n"
        "-------------------------"
    )


def test_format_delete_profile_interrupt_includes_args() -> None:
    tool_call = cast(
        ToolCall,
        {
            "id": "tool-3",
            "name": "delete_profile",
            "args": {"filename": "alpha.yml"},
        },
    )

    text = _format_delete_file_interrupt(
        tool_call,
        cast(AgentState[Any], {"messages": []}),
        cast(Runtime[Any], SimpleNamespace()),
        label="Profile",
        target_dir=None,
    )

    assert text == ("Profile deletion request:\n- target: (unknown)\n- filename: alpha.yml\n")


def test_format_delete_profile_interrupt_defaults() -> None:
    text = _format_delete_file_interrupt(
        cast(ToolCall, {"id": "tool-4", "name": "delete_profile", "args": {}}),
        cast(AgentState[Any], {"messages": []}),
        cast(Runtime[Any], SimpleNamespace()),
        label="Profile",
        target_dir=None,
    )

    assert text == ("Profile deletion request:\n- target: (unknown)\n- filename: \n")


def test_recording_model_stubs_match_langchain_hooks() -> None:
    model = RecordingModel("ok")
    _ = model._llm_type
    _ = model._generate([SystemMessage(content="hi")])
    _ = model.bind_tools([])
    assert model.bound_tools == []
    assert model.bound_tool_choice is None
