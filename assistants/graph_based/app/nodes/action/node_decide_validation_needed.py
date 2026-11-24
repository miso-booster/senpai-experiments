"""LLM-powered decision helper that determines if YAML validation must run."""

import json
import logging
import re
from typing import Any, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.assistant.intent import IntentLiteral
from app.assistant.state import ChatState
from app.nodes.node_intent_routing import extract_user_text
from app.utils.utilities import normalise_message_content

log = logging.getLogger(__name__)


VALIDATION_DECISION_SYSTEM_PROMPT = (
    "You are a careful classifier deciding if the assistant must run the YAML validator "
    "before replying to the user. Reply STRICTLY with a JSON object on a single line using this schema:\n"
    '{"decision": "TRUE" | "FALSE", "reason": "short explanation"}.\n'
    'Choose "FALSE" only when the user explicitly asks for a broken/incorrect rule/profile/connector, requests no validation, '
    "wants to explore invalid outputs, or asks explicitly for a missing field.\n"
    'In every other case respond with "TRUE" so the validator runs.\n'
    'If you are unsure, choose "TRUE".\n'
    "Do not mention or infer user intent; that classification is handled elsewhere.\n"
    "Do not add markdown fences or extra text."
)


# Set of intents that require validation
_INTENTS_NEED_VALIDATION: tuple[IntentLiteral, ...] = (
    "create_rule",
    "create_profile",
    "create_connector",
    "fix_rule",
    "fix_profile",
    "fix_connector",
)


def _build_validation_decision_prompt(user_text: str) -> str:
    """Compose the human message passed to the LLM validation helper."""
    request = user_text.strip()
    return (
        "DECISION TASK: Decide whether the assistant must run the SENSEI Profiles, Rules, and Connectors validator "
        "before providing its next reply.\n"
        "Return a JSON object exactly like the following example (no code fences):\n"
        '{"decision": "TRUE", "reason": "user expects a correct rule"}\n'
        'Return "FALSE" only if the user explicitly wants an incorrect/broken rule/profile/connector, asks to skip validation, '
        'or wants unchecked output. Return "TRUE" otherwise.\n'
        "USER MESSAGE:\n"
        "<<<\n"
        f"{request}\n"
        ">>>"
    )


def _parse_validation_decision(text: str) -> tuple[bool | None, str | None]:
    """Parse the structured output from the LLM validation helper."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None, None

    candidate = cleaned
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            candidate = match.group(0)

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        raw_decision = data.get("decision") or data.get("apply_validation") or data.get("validate")
        reason = data.get("reason") or data.get("explanation")
        if isinstance(raw_decision, bool):
            return bool(raw_decision), reason if isinstance(reason, str) else None
        if isinstance(raw_decision, str):
            decision_upper = raw_decision.strip().upper()
            if decision_upper == "TRUE":
                return True, reason if isinstance(reason, str) else None
            if decision_upper == "FALSE":
                return False, reason if isinstance(reason, str) else None

    return None, None


def decide_validation_needed(
    state: ChatState,
    model: BaseChatModel,
    *,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Determine via LLM whether validators should run for the current request."""
    current_intent = state.get("intent")
    intent_value = current_intent if isinstance(current_intent, str) and current_intent else "other"

    if current_intent not in _INTENTS_NEED_VALIDATION:
        reason_code = "intent_does_not_require_validation"
        return {
            "should_validate": False,
            "validation_decision_reason": reason_code,
            "intent": intent_value,
            "validation_results": [],
            "validation_attempts": 0,
            "needs_retry": False,
            "retry_action": "none",
            "invalid_snippets": [],
            "validation_feedback": None,
            "code_blocks": [],
        }

    user_text = extract_user_text(state)
    if not user_text.strip():
        return {
            "should_validate": True,
            "validation_decision_reason": "empty_user_message",
            "intent": intent_value,
        }

    messages = [
        SystemMessage(content=VALIDATION_DECISION_SYSTEM_PROMPT),
        HumanMessage(content=_build_validation_decision_prompt(user_text)),
    ]

    try:
        response = model.invoke(messages)
    except Exception:
        log.exception("Failed to obtain validation decision from LLM; defaulting to TRUE.")
        return {
            "should_validate": True,
            "validation_decision_reason": "llm_call_failed",
            "intent": intent_value,
        }

    decision_text = normalise_message_content(response)
    decision, reason = _parse_validation_decision(decision_text)

    if verbose:
        decision_label = "TRUE" if decision is True else "FALSE" if decision is False else "UNKNOWN"
        summary: Dict[str, Any] = {"decision": decision_label}
        if reason:
            summary["reason"] = reason
        print(f"[validation-decision] {summary}")
        if decision is None:
            raw_text = decision_text.strip()
            preview = raw_text if len(raw_text) <= 160 else f"{raw_text[:157]}..."
            print(f"[validation-decision] raw={preview}")

    if decision is False:
        payload: Dict[str, Any] = {
            "should_validate": False,
            "validation_results": [],
            "validation_attempts": 0,
            "needs_retry": False,
            "retry_action": "none",
            "invalid_snippets": [],
            "validation_feedback": None,
            "code_blocks": [],
            "intent": intent_value,
        }
        if reason:
            payload["validation_decision_reason"] = reason
        return payload

    if decision is True:
        result: Dict[str, Any] = {"should_validate": True, "intent": intent_value}
        if reason:
            result["validation_decision_reason"] = reason
        return result

    log.warning("Could not parse validation decision output '%s'; defaulting to TRUE.", decision_text)
    return {
        "should_validate": True,
        "validation_decision_reason": "unparsed_response",
        "intent": intent_value,
    }
