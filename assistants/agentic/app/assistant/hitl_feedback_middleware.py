"""Middleware to react to HITL rejection feedback."""

from __future__ import annotations

import logging
from typing import Any, Sequence

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from app.assistant.middleware_utils import get_latest_ai_message, get_state_messages

logger = logging.getLogger(__name__)


def _format_rejection_feedback(rejections: Sequence[ToolMessage]) -> str:
    """Summarize rejection feedback for model guidance."""
    lines: list[str] = []
    for rejection in rejections:
        content = rejection.content if isinstance(rejection.content, str) else ""
        text = content.strip() or "No feedback provided."
        name = rejection.name or "tool"
        lines.append(f"- {name}: {text}")
    return "\n".join(lines)


class HitlFeedbackMiddleware(AgentMiddleware):
    """Handle HITL rejections by prompting a follow-up response or retry.

    This middleware runs after the model generates tool calls and after HITL
    decisions are recorded as ToolMessages, and it:
    - Finds tool calls from the latest AI message.
    - Detects matching rejected ToolMessages emitted by HITL decisions.
    - Skips injection when any tool call is still pending a ToolMessage, to
      preserve tool_call -> tool_message ordering.
    - Injects a HumanMessage containing the rejection feedback and jumps back
      to the model, so the assistant can revise its response.
    """

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        """Detect HITL rejections and prompt the model to respond."""
        _ = runtime
        messages = get_state_messages(state)
        if not messages:
            return None

        assistant_msg = get_latest_ai_message(messages)
        if assistant_msg is None:
            return None

        tool_calls = list(getattr(assistant_msg, "tool_calls", None) or [])
        if not tool_calls:
            return None

        tool_call_ids = {call.get("id") for call in tool_calls if isinstance(call, dict)}
        tool_call_ids.discard(None)
        if not tool_call_ids:
            return None

        rejected_messages = [
            msg
            for msg in messages
            if isinstance(msg, ToolMessage) and msg.status == "error" and msg.tool_call_id in tool_call_ids
        ]
        if not rejected_messages:
            return None

        tool_message_ids = {
            msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage) and msg.tool_call_id in tool_call_ids
        }
        pending_tool_calls = [call for call in tool_calls if call.get("id") not in tool_message_ids]
        if pending_tool_calls:
            logger.info(
                "[hitl_feedback] detected %d rejection(s) with %d pending tool call(s); skipping feedback injection.",
                len(rejected_messages),
                len(pending_tool_calls),
            )
            return None

        feedback = _format_rejection_feedback(rejected_messages)
        prompt = (
            "A tool request was rejected by the user. Use the feedback below to decide how to respond.\n"
            "- If the feedback indicates they don't want the action, acknowledge and do not retry.\n"
            "- If they want changes, revise your response and retry the tool call.\n"
            "- If details are missing, ask one concise follow-up question.\n"
            "- Do not mention tools, approvals, or internal steps.\n\n"
            f"Feedback:\n{feedback}"
        )
        follow_up = HumanMessage(content=prompt)

        update: dict[str, Any] = {"messages": [assistant_msg, follow_up], "jump_to": "model"}
        logger.info(
            "[hitl_feedback] handled %d rejection(s) with no pending tool calls.",
            len(rejected_messages),
        )
        return update


__all__ = ["HitlFeedbackMiddleware"]
