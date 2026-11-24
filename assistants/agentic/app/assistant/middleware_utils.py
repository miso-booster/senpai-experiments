"""Shared helpers for agent middleware implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from langchain.agents import AgentState
from langchain_core.messages import AIMessage, HumanMessage


def get_state_messages(state: AgentState[Any]) -> list[Any]:
    """Extract messages from the agent state.

    Args:
        state: Current agent state.

    Returns:
        The messages list, or an empty list when unavailable.
    """
    state_get = getattr(state, "get", None)
    raw_messages: object = state_get("messages", []) if callable(state_get) else []
    return raw_messages if isinstance(raw_messages, list) else []


def get_latest_ai_message(messages: Sequence[Any]) -> AIMessage | None:
    """Locate the latest AIMessage in the message history.

    Args:
        messages: Message list to search.

    Returns:
        The most recent AIMessage, or None when not found.
    """
    return next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)


def get_latest_human_text(messages: Sequence[Any]) -> str:
    """Return the latest human message content as text.

    Args:
        messages: Message list to search.

    Returns:
        The latest human message content, or an empty string if missing.
    """
    user_msg = next(
        (msg for msg in reversed(messages) if isinstance(msg, HumanMessage) and isinstance(msg.content, str)),
        None,
    )
    return cast(str, user_msg.content) if user_msg else ""


__all__ = ["get_state_messages", "get_latest_ai_message", "get_latest_human_text"]
