"""Scope guardrail middleware for the Senpai assistant."""

from __future__ import annotations

import os
import logging
from collections.abc import Sequence
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from app.assistant.middleware_utils import get_state_messages

logger = logging.getLogger(__name__)

def _structured_output_kwargs() -> dict[str, str]:
    """Use tool calling for OpenAI-compatible endpoints without json_schema support (e.g. DeepSeek)."""
    method = os.getenv("SENPAI_STRUCTURED_OUTPUT_METHOD")
    return {"method": method} if method else {}


# Keep classifier context small and predictable in cost.
_MAX_CONTEXT_MESSAGES = 6
_MAX_CONTEXT_CHARS = 500

_DOMAIN_VOCABULARY = (
    "SENSEI domain vocabulary you should recognize as in-scope even when the user does not explicitly say "
    "'SENSEI' or 'Senpai':\n"
    "- Rules / validation terms: oracle, if/then rules, metamorphic rules, when filters, helpers, "
    "chatbot_phrases, utterance_index, only_talks_about, conversation_length.\n"
    "- Profile terms: profile, chatbot.output, extracted outputs, goals, stopping logic, simulator behaviour.\n"
    "- Connector terms: connector, request payload, headers, response_path, API mapping.\n"
    "- Project artifact terms: project files, YAML files, docs, profiles directory, rules directory, connectors.\n"
)


class _ScopeDecision(BaseModel):
    """Structured classification result for request scope checks."""

    in_scope: bool = Field(
        description=(
            "True when the user request is within the Senpai assistant scope (SENSEI rules/profiles/connectors, "
            "their docs/project files, Senpai capabilities/workflow) or is a simple greeting/social message. "
            "False for unrelated topics (standalone generic coding requests, random knowledge, non-SENSEI tasks)."
        )
    )
    reason: str = Field(
        default="",
        description="Short rationale for the decision to help debugging/logging; do not include chain-of-thought.",
    )


