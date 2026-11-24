"""Validation helpers for Sensei YAML code blocks."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterable, List

from senpai_validators import validate_connector, validate_profile, validate_rule
from senpai_validators.utils import append_get_docs_hint

logger = logging.getLogger(__name__)


SUPPORTED_CODE_LANGUAGES = {"yaml", "yml"}
MAX_VALIDATION_ATTEMPTS = 3


def validate_code_blocks(  # noqa: ANN401
    code_blocks: Iterable[Dict[str, Any]],
    attempts_so_far: int = 0,
    *,
    intent: str | None = None,
) -> Dict[str, Any]:
    """Validate YAML code blocks and decide whether a retry is required.

    Args:
        code_blocks: Parsed YAML code block metadata extracted from the model response.
        attempts_so_far: Number of validation attempts already performed for this turn.
        intent: Optional intent inferred from the user request (create, fix, or other).

    Returns:
        A partial state update describing validation outcomes and potential retries.
    """
    code_blocks = list(code_blocks)
    results: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    validators = _get_validators()

    for index, block in enumerate(code_blocks):
        language_raw = block.get("language")
        language = (language_raw or "").lower()
        block_type_raw = block.get("block_type")
        normalized_type = (block_type_raw or "").lower()
        if normalized_type in validators:
            validator_type = normalized_type
        else:
            validator_type = "unknown"

        logger.info(f"Validator type: {validator_type}")

        if language and language not in SUPPORTED_CODE_LANGUAGES:
            results.append(
                {
                    "index": index,
                    "language": language_raw,
                    "block_type": block_type_raw,
                    "skipped": True,
                    "reason": "unsupported_language",
                }
            )
            continue

        if normalized_type not in validators and normalized_type not in {"", None, "unknown", "error"}:
            results.append(
                {
                    "index": index,
                    "language": language_raw,
                    "block_type": block_type_raw,
                    "skipped": True,
                    "reason": "unsupported_block_type",
                }
            )
            continue

        block_type = block.get("block_type")
        documents = block.get("documents", []) or []
        if block_type == "error" or len(documents) != 1:
            reason = block.get("error_reason") or "multiple_documents_not_supported"
            error_message = "Each code block must contain exactly one YAML document."
            if reason != "multiple_documents_not_supported":
                error_message = reason
            errors_with_hint = [error_message]
            append_get_docs_hint(errors_with_hint, kind="unknown")
            result_block_type = block_type or validator_type
            block_result = {
                "index": index,
                "language": language_raw,
                "block_type": result_block_type,
                "is_valid": False,
                "errors": errors_with_hint,
                "warnings": [],
                "data": None,
            }
            results.append(block_result)
            invalid.append(
                {
                    "block_index": index,
                    "language": language_raw,
                    "block_type": result_block_type,
                    "snippet_kind": "block",
                    "snippet_number": None,
                    "errors": errors_with_hint,
                    "warnings": [],
                }
            )
            continue

        content = block.get("content", "")
        validator = validators.get(validator_type)
        if validator is None:
            errors_with_hint = [
                "Could not classify this YAML block as a rule, profile, or connector. "
                "If it is intentionally generic or a tiny one-line snippet, consider removing the YAML fence so it won't be validated; "
                "otherwise align it with one of the supported schemas so it can be validated."
            ]
            append_get_docs_hint(errors_with_hint, kind="unknown")
            result_block_type = block_type_raw or validator_type
            block_result = {
                "index": index,
                "language": language_raw,
                "block_type": result_block_type,
                "is_valid": False,
                "errors": errors_with_hint,
                "warnings": [],
                "data": None,
            }
            results.append(block_result)
            invalid.append(
                {
                    "block_index": index,
                    "language": language_raw,
                    "block_type": result_block_type,
                    "snippet_kind": "unknown",
                    "snippet_number": None,
                    "errors": errors_with_hint,
                    "warnings": [],
                }
            )
            continue

        block_result, block_invalid = validator(content)

        block_result.update({"index": index, "language": language_raw, "block_type": validator_type})
        results.append(block_result)

        for item in block_invalid:
            invalid.append(
                {
                    "block_index": index,
                    "language": language_raw,
                    "block_type": validator_type,
                    "snippet_kind": item["snippet_kind"],
                    "snippet_number": item.get("snippet_number"),
                    "errors": item["errors"],
                    "warnings": item["warnings"],
                }
            )

    if not invalid:
        return {
            "validation_results": results,
            "needs_retry": False,
            "validation_attempts": 0,
            "retry_action": "none",
            "invalid_snippets": [],
            "validation_feedback": None,
        }

    attempt_number = attempts_so_far + 1
    feedback = _format_validation_feedback(invalid, total_blocks=len(code_blocks))

    if attempt_number < MAX_VALIDATION_ATTEMPTS:
        return {
            "validation_results": results,
            "validation_attempts": attempt_number,
            "needs_retry": True,
            "retry_action": "fix_blocks",
            "invalid_snippets": invalid,
            "validation_feedback": feedback,
        }

    failure_context: Dict[str, Any] = {
        "attempts": attempt_number,
        "feedback": feedback,
        "intent": intent or "other",
    }

    return {
        "validation_results": results,
        "validation_attempts": attempt_number,
        "needs_retry": False,
        "retry_action": "final_failure",
        "invalid_snippets": invalid,
        "validation_feedback": feedback,
        "final_failure_context": failure_context,
    }


def _format_validation_feedback(invalid_rules: List[Dict[str, Any]], *, total_blocks: int) -> str:
    """Build a repair-oriented validation summary for the model."""
    invalid_blocks = sorted({int(item.get("block_index", 0)) + 1 for item in invalid_rules})
    valid_blocks = [block for block in range(1, total_blocks + 1) if block not in invalid_blocks]

    sections = [
        "Validation repair summary:",
        f"- invalid blocks: {_format_block_numbers(invalid_blocks)}",
        f"- valid blocks: {_format_block_numbers(valid_blocks)}",
        "",
    ]

    for item in invalid_rules:
        block_number = int(item.get("block_index", 0)) + 1
        snippet_kind = item.get("snippet_kind") or "block"
        snippet_number = item.get("snippet_number")
        language = item.get("language")
        errors = list(item.get("errors") or [])
        warnings = list(item.get("warnings") or [])
        primary_error = _select_primary_error(errors)
        line = item.get("line")
        column = item.get("column")
        error_class = item.get("error_class")
        area = item.get("area") or item.get("field") or item.get("field_path")
        fix_instruction = item.get("repair_instruction") or item.get("repair_hint")

        header = f"Block {block_number}"
        if snippet_kind == "rule" and snippet_number is not None:
            header += f" (rule {snippet_number})"
        elif snippet_number is not None:
            header += f" (item {snippet_number})"
        if language:
            header += f" ({language})"

        lines = [header]
        if error_class:
            lines.append(f"- error class: {error_class}")
        if area:
            lines.append(f"- area: {area}")
        if isinstance(line, int):
            lines.append(f"- line: {line}")
        if isinstance(column, int):
            lines.append(f"- column: {column}")
        lines.append(f"- issue: {primary_error}")
        if fix_instruction:
            lines.append(f"- what to do: {fix_instruction}")

        docs_hint = _extract_docs_hint(errors)
        if docs_hint:
            lines.append(f"- docs hint: {docs_hint}")
        if warnings:
            lines.append(f"- warnings: {'; '.join(warnings)}")

        sections.append("\n".join(lines))
        sections.append("")

    if invalid_blocks:
        if valid_blocks:
            sections.append(
                f"Final instruction:\nKeep blocks {_format_block_numbers(valid_blocks)} unchanged. "
                f"Rewrite the full reply, but only modify blocks {_format_block_numbers(invalid_blocks)} "
                "and any prose that references them."
            )
        else:
            sections.append(
                "All blocks are invalid. Rewrite the full reply, keeping the same number of blocks but changing all of them."
            )

    return "\n".join(sections).rstrip()


def _format_block_numbers(block_numbers: List[int]) -> str:
    """Format block numbers for repair summaries."""
    if not block_numbers:
        return "none"
    return ", ".join(str(number) for number in block_numbers)


def _select_primary_error(errors: List[str]) -> str:
    """Choose the main error to surface in repair summaries."""
    for error in errors:
        if "get_docs tool" not in error:
            return error
    return errors[0] if errors else "Validation failed."


def _extract_docs_hint(errors: List[str]) -> str | None:
    """Extract the validator docs hint, if present."""
    for error in errors:
        if "get_docs tool" in error:
            return error
    return None


def _validate_rule_block(content: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run the rule validator for a YAML code block."""
    validation = validate_rule(content)
    block_result = {
        "is_valid": validation.is_valid,
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "data": validation.data if validation.is_valid else None,
        "rule": {
            "is_valid": validation.is_valid,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "data": validation.data,
        },
    }

    invalid_entries: List[Dict[str, Any]] = []
    if not validation.is_valid:
        invalid_entries.append(
            {
                "snippet_kind": "rule",
                "snippet_number": 1,
                "errors": list(validation.errors),
                "warnings": list(validation.warnings),
            }
        )

    return block_result, invalid_entries


