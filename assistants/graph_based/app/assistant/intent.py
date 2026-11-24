"""Shared intent constants used across the assistant."""

from __future__ import annotations

from typing import Literal, Tuple, cast

_INTENT_VALUES: Tuple[str, ...] = (
    "create_rule",
    "create_profile",
    "create_connector",
    "fix_rule",
    "fix_profile",
    "fix_connector",
    "explain",
    "other",
)

IntentLiteral = Literal[
    "create_rule",
    "create_profile",
    "create_connector",
    "fix_rule",
    "fix_profile",
    "fix_connector",
    "explain",
    "other",
]

INTENT_SYSTEM_PROMPT = (
    "You are a routing assistant for SENSEI conversations.\n"
    "Read the latest user messages and identify their CURRENT request.\n"
    "SENSEI is a tool / framework for chatbot testing by using Profiles, Rules, and Connectors. "
    "This is done by executing Profiles through Connectors using SENSEI and validating the output against Rules.\n"
    "Choose one of these intents:\n"
    '- "create_rule": user wants a new SENSEI rule.\n'
    '- "create_profile": user wants a new SENSEI profile.\n'
    '- "create_connector": user wants a new SENSEI connector.\n'
    '- "fix_rule": user wants to improve or correct an existing rule.\n'
    '- "fix_profile": user wants to improve or correct an existing profile.\n'
    '- "fix_connector": user wants to improve or correct an existing connector.\n'
    '- "explain": user greets, asks questions related to SENSEI, wants explanations/docs related to SENSEI, or wants to'
    "list, find or read existing profiles, rules or connectors in the project or user path.\n"
    '- "other": asks questions unrelated to SENSEI rules, profiles, or connectors, or wants unrelated explanations/docs.\n'
    'Respond with JSON like {"intent": "create_rule", "reason": "short note"} on a single line. '
    "No markdown, no extra text."
)

ALLOWED_INTENTS: Tuple[IntentLiteral, ...] = cast(Tuple[IntentLiteral, ...], _INTENT_VALUES)
ALLOWED_INTENT_SET = set(_INTENT_VALUES)

__all__ = [
    "IntentLiteral",
    "INTENT_SYSTEM_PROMPT",
    "ALLOWED_INTENTS",
    "ALLOWED_INTENT_SET",
]
