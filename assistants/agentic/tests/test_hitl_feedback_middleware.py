from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from langchain.agents import AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage
from langgraph.runtime import Runtime

from app.assistant.hitl_feedback_middleware import HitlFeedbackMiddleware


def test_hitl_feedback_skips_without_tool_calls() -> None:
    middleware = HitlFeedbackMiddleware()
    state: AgentState[Any] = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is None


def test_hitl_feedback_prompts_retry_on_rejection() -> None:
    middleware = HitlFeedbackMiddleware()
    tool_call = {"id": "tool-1", "name": "save_profile", "args": {}, "type": "tool_call"}
    assistant_msg = AIMessage(content="here you go", tool_calls=[tool_call])
    rejection = ToolMessage(
        content="change this section",
        name="save_profile",
        tool_call_id="tool-1",
        status="error",
    )
    state: AgentState[Any] = {"messages": [HumanMessage(content="make profile"), assistant_msg, rejection]}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is not None
    assert update.get("jump_to") == "model"
    assert assistant_msg.tool_calls == [tool_call]
    assert any(isinstance(msg, HumanMessage) and "rejected" in msg.content for msg in update["messages"])


def test_hitl_feedback_skips_with_pending_tool_calls() -> None:
    middleware = HitlFeedbackMiddleware()
    rejected_call = {"id": "tool-1", "name": "save_profile", "args": {}, "type": "tool_call"}
    approved_call = {"id": "tool-2", "name": "delete_profile", "args": {}, "type": "tool_call"}
    assistant_msg = AIMessage(content="doing both", tool_calls=[rejected_call, approved_call])
    rejection = ToolMessage(
        content="don't create it",
        name="save_profile",
        tool_call_id="tool-1",
        status="error",
    )
    state: AgentState[Any] = {"messages": [HumanMessage(content="do stuff"), assistant_msg, rejection]}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is None


def test_hitl_feedback_multiple_rejections_formats_feedback() -> None:
    middleware = HitlFeedbackMiddleware()
    tool_calls = [
        {"id": "tool-1", "name": "save_profile", "args": {}, "type": "tool_call"},
        {"id": "tool-2", "name": "delete_profile", "args": {}, "type": "tool_call"},
    ]
    assistant_msg = AIMessage(content="doing both", tool_calls=tool_calls)
    rejection_one = ToolMessage(
        content="fix profile fields",
        name="save_profile",
        tool_call_id="tool-1",
        status="error",
    )
    rejection_two = ToolMessage(
        content="don't delete yet",
        name="delete_profile",
        tool_call_id="tool-2",
        status="error",
    )
    state: AgentState[Any] = {
        "messages": [HumanMessage(content="do stuff"), assistant_msg, rejection_one, rejection_two]
    }

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is not None
    prompt = next(msg for msg in update["messages"] if isinstance(msg, HumanMessage)).content
    assert "- save_profile: fix profile fields" in prompt
    assert "- delete_profile: don't delete yet" in prompt


def test_hitl_feedback_ignores_approved_tool_messages() -> None:
    middleware = HitlFeedbackMiddleware()
    tool_calls = [
        {"id": "tool-1", "name": "save_profile", "args": {}, "type": "tool_call"},
        {"id": "tool-2", "name": "delete_profile", "args": {}, "type": "tool_call"},
    ]
    assistant_msg = AIMessage(content="doing both", tool_calls=tool_calls)
    rejection = ToolMessage(
        content="fix profile fields",
        name="save_profile",
        tool_call_id="tool-1",
        status="error",
    )
    approval = ToolMessage(
        content="ok",
        name="delete_profile",
        tool_call_id="tool-2",
        status="success",
    )
    state: AgentState[Any] = {"messages": [HumanMessage(content="do stuff"), assistant_msg, rejection, approval]}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is not None
    prompt = next(msg for msg in update["messages"] if isinstance(msg, HumanMessage)).content
    assert "- save_profile: fix profile fields" in prompt
    assert "delete_profile" not in prompt


def test_hitl_feedback_skips_without_rejections() -> None:
    middleware = HitlFeedbackMiddleware()
    tool_call = {"id": "tool-1", "name": "save_profile", "args": {}, "type": "tool_call"}
    assistant_msg = AIMessage(content="here you go", tool_calls=[tool_call])
    approval = ToolMessage(
        content="ok",
        name="save_profile",
        tool_call_id="tool-1",
        status="success",
    )
    state: AgentState[Any] = {"messages": [HumanMessage(content="make profile"), assistant_msg, approval]}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is None


def test_hitl_feedback_skips_on_empty_state() -> None:
    middleware = HitlFeedbackMiddleware()
    state: AgentState[Any] = {"messages": []}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is None


def test_hitl_feedback_skips_without_ai_message() -> None:
    middleware = HitlFeedbackMiddleware()
    state: AgentState[Any] = {"messages": [HumanMessage(content="hello")]}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is None


def test_hitl_feedback_skips_tool_calls_without_ids() -> None:
    middleware = HitlFeedbackMiddleware()
    tool_call: ToolCall = {"id": None, "name": "save_profile", "args": {}, "type": "tool_call"}
    assistant_msg = AIMessage(content="here you go", tool_calls=[tool_call])
    state: AgentState[Any] = {"messages": [HumanMessage(content="make profile"), assistant_msg]}

    update = middleware.after_model(state, cast(Runtime[Any], SimpleNamespace()))

    assert update is None