def _validate_profile_block(content: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run the profile validator for a YAML code block."""
    validation = validate_profile(content)
    block_result = {
        "is_valid": validation.is_valid,
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "data": validation.data if validation.is_valid else None,
        "profile": {
            "is_valid": validation.is_valid,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "data": validation.data,
        },
    }

    invalid_entries: List[Dict[str, Any]] = []
    if not validation.is_valid:
        invalid_entries.append(
            {
                "snippet_kind": "profile",
                "snippet_number": None,
                "errors": list(validation.errors),
                "warnings": list(validation.warnings),
            }
        )

    return block_result, invalid_entries


def _validate_connector_block(content: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run the connector validator for a YAML code block."""
    validation = validate_connector(content)
    block_result = {
        "is_valid": validation.is_valid,
        "errors": list(validation.errors),
        "warnings": list(validation.warnings),
        "data": validation.data if validation.is_valid else None,
        "connector": {
            "is_valid": validation.is_valid,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "data": validation.data,
        },
    }

    invalid_entries: List[Dict[str, Any]] = []
    if not validation.is_valid:
        invalid_entries.append(
            {
                "snippet_kind": "connector",
                "snippet_number": None,
                "errors": list(validation.errors),
                "warnings": list(validation.warnings),
            }
        )

    return block_result, invalid_entries


def _get_validators() -> Dict[str, Callable[[str], tuple[Dict[str, Any], List[Dict[str, Any]]]]]:
    """Return the current validator mapping."""
    return {
        "rule": _validate_rule_block,
        "profile": _validate_profile_block,
        "connector": _validate_connector_block,
    }


__all__ = ["SUPPORTED_CODE_LANGUAGES", "MAX_VALIDATION_ATTEMPTS", "validate_code_blocks"]
