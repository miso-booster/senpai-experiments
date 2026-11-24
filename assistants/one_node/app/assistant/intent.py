"""Shared intent constants used across the assistant."""

from __future__ import annotations

from typing import Literal, Tuple, cast

_INTENT_VALUES: Tuple[str, ...] = (
    "create_rule",
    "create_profile",
    "fix_rule",
    "fix_profile",
    "explain",
    "other",
)

IntentLiteral = Literal[
    "create_rule",
    "create_profile",
    "fix_rule",
    "fix_profile",
    "explain",
    "other",
]

INTENT_SYSTEM_PROMPT = (
    "You are a routing assistant for SENSEI conversations.\n"
    "Read the latest user messages and identify their CURRENT request.\n"
    "SENSEI is a tool / framework for chatbot testing by using Profiles and Rules."
    "This is done by executing the Profiles using SENSEI and then validating the output against the Rules.\n"
    "Choose one of these intents:\n"
    '- "create_rule": user wants a new SENSEI rule.\n'
    '- "create_profile": user wants a new SENSEI profile.\n'
    '- "fix_rule": user wants to improve or correct an existing rule.\n'
    '- "fix_profile": user wants to improve or correct an existing profile.\n'
    '- "explain": user greets, asks questions related to SENSEI, or wants explanations/docs related to SENSEI.\n'
    '- "other": asks questions unrelated to SENSEI rules or profiles, or wants explanations/docs unrelated to SENSEI rules or profiles anything unrelated to SENSEI rules or profiles.\n'
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
