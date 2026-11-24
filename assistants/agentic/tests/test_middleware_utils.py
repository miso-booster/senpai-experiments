from __future__ import annotations

from typing import Any

from langchain.agents import AgentState
from langchain_core.messages import AIMessage, HumanMessage

from app.assistant.middleware_utils import (
    get_latest_ai_message,
    get_latest_human_text,
    get_state_messages,
)


def test_get_state_messages_returns_list() -> None:
    state: AgentState[Any] = {"messages": [HumanMessage(content="hi")]}

    messages = get_state_messages(state)

    assert messages == state["messages"]


def test_get_state_messages_handles_non_list() -> None:
    state: dict[str, object] = {"messages": "nope"}

    messages = get_state_messages(state)  # type: ignore[arg-type]

    assert messages == []


def test_get_latest_ai_message_returns_last_ai() -> None:
    messages = [HumanMessage(content="hi"), AIMessage(content="one"), AIMessage(content="two")]

    latest = get_latest_ai_message(messages)

    assert isinstance(latest, AIMessage)
    assert latest.content == "two"


def test_get_latest_human_text_skips_non_text() -> None:
    messages = [
        HumanMessage(content="first"),
        HumanMessage(content=[{"type": "text", "text": "skip"}]),
        AIMessage(content="ignored"),
    ]

    latest = get_latest_human_text(messages)

    assert latest == "first"
