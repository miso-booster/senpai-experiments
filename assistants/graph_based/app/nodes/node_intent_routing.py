"""Utilities for classifying user requests and extracting chat text."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence, Tuple, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.assistant.intent import ALLOWED_INTENT_SET, INTENT_SYSTEM_PROMPT, IntentLiteral
from app.assistant.state import ChatState
from app.utils.utilities import normalise_message_content

_UNSUPPORTED_INTENT_MESSAGE = (
    "I can only help with SENSEI rules, SENSEI profiles, SENSEI connectors, or related explanations. "
    "Please share one of those requests."
)


def classify_request(
    state: ChatState,
    model: BaseChatModel,
    *,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Classify the user request with the bound LLM."""
    user_messages = _collect_recent_user_messages(state)
    if not user_messages:
        return {
            "intent": "other",
            "messages": [AIMessage(content=_UNSUPPORTED_INTENT_MESSAGE)],
            "retry_action": "none",
            "needs_retry": False,
        }

    intent, raw = _run_intent_classifier(model, user_messages, verbose=verbose)

    if verbose:
        summary: Dict[str, Any] = {"intent": intent}
        if raw:
            summary["raw"] = raw if len(raw) <= 160 else f"{raw[:157]}..."
        print(f"[intent-classifier] {summary}")

    payload: Dict[str, Any] = {"intent": intent}
    if user_messages:
        payload["last_user_message"] = user_messages[0]
    if intent == "other":
        payload["messages"] = [AIMessage(content=_UNSUPPORTED_INTENT_MESSAGE)]
        payload["retry_action"] = "none"
        payload["needs_retry"] = False
    return payload


def _run_intent_classifier(
    model: BaseChatModel,
    messages: Sequence[str],
    *,
    verbose: bool = False,
) -> Tuple[IntentLiteral, str | None]:
    """Send the recent user messages to the LLM for intent classification."""
    prompt = _build_intent_prompt(messages)
    llm_messages: Sequence[BaseMessage] = [
        SystemMessage(content=INTENT_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    try:
        response = model.invoke(llm_messages)
    except Exception:  # pragma: no cover - defensive guard
        return "other", None

    text = normalise_message_content(response)
    intent = _parse_intent_label(text)
    if intent is None:
        if verbose:
            preview = text if len(text) <= 160 else f"{text[:157]}..."
            print(f"[intent-classifier] unparsed response: {preview}")
        return "other", text
    return intent, text


def _build_intent_prompt(messages: Sequence[str]) -> str:
    """Build a string with the user's messages from oldest to newest."""
    chronological = list(reversed(messages))
    formatted = "\n".join(f"{idx}. {text}" for idx, text in enumerate(chronological, start=1))
    return f"USER MESSAGES (oldest to newest):\n{formatted}\nClassify only the last message. I send you all the messages for context, but you have to classify only the last one."


def _parse_intent_label(text: str) -> IntentLiteral | None:
    """Extract the intent label from the LLM response text."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    candidate = cleaned
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start : end + 1]

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    intent_raw = data.get("intent")
    if not isinstance(intent_raw, str):
        return None

    intent_value = intent_raw.strip().lower()
    if intent_value not in ALLOWED_INTENT_SET:
        return None
    return cast(IntentLiteral, intent_value)


def _collect_recent_user_messages(state: ChatState, limit: int = 3) -> List[str]:
    messages = state.get("messages", []) or []
    collected: List[str] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            text = normalise_message_content(message.content)
            if text:
                collected.append(text)
                if len(collected) >= limit:
                    break
    if not collected:
        fallback = state.get("input") or state.get("last_user_message")
        if isinstance(fallback, str) and fallback.strip():
            collected.append(fallback.strip())
    return collected


def extract_user_text(state: ChatState) -> str:
    """Retrieve the latest human message content from the chat state."""
    messages = state.get("messages", []) or []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            text = normalise_message_content(message.content)
            if text:
                return text

    fallback = state.get("input") or state.get("last_user_message")
    if isinstance(fallback, str):
        return fallback
    if fallback is None:
        return ""
    return str(fallback)


__all__ = ["classify_request", "extract_user_text"]
