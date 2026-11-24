"""Middleware to validate YAML code blocks and tool calls emitted by the agent."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolCall, ToolMessage
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field
from senpai_validators import ValidationResult
from senpai_validators import validate_connector as validate_connector_content
from senpai_validators import validate_profile as validate_profile_content
from senpai_validators import validate_rule as validate_rule_content

from app.assistant.codeblock_classifier import YamlBlockPayload, extract_yaml_blocks
from app.assistant.docs_metadata import DOC_METADATA, DOC_TYPE_BY_BLOCK_TYPE, SENSEI_DOC_TYPES
from app.assistant.middleware_utils import (
    get_latest_ai_message,
    get_latest_human_text,
    get_state_messages,
)
from app.assistant.validation import MAX_VALIDATION_ATTEMPTS, validate_code_blocks

logger = logging.getLogger(__name__)

def _structured_output_kwargs() -> dict[str, str]:
    """Use tool calling for OpenAI-compatible endpoints without json_schema support (e.g. DeepSeek)."""
    method = os.getenv("SENPAI_STRUCTURED_OUTPUT_METHOD")
    return {"method": method} if method else {}


_VALIDATION_ATTEMPTS_STATE_KEY = "_validator_attempts"
_VALIDATION_DECISION_STATE_KEY = "_validator_requires_validation"
_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
_SAVE_TOOL_NAMES = frozenset({"save_profile", "save_rule", "save_connector"})


@dataclass(frozen=True, slots=True)
class _ToolValidationSpec:
    label: str
    validator: Callable[[str], ValidationResult]
    doc_type: str


def _get_state_attempts(state: AgentState[Any]) -> int:
    """Read the current validation attempt counter from state.

    Args:
        state: Current agent state.

    Returns:
        Attempt count stored in state, or 0 when missing or invalid.
    """
    state_get = getattr(state, "get", None)
    if not callable(state_get):
        return 0
    try:
        value = state_get(_VALIDATION_ATTEMPTS_STATE_KEY, 0)
        return int(cast(Any, value)) if value is not None else 0
    except Exception:  # noqa: BLE001
        return 0


def _get_cached_requires_validation(
    assistant_message: AIMessage | None,
) -> tuple[bool | None, str | None]:
    """Return cached validation decision and its source, if available."""
    if assistant_message is not None:
        metadata = getattr(assistant_message, "additional_kwargs", None)
        if isinstance(metadata, dict) and _VALIDATION_DECISION_STATE_KEY in metadata:
            return bool(metadata[_VALIDATION_DECISION_STATE_KEY]), "message"
    return None, None


class ValidationDecisionMiddleware(AgentMiddleware):
    """Decide whether validation should run for the current reply."""

    def __init__(self, *, model: BaseChatModel) -> None:
        """Initialize the validation decision middleware."""
        super().__init__()
        self._model: BaseChatModel = model

    @hook_config(can_jump_to=["end", "model"])
    def after_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        """Classify whether validation is required for this turn."""
        _ = runtime
        messages = get_state_messages(state)
        if not messages:
            return None

        assistant_msg = get_latest_ai_message(messages)
        if assistant_msg is None:
            return None

        assistant_text = assistant_msg.content if isinstance(assistant_msg.content, str) else ""
        tool_calls = list(getattr(assistant_msg, "tool_calls", None) or [])
        has_save_call = any(call.get("name") in _SAVE_TOOL_NAMES for call in tool_calls)
        has_yaml = bool(assistant_text) and bool(extract_yaml_blocks(assistant_text))

        if not has_save_call and not has_yaml:
            metadata = getattr(assistant_msg, "additional_kwargs", None)
            if not isinstance(metadata, dict):
                assistant_msg.additional_kwargs = {}
                metadata = assistant_msg.additional_kwargs
            metadata[_VALIDATION_DECISION_STATE_KEY] = False
            logger.info("[validation_decision] skipped (no YAML blocks or save_* tool calls).")
            return None

        user_text = get_latest_human_text(messages)
        requires_validation = _classify_requires_validation_with_model(self._model, user_text, assistant_text)
        metadata = getattr(assistant_msg, "additional_kwargs", None)
        if not isinstance(metadata, dict):
            assistant_msg.additional_kwargs = {}
            metadata = assistant_msg.additional_kwargs
        metadata[_VALIDATION_DECISION_STATE_KEY] = requires_validation
        logger.info("[validation_decision] decided requires_validation=%s", requires_validation)
        return None


def _classify_requires_validation_with_model(
    model: BaseChatModel,
    user_message: str,
    assistant_reply: str,
) -> bool:
    """Ask the model whether validation should run for this reply."""

    class ValidationDecision(BaseModel):
        requires_validation: bool = Field(
            description=(
                "True when the user asked to create, fix, generate or validate a Sensei rule/profile. "
                "False when the user requested an explanation or example, asked for a fragment/partial snippet "
                "(e.g., only the user section, just one field, isolated block), "
                "or explicitly asked for incomplete/invalid YAML (e.g., omit user section, missing fields, keep invalid, "
                "leave placeholders)."
            )
        )

    prompt = [
        SystemMessage(
            content=(
                "Decide if the assistant reply should be passed through a YAML validator. "
                "Return JSON with a single boolean field requires_validation. "
                "Validate only when the user asked to create/fix/generate/validate a Sensei rule, profile, or connector. "
                "If the user asked for a fragment/partial snippet (only one section or field, isolated block), "
                "ALWAYS set requires_validation to false even if the YAML resembles a valid profile/rule/connector. "
                "If the user asked for intentionally incomplete or invalid YAML (e.g., omit a required section like user, "
                "missing fields, keep it wrong, leave placeholders/variables to be filled later), set requires_validation to false."
                "\n\nExamples:\n"
                'User: "create only the user section of a profile" -> {"requires_validation": false}\n'
                'User: "give me just one field from a rule" -> {"requires_validation": false}\n'
                'User: "make a full profile for a cafe" -> {"requires_validation": true}\n'
                'User: "fix this connector yaml" -> {"requires_validation": true}\n'
            )
        ),
        HumanMessage(
            content=(
                f"User request:\n{user_message}\n\nAssistant reply:\n{assistant_reply}\n\n"
                "Set requires_validation to true only if the user intent is create/fix/generate/validate AND they did not ask for a fragment/partial or incomplete/invalid YAML."
            )
        ),
    ]

    try:
        decision_model = model.with_structured_output(ValidationDecision, **_structured_output_kwargs())
        decision = decision_model.invoke(prompt)
        return bool(getattr(decision, "requires_validation", False))
    except Exception:  # noqa: BLE001
        return False


class ToolCallValidationMiddleware(AgentMiddleware):
    """Validate tool calls before human review or tool execution."""

    def __init__(self, *, model: BaseChatModel) -> None:
        """Initialize the tool call validator middleware."""
        super().__init__()
        self._model: BaseChatModel = model
        self._tool_validators: dict[str, _ToolValidationSpec] = {
            "save_profile": _ToolValidationSpec(
                label="Profile",
                validator=validate_profile_content,
                doc_type="profiles",
            ),
            "save_rule": _ToolValidationSpec(
                label="Rule",
                validator=validate_rule_content,
                doc_type="rules",
            ),
            "save_connector": _ToolValidationSpec(
                label="Connector",
                validator=validate_connector_content,
                doc_type="connectors",
            ),
        }

    @hook_config(can_jump_to=["end", "model"])
    def after_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        """Validate tool calls on the latest AI message.

        Args:
            state: Current agent state.
            runtime: Agent runtime (unused).

        Returns:
            State update dict when tool calls are filtered or retried, otherwise None.
        """
        _ = runtime
        messages = get_state_messages(state)
        if not messages:
            return None

        assistant_msg = get_latest_ai_message(messages)
        if assistant_msg is None:
            return None

        tool_calls = list(getattr(assistant_msg, "tool_calls", None) or [])
        if not tool_calls:
            logger.info("[tool_validation] skipped (no tool calls found).")
            return None

        attempts_so_far = _get_state_attempts(state)
        has_save_call = any(tool_call.get("name") in self._tool_validators for tool_call in tool_calls)
        if has_save_call:
            user_text = get_latest_human_text(messages)
            assistant_text = assistant_msg.content if isinstance(assistant_msg.content, str) else ""
            requires_validation, cache_source = _get_cached_requires_validation(assistant_msg)
            if requires_validation is None:
                logger.info("[tool_validation] classifier cache miss; invoking decision model.")
                requires_validation = self._classify_requires_validation(user_text, assistant_text)
            else:
                logger.info("[tool_validation] classifier cache hit (%s): %s", cache_source, requires_validation)
            if not requires_validation:
                logger.info("[tool_validation] skipped (classifier decided not to validate).")
                return None
        tool_call_update = self._filter_invalid_tool_calls(assistant_msg)
        if tool_call_update is None:
            if has_save_call:
                logger.info("[tool_validation] passed (all save_* tool calls valid).")
            else:
                logger.info("[tool_validation] skipped (no save_* tool calls found).")
            return None

        if attempts_so_far:
            tool_call_update[_VALIDATION_ATTEMPTS_STATE_KEY] = 0
        return tool_call_update

    def _classify_requires_validation(self, user_message: str, assistant_reply: str) -> bool:
        """Ask the model whether validation should run for this reply."""
        return _classify_requires_validation_with_model(self._model, user_message, assistant_reply)

    def _filter_invalid_tool_calls(self, assistant_message: AIMessage) -> dict[str, Any] | None:
        """Filter invalid save_* tool calls before HITL and tool execution.

        Args:
            assistant_message: Latest AIMessage containing tool_calls to validate.
                This message is mutated in place so downstream middleware and tool
                routing see the filtered tool_calls immediately.

        Returns:
            A state update dict when invalid tool calls are removed (including a retry
            jump back to the model), or None when no changes are needed.
        """
        tool_calls = cast(list[ToolCall], list(getattr(assistant_message, "tool_calls", []) or []))
        if not tool_calls:
            return None

        valid_calls: list[ToolCall] = []
        error_texts: list[str] = []
        invalid_doc_types: set[str] = set()
        invalid_tool_names: set[str] = set()

        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            spec = self._tool_validators.get(tool_name)
            if spec is None:
                valid_calls.append(tool_call)
                continue

            validation_error = self._validate_tool_call(tool_call, spec)
            if validation_error is None:
                valid_calls.append(tool_call)
                continue

            content = validation_error.content if isinstance(validation_error.content, str) else ""
            error_text = content.strip() or f"{spec.label} validation failed."
            error_texts.append(error_text)
            invalid_doc_types.add(spec.doc_type)
            if tool_name:
                invalid_tool_names.add(tool_name)

        if not error_texts:
            return None

        assistant_message.tool_calls = valid_calls
        retry_text = self._build_tool_retry_instruction(
            "\n\n".join(error_texts),
            assistant_message.content,
            sorted(invalid_doc_types),
        )
        reasons = "; ".join(error_texts)
        tool_list = ", ".join(sorted(invalid_tool_names)) if invalid_tool_names else "save_*"
        logger.warning(
            "[tool_validation] blocked invalid %s tool call(s); requesting retry. Reasons: %s",
            tool_list,
            reasons,
        )
        return {
            "messages": [assistant_message, HumanMessage(content=retry_text)],
            "jump_to": "model",
        }

    def _build_tool_retry_instruction(
        self,
        feedback: str,
        previous_assistant_message: object,
        doc_types: list[str],
    ) -> str:
        """Build a retry instruction for invalid save tool calls.

        Args:
            feedback: Validation feedback to include.
            previous_assistant_message: Assistant message content for context.
            doc_types: Doc types to include in the get_docs hint.

        Returns:
            Retry instruction for the model.
        """
        previous_text = previous_assistant_message if isinstance(previous_assistant_message, str) else ""
        doc_hint = ""
        if doc_types:
            doc_list = ", ".join(f"'{doc_type}'" for doc_type in doc_types)
            doc_hint = f"If you have not already, call get_docs with doc_types=[{doc_list}] before retrying.\n\n"

        return (
            "The previous save tool call(s) could not be used because the content failed required checks:\n"
            f"{feedback}\n\n"
            "Rewrite your response as a normal continuation of the conversation. "
            "If you can provide valid content, do so (and only call the save tool if the content is valid). "
            "If details are missing, ask a concise follow-up question instead. "
            "Do not mention validation, tools, or internal steps.\n"
            f"{doc_hint}"
            "Previous assistant message (for context only, do not quote it):\n"
            f"{previous_text}"
        )

    def _validate_tool_call(
        self,
        tool_call: ToolCall | dict[str, Any],
        spec: _ToolValidationSpec,
    ) -> ToolMessage | None:
        """Validate a save_* tool call payload before execution.

        Args:
            tool_call: Tool call payload to validate.
            spec: Validator configuration for the tool call.

        Returns:
            ToolMessage describing the validation error, or None if valid.
        """
        args = tool_call.get("args")
        if not isinstance(args, dict):
            return self._build_tool_error(
                tool_call,
                message=f"{spec.label} validation failed: tool args are missing or invalid.",
            )

        content = args.get("content")
        if not isinstance(content, str) or not content.strip():
            return self._build_tool_error(
                tool_call,
                message=f"{spec.label} validation failed: content is missing or empty.",
            )

        validation = spec.validator(content)
        if validation.is_valid:
            return None

        return self._build_tool_error(
            tool_call,
            message=f"{spec.label} validation failed.",
            validation=validation,
        )

    def _build_tool_error(
        self,
        tool_call: ToolCall | dict[str, Any],
        *,
        message: str,
        validation: ValidationResult | None = None,
    ) -> ToolMessage:
        """Create a ToolMessage error for invalid save tool calls.

        Args:
            tool_call: Tool call payload for metadata.
            message: Summary error message.
            validation: Optional validation details to append.

        Returns:
            ToolMessage describing the validation errors and warnings.
        """
        lines = [message]
        if validation is not None:
            if validation.errors:
                lines.append("Errors:")
                lines.extend(f"- {error}" for error in validation.errors)
            if validation.warnings:
                lines.append("Warnings:")
                lines.extend(f"- {warning}" for warning in validation.warnings)
        tool_call_id = tool_call.get("id") or "unknown"
        tool_name = tool_call.get("name")
        return ToolMessage(
            content="\n".join(lines),
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )


class MessageValidationMiddleware(AgentMiddleware):
    """Run message validation (YAML blocks) after model replies."""

    def __init__(self, *, model: BaseChatModel) -> None:
        """Initialize the message validation middleware.

        Args:
            model: Language model used to classify and repair YAML snippets.
        """
        super().__init__()
        self._model: BaseChatModel = model
        self._validate_code_blocks = validate_code_blocks

    @hook_config(can_jump_to=["end", "model"])
    def after_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        """Validate the latest AI message when it contains YAML.

        Args:
            state: Current agent state.
            runtime: Agent runtime (unused).

        Returns:
            State update dict when validation modifies output, otherwise None.
        """
        _ = runtime
        messages = get_state_messages(state)
        attempts_so_far = _get_state_attempts(state)
        if not messages:
            return None

        assistant_msg = get_latest_ai_message(messages)
        if assistant_msg is None:
            return None
        if not isinstance(assistant_msg.content, str):
            return None

        user_text = get_latest_human_text(messages)
        state_update = self._apply_validation_if_needed(state, messages, user_text, assistant_msg, attempts_so_far)
        if state_update is not None:
            return state_update

        return None

    def _apply_validation_if_needed(
        self,
        state: AgentState[Any],
        messages: list[Any],
        user_message: str,
        assistant_message: AIMessage,
        attempts_so_far: int,
    ) -> dict[str, Any] | None:
        """Run YAML validation when the response includes YAML code blocks.

        Args:
            state: Current agent state.
            messages: Conversation history.
            user_message: Latest user message text.
            assistant_message: Latest assistant message.
            attempts_so_far: Current validation attempt count.

        Returns:
            State update dict if validation updated state, otherwise None.
        """
        assistant_reply = cast(str, assistant_message.content)
        yaml_blocks: list[YamlBlockPayload] = extract_yaml_blocks(assistant_reply)
        if not yaml_blocks:
            logger.info("[message_validation] skipped (no YAML code blocks found).")
            if attempts_so_far:
                return {_VALIDATION_ATTEMPTS_STATE_KEY: 0}
            return None

        requires_validation, cache_source = _get_cached_requires_validation(assistant_message)
        if requires_validation is None:
            logger.info("[message_validation] classifier cache miss; invoking decision model.")
            requires_validation = self._classify_requires_validation(user_message, assistant_reply)
        else:
            logger.info("[message_validation] classifier cache hit (%s): %s", cache_source, requires_validation)
        if not requires_validation:
            logger.info("[message_validation] skipped (classifier decided not to validate).")
            if attempts_so_far:
                return {_VALIDATION_ATTEMPTS_STATE_KEY: 0}
            return None

        return self._run_validation_loop(
            assistant_message=assistant_message,
            attempts_so_far=attempts_so_far,
            messages=messages,
            user_message=user_message,
            initial_blocks=yaml_blocks,
        )

    def _classify_requires_validation(self, user_message: str, assistant_reply: str) -> bool:
        """Ask the model whether the YAML snippet should be validated."""
        return _classify_requires_validation_with_model(self._model, user_message, assistant_reply)

    def _build_failure_message(self, user_message: str, assistant_reply: str, feedback: str) -> str:
        """Generate a fallback user-facing message when validation keeps failing.

        Args:
            user_message: Latest user message text.
            assistant_reply: Latest assistant reply.
            feedback: Validator feedback for context.

        Returns:
            A short user-facing message.
        """
        prompt = [
            SystemMessage(
                content=(
                    "You are helping a user create a YAML-based profile, rule, or connector in a system called SENSEI.\n"
                    "The system tried multiple times but could not produce a version that passes all checks.\n\n"
                    "Write a very short, friendly, and clear message for the user.\n"
                    "Requirements:\n"
                    "- 1 to 3 short sentences, max 60 words total.\n"
                    "- Use simple, conversational language.\n"
                    "- Briefly apologize and say you tried several times but couldn't finish a version that meets all requirements.\n"
                    "- Mention the most concrete remaining issue in plain language when possible.\n"
                    "- Only ask for missing details, constraints, or examples if the feedback suggests required information is missing.\n"
                    "- Do NOT mention validators, models, SENSEI, or internal tools by name.\n"
                    "- Do NOT include YAML, code blocks, stack traces, or technical error messages.\n"
                    "- Do NOT quote or restate the full user request, assistant reply, or feedback."
                )
            ),
            HumanMessage(
                content=(
                    "Context for you only (do not repeat this text to the user):\n\n"
                    f"User request:\n{user_message}\n\n"
                    f"Last assistant reply:\n{assistant_reply}\n\n"
                    f"Validator feedback:\n{feedback}\n\n"
                    "Now write the final message the user will see, following the requirements above."
                )
            ),
        ]

        try:
            response = self._model.invoke(prompt)
            text = getattr(response, "content", None)
            if isinstance(text, str) and text.strip():
                return text.strip()
        except Exception:  # noqa: BLE001
            pass

        return (
            "Sorry, I tried a few times but couldn't build something I'm confident will work correctly. "
            "I can only share it once it meets all requirements, so could you be more specific about the structure or fields you need?"
        )

    def _build_retry_instruction(
        self,
        feedback: str,
        block_type: str | None,
        block_count: int,
        *,
        user_message: str,
        previous_assistant_message: str,
    ) -> str:
        """Build an instruction asking the model to fix YAML while preserving conversational flow.

        Args:
            feedback: Validation feedback to include.
            block_type: Block type label when known.
            block_count: Number of YAML blocks detected.
            user_message: Latest user message text.
            previous_assistant_message: Assistant reply to rewrite.

        Returns:
            Retry instruction for the model.
        """
        snippet = block_type or "YAML"
        return (
            f"The previous {snippet} content has issues (YAML blocks: {block_count}):\n{feedback}\n\n"
            "Rewrite your entire previous assistant message so it reads like a normal continuation of the conversation "
            "(not a meta announcement).\n"
            "Requirements:\n"
            "- Avoid repeating the user's previous message verbatim; start fresh with wording that directly responds to their request.\n"
            "- Keep the same tone/structure as much as possible; only change what is necessary.\n"
            "- Preserve YAML lines that are already valid; focus your edits on the lines implicated by the feedback.\n"
            "- Use any reference documentation already provided earlier in this conversation (if present).\n"
            "- Do not mention validation, retries, tools, internal steps, or that anything failed.\n"
            "- Only mention a correction/fix/update if (and only if) the user explicitly asked you to fix/correct/update something.\n"
            "- If the user did not ask for a fix, do not use phrases like 'here is the corrected ...' or words like 'corrected', 'fixed', 'updated', 'revised'.\n"
            "- Keep every YAML code fence (all blocks, if multiple).\n"
            "- Ensure explanations align with the YAML you output."
            "\n\nUser request (for context):\n"
            f"{user_message}\n\n"
            "Previous assistant message to rewrite (do not quote it; rewrite it):\n"
            f"{previous_assistant_message}"
        )

    def _doc_types_for_blocks(self, yaml_blocks: list[YamlBlockPayload]) -> list[str]:
        """Union doc_types needed for a set of YAML blocks.

        Args:
            yaml_blocks: YAML block payloads to inspect.

        Returns:
            Sorted list of doc types to include.
        """
        requested: set[str] = set()
        saw_unknown = False
        for block in yaml_blocks:
            normalized = (block.get("block_type") or "").strip().lower()
            doc_type = DOC_TYPE_BY_BLOCK_TYPE.get(normalized)
            if doc_type:
                requested.add(doc_type)
            else:
                saw_unknown = True
        if saw_unknown:
            return sorted(SENSEI_DOC_TYPES)
        if not requested:
            return sorted(SENSEI_DOC_TYPES)
        return sorted(requested)

    def _build_reference_docs_message(self, yaml_blocks: list[YamlBlockPayload]) -> SystemMessage | None:
        """Attach reference docs to the repair context when available.

        Args:
            yaml_blocks: YAML block payloads to inspect.

        Returns:
            SystemMessage containing reference docs, or None if unavailable.
        """
        doc_types = set(self._doc_types_for_blocks(yaml_blocks))
        if not doc_types:
            return None

        sections: list[str] = []
        for filename, doc_type in DOC_METADATA:
            if doc_type not in doc_types:
                continue
            path = _DOCS_DIR / filename
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError as exc:  # noqa: BLE001
                logger.warning("[message_validation] failed to read docs %s: %s", filename, exc)
                continue
            if not content:
                continue
            sections.append(f"## {filename}\n{content}")

        if not sections:
            return None

        return SystemMessage(
            content=(
                "Reference documentation (use this for schema/fields/examples; do not mention this message to the user):\n\n"
                + "\n\n".join(sections)
            )
        )

    def _invoke_repair(self, working_messages: list[Any]) -> AIMessage:
        """Invoke the model for repair attempts.

        Args:
            working_messages: Messages to send to the model.

        Returns:
            AIMessage containing the model response.
        """
        raw = self._model.invoke(working_messages)
        return raw if isinstance(raw, AIMessage) else AIMessage(content=getattr(raw, "content", "") or "")

    def _run_validation_loop(
        self,
        *,
        assistant_message: AIMessage,
        attempts_so_far: int,
        messages: list[Any],
        user_message: str,
        initial_blocks: list[YamlBlockPayload],
    ) -> dict[str, Any] | None:
        """Validate YAML and ask the agent to retry within this turn on failure.

        Args:
            assistant_message: Latest assistant message to update.
            attempts_so_far: Current validation attempt count.
            messages: Conversation history.
            user_message: Latest user message text.
            initial_blocks: Initial YAML blocks extracted from the reply.

        Returns:
            State update dict if validation updated state, otherwise None.
        """
        base_messages = list(messages)
        working_messages = list(messages)
        current_blocks: list[YamlBlockPayload] = initial_blocks
        attempts_completed = attempts_so_far
        had_retries = False
        current_ai = assistant_message
        docs_injected = False

        while True:
            results = self._validate_code_blocks(cast(list[dict[str, Any]], current_blocks), attempts_completed)
            invalid = results.get("invalid_snippets") or []
            feedback = results.get("validation_feedback") or ("Validation failed." if invalid else "Validation passed.")

            if not invalid:
                count = len(current_blocks)
                logger.info(f"[message_validation] passed ({count} block{'s' if count != 1 else ''}).")
                content = getattr(current_ai, "content", "")
                sanitized = ""
                if isinstance(content, str):
                    sanitized = content.strip() if had_retries else content
                if sanitized != assistant_message.content or attempts_so_far:
                    assistant_message.content = sanitized
                    return {"messages": base_messages, _VALIDATION_ATTEMPTS_STATE_KEY: 0}
                return None

            attempts_completed += 1
            history_entry = {
                "attempt": attempts_completed,
                "input": self._format_yaml_blocks_for_display(current_blocks),
                "feedback": feedback,
                "fixed": None,
            }
            logger.warning(self._render_validation_report(history=[history_entry], success=False))

            if attempts_completed >= MAX_VALIDATION_ATTEMPTS:
                failure = self._build_failure_message(user_message, cast(str, current_ai.content), feedback)
                assistant_message.content = failure
                return {"messages": base_messages, _VALIDATION_ATTEMPTS_STATE_KEY: 0}

            if not docs_injected:
                docs_message = self._build_reference_docs_message(current_blocks)
                if docs_message is not None:
                    working_messages.append(docs_message)
                docs_injected = True
            primary_block_type = current_blocks[0].get("block_type") if current_blocks else None
            retry_text = self._build_retry_instruction(
                feedback,
                primary_block_type,
                len(current_blocks),
                user_message=user_message,
                previous_assistant_message=cast(str, current_ai.content),
            )
            working_messages.append(HumanMessage(content=retry_text))
            had_retries = True

            try:
                current_ai = self._invoke_repair(working_messages)
            except Exception:  # noqa: BLE001
                # If the repair call fails, stop retrying without exposing retry prompts to the user.
                latest_content = getattr(current_ai, "content", assistant_message.content)
                if isinstance(latest_content, str):
                    assistant_message.content = latest_content
                return {"messages": base_messages, _VALIDATION_ATTEMPTS_STATE_KEY: 0}

            latest_content = cast(str, current_ai.content)
            new_blocks = extract_yaml_blocks(latest_content)
            if not new_blocks:
                logger.info(
                    "[message_validation] repair produced no YAML code blocks; "
                    "stopping validation and keeping rewritten response."
                )
                assistant_message.content = latest_content.strip()
                return {"messages": base_messages, _VALIDATION_ATTEMPTS_STATE_KEY: 0}

            current_blocks = new_blocks

    def _render_validation_report(
        self,
        history: list[dict[str, Any]],
        success: bool,
        initial_reply: str | None = None,
    ) -> str:
        """Build a readable transcript of validator inputs, feedback, and final status.

        Args:
            history: Validation history entries.
            success: Whether validation succeeded.
            initial_reply: Optional initial reply to include.

        Returns:
            Human-readable validation report.
        """
        parts: list[str] = []
        if initial_reply:
            parts = [initial_reply, ""]
        for idx, record in enumerate(history):
            parts.append(f"validator input {record['attempt']}:\n{record['input']}")
            parts.append(f"validator feedback {record['attempt']}:\n{record['feedback']}")
            fixed = record.get("fixed")
            if fixed:
                has_next_attempt = idx + 1 < len(history)
                if has_next_attempt:
                    parts.append(
                        f"LLM tried to fix based on the validator feedback before attempt {record['attempt'] + 1}."
                    )
                else:
                    parts.append(f"fix attempt {record['attempt']}:\n```yaml\n{fixed}\n```")
            parts.append("")

        status = "[message_validation] passed" if success else "[message_validation] failed (see feedback)"
        parts.append(status)
        return "\n".join(parts).rstrip()

    def _format_yaml_blocks_for_display(self, yaml_blocks: list[YamlBlockPayload]) -> str:
        """Pretty-print numbered YAML blocks for validation reports.

        Args:
            yaml_blocks: YAML block payloads to format.

        Returns:
            Formatted YAML block display string.
        """
        lines: list[str] = []
        for idx, block in enumerate(yaml_blocks, start=1):
            content = block.get("content") or ""
            header = f"# block {idx}"
            lines.append(f"{header}\n```yaml\n{content}\n```")
        return "\n\n".join(lines)


__all__ = ["ToolCallValidationMiddleware", "MessageValidationMiddleware", "ValidationDecisionMiddleware"]