def _content_to_text(content: object) -> str:
    """Flatten common message content payloads into text for prompts/logging."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
                    continue
            parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _format_recent_context(messages: Sequence[BaseMessage | Any]) -> str:
    """Build a compact recent conversation context for the scope classifier."""
    rows: list[str] = []
    for msg in list(messages)[-_MAX_CONTEXT_MESSAGES:]:
        role = getattr(msg, "type", None) or msg.__class__.__name__
        content = _content_to_text(getattr(msg, "content", ""))
        if not content:
            continue
        content = content.strip()
        if not content:
            continue
        if len(content) > _MAX_CONTEXT_CHARS:
            content = content[:_MAX_CONTEXT_CHARS].rstrip() + "..."
        rows.append(f"{role}: {content}")
    return "\n".join(rows)


class ScopeGuardrailMiddleware(AgentMiddleware):
    """Model-based scope guardrail executed before the agent."""

    def __init__(self, *, model: BaseChatModel, has_workspace_context: bool = False) -> None:
        """Initialize the scope guardrail with the model used for classification/replies.

        Args:
            model: Chat model used for scope classification and guardrail replies.
            has_workspace_context: True when a SENSEI workspace is available, including
                project files and/or connectors. This does not guarantee a full project
                directory is present.
        """
        super().__init__()
        self._model = model
        self._has_workspace_context = has_workspace_context

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        """Block out-of-scope requests before planning/model/tool execution."""
        _ = runtime
        messages = get_state_messages(state)
        if not messages:
            return None

        last_message = messages[-1]
        if not isinstance(last_message, HumanMessage):
            # Resume paths (e.g. HITL approvals) should not be re-classified.
            return None

        user_text = _content_to_text(last_message.content).strip()
        if not user_text:
            return None

        in_scope, reason = self._classify_request_scope(user_text=user_text, messages=messages)
        if in_scope:
            logger.info("[scope_guardrail] allowed request.")
            return None

        reply = self._build_out_of_scope_reply(user_text=user_text, reason=reason)
        logger.info("[scope_guardrail] blocked out-of-scope request. reason=%s", reason or "(none)")
        return {
            "messages": [AIMessage(content=reply)],
            "jump_to": "end",
        }

    def _classify_request_scope(self, *, user_text: str, messages: Sequence[Any]) -> tuple[bool, str]:
        """Classify whether a request is in scope for Senpai."""
        prompt = self._build_scope_prompt(user_text=user_text, messages=messages)

        try:
            decision_model = self._model.with_structured_output(_ScopeDecision, **_structured_output_kwargs())
            decision = decision_model.invoke(prompt)
            return bool(getattr(decision, "in_scope", True)), str(getattr(decision, "reason", "") or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[scope_guardrail] classifier failed; allowing request. error=%s", exc)
            return True, "classifier_failed_open"

    def _build_scope_prompt(self, *, user_text: str, messages: Sequence[Any]) -> list[BaseMessage]:
        """Build the classifier prompt with active workspace and conversation context."""
        recent_context = _format_recent_context(messages)
        workspace_context = (
            "A SENSEI workspace is currently open. Interpret ambiguous questions about docs, files, "
            "rules, profiles, or connectors as referring to that workspace unless the user clearly indicates "
            "another domain."
            if self._has_workspace_context
            else "No active SENSEI workspace is guaranteed."
        )
        return [
            SystemMessage(
                content=(
                    "You are a lenient scope filter for the Senpai assistant (a SENSEI-focused assistant).\n"
                    "DEFAULT TO ALLOW. Only mark out-of-scope when you are highly confident the request is "
                    "completely unrelated AND not a follow-up to previous in-scope context.\n\n"
                    f"Workspace context:\n- {workspace_context}\n\n"
                    f"{_DOMAIN_VOCABULARY}\n"
                    "Decide whether the latest user request is in scope.\n\n"
                    "ALWAYS ALLOW - Core Topics:\n"
                    "- SENSEI RULES (SENSEI-check DSL), SENSEI PROFILES (SENSEI Chat), SENSEI CONNECTORS.\n"
                    "- Explaining docs, creating/fixing/updating YAML, reasoning about project files for those.\n"
                    "- Explaining or defining SENSEI terminology and DSL vocabulary.\n"
                    "- Senpai assistant workflow/capabilities/limitations when related to SENSEI tasks.\n"
                    "- Guardrails, middleware, validation, tools, docs loading, project file workflows in this assistant.\n"
                    "- Implicit project-local documentation or file questions when a SENSEI workspace is open.\n\n"
                    "ALWAYS ALLOW - Follow-ups & Context:\n"
                    "- ANY follow-up to a previous in-scope conversation.\n"
                    "- Questions about code/YAML the assistant just showed.\n"
                    "- Clarifications, reformats, shorter/longer versions, translations.\n"
                    "- Short/vague questions that could relate to prior context.\n"
                    "- Questions with typos in SENSEI terminology.\n\n"
                    "ALWAYS ALLOW - Social:\n"
                    "- Pure greetings / thanks / small talk with no unrelated request attached.\n\n"
                    "IMPORTANT DISTINCTIONS:\n"
                    "- A greeting PLUS an unrelated request is NOT automatically allowed.\n"
                    "- Standalone generic coding help (e.g., plain Python/React/SQL coding) is OUT OF SCOPE unless the "
                    "user clearly ties it to SENSEI rules/profiles/connectors or this assistant's implementation.\n"
                    "- If the user is inside an active SENSEI workspace and asks a short documentation or file question, "
                    "treat it as workspace-local by default.\n"
                    "- If the user asks what a domain term means and that term appears in the vocabulary above, "
                    "treat it as in-scope unless they clearly mean another domain.\n"
                    "IN SCOPE:\n"
                    "- SENSEI RULES (SENSEI-check DSL), SENSEI PROFILES (SENSEI Chat), SENSEI CONNECTORS.\n"
                    "- Explaining docs, creating/fixing/updating YAML, reasoning about project files for those.\n"
                    "- Defining or clarifying SENSEI terminology and validation vocabulary.\n"
                    "- Questions about Senpai assistant capabilities/workflow/guardrails in the context of this SENSEI assistant.\n"
                    "- Ambiguous questions about docs/files/artifacts in the active SENSEI workspace.\n"
                    "- Pure greetings / simple social messages.\n"
                    "- Follow-ups that depend on prior in-scope context (be permissive when ambiguous).\n\n"
                    "OUT OF SCOPE:\n"
                    "- Unrelated frameworks/topics, random knowledge questions, or non-SENSEI tasks.\n\n"
                    "ONLY mark out-of-scope when ALL are true:\n"
                    "1) The query is completely unrelated to SENSEI or this assistant's implementation/context.\n"
                    "2) It is NOT a follow-up to prior in-scope messages.\n"
                    "3) It is NOT a vague clarification that could refer to prior context.\n\n"
                    "Critical rules:\n"
                    "- When uncertain, choose in_scope=true.\n"
                    "- False positives (blocking valid requests) are worse than false negatives.\n"
                    "- Set in_scope=false only if you are >95% confident it is unrelated.\n\n"
                    "Return structured output with fields: in_scope (bool), reason (short string)."
                )
            ),
            HumanMessage(
                content=(
                    f"Recent conversation context:\n{recent_context or '(none)'}\n\nLatest user request:\n{user_text}"
                )
            ),
        ]

    def _build_out_of_scope_reply(self, *, user_text: str, reason: str) -> str:
        """Generate a short, user-facing out-of-scope reply in the user's language."""
        prompt = [
            SystemMessage(
                content=(
                    "You are writing a guardrail response for Senpai, an assistant focused on SENSEI tools.\n"
                    "Write a short reply in the SAME language as the user's message.\n"
                    "Language lock:\n"
                    "- If the user's message is in English, reply in English.\n"
                    "- Do NOT reply in Japanese unless the user wrote in Japanese.\n"
                    "- Do NOT switch languages.\n"
                    "Requirements:\n"
                    "- 1 to 4 short sentences.\n"
                    "- Politely explain that you can help with SENSEI RULES, SENSEI PROFILES, and SENSEI CONNECTORS "
                    "(docs, YAML creation/fixes, and related project files).\n"
                    "- Do not mention guardrails, middleware, classification, policies, or internal implementation.\n"
                    "- Do not answer the out-of-scope request itself."
                )
            ),
            HumanMessage(
                content=(
                    f"User message:\n{user_text}\n\n"
                    f"Classifier reason (for context only, do not mention directly): {reason or '(none)'}"
                )
            ),
        ]

        try:
            response = self._model.invoke(prompt)
            text = _content_to_text(getattr(response, "content", "")).strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("[scope_guardrail] reply generation failed; using fallback. error=%s", exc)

        return "I can help with SENSEI rules, profiles, and connectors (docs, YAML, and related project files)."


__all__ = ["ScopeGuardrailMiddleware"]
