"""Validation helpers for Sensei YAML code blocks."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

import yaml

from app.validator.profiles_validator import validate_profile
from app.validator.rules_validator import validate_rule

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
    results: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []

    for index, block in enumerate(code_blocks):
        language_raw = block.get("language")
        language = (language_raw or "").lower()
        block_type_raw = block.get("block_type")
        normalized_type = (block_type_raw or "").lower()
        validator_type = "profile" if normalized_type == "profile" else "rule"
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

        block_type = block.get("block_type")
        documents = block.get("documents", []) or []
        if block_type == "error" or len(documents) != 1:
            reason = block.get("error_reason") or "multiple_documents_not_supported"
            error_message = "Each code block must contain exactly one YAML document."
            if reason != "multiple_documents_not_supported":
                error_message = reason
            result_block_type = block_type or validator_type
            block_result = {
                "index": index,
                "language": language_raw,
                "block_type": result_block_type,
                "is_valid": False,
                "errors": [error_message],
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
                    "errors": [error_message],
                    "warnings": [],
                }
            )
            continue

        content = block.get("content", "")
        if validator_type == "profile":
            block_result, block_invalid = _validate_profile_block(content)
        else:
            block_result, block_invalid = _validate_rule_block(content)

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
    feedback = _format_validation_feedback(invalid)

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


def _format_validation_feedback(invalid_rules: List[Dict[str, Any]]) -> str:
    """Build a human-readable summary of validation errors for the model."""
    sections: List[str] = []
    for item in invalid_rules:
        block_number = item.get("block_index", 0) + 1
        snippet_kind = item.get("snippet_kind") or "block"
        snippet_number = item.get("snippet_number")
        language = item.get("language")

        label_map = {
            "rule": "Rule block",
            "profile": "Profile block",
            "block": "Code block",
            "unknown": "Code block",
        }

        header = label_map.get(snippet_kind, "Code block") + f" {block_number}"
        if snippet_kind == "rule" and snippet_number is not None:
            header += f" (rule {snippet_number})"
        elif snippet_number is not None:
            header += f" (item {snippet_number})"
        if language:
            header += f" ({language})"

        lines = [header, "Errors:"]
        lines.extend(f"- {error}" for error in item.get("errors", []))
        warnings = item.get("warnings") or []
        if warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in warnings)

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _validate_rule_block(content: str) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run the rule validator for a YAML code block."""
    rule_texts = _split_rule_block(content)
    if len(rule_texts) > 1:
        message = "Each code block must contain exactly one YAML document."
        block_result = {
            "is_valid": False,
            "errors": [message],
            "warnings": [],
            "data": None,
            "rules": [],
        }
        invalid_entries = [
            {
                "snippet_kind": "rule",
                "snippet_number": None,
                "errors": [message],
                "warnings": [],
            }
        ]
        return block_result, invalid_entries
    block_result, block_invalid = _validate_rule_texts(rule_texts)

    invalid_entries = [
        {
            "snippet_kind": "rule",
            "snippet_number": item["rule_number"],
            "errors": item["errors"],
            "warnings": item["warnings"],
        }
        for item in block_invalid
    ]

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


def _split_rule_block(content: str) -> List[str]:
    """Split a YAML rule block into individual rule snippets when possible."""
    try:
        documents = list(yaml.safe_load_all(content))
    except yaml.YAMLError:
        return [content]

    flattened: List[Any] = []
    for doc in documents:
        if doc is None:
            continue
        if isinstance(doc, list):
            flattened.extend(doc)
        else:
            flattened.append(doc)

    if len(flattened) <= 1 or not all(isinstance(item, dict) for item in flattened):
        return [content]

    snippets: List[str] = []
    for item in flattened:
        dumped = yaml.safe_dump(item, sort_keys=False)
        snippets.append(dumped.strip())

    return snippets or [content]


def _validate_rule_texts(rule_texts: List[str]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Validate one or more SENSEI rules extracted from a YAML block."""
    rules_info: List[Dict[str, Any]] = []
    invalid_rules: List[Dict[str, Any]] = []
    block_is_valid = True

    for idx, rule_text in enumerate(rule_texts):
        validation = validate_rule(rule_text)
        rule_entry = {
            "rule_index": idx,
            "is_valid": validation.is_valid,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "data": validation.data,
        }
        rules_info.append(rule_entry)

        if not validation.is_valid:
            block_is_valid = False
            invalid_rules.append(
                {
                    "rule_number": idx + 1,
                    "errors": list(validation.errors),
                    "warnings": list(validation.warnings),
                }
            )

    if len(rule_texts) == 1:
        single = rules_info[0]
        errors = list(single["errors"])
        warnings = list(single["warnings"])
        data = single["data"] if single["is_valid"] else None
    else:
        errors = [
            f"[Rule {idx + 1}] {error}"
            for idx, info in enumerate(rules_info)
            if not info["is_valid"]
            for error in info["errors"]
        ]
        warnings = [
            f"[Rule {idx + 1}] {warning}" for idx, info in enumerate(rules_info) for warning in info["warnings"]
        ]
        valid_data = [info["data"] for info in rules_info if info["is_valid"] and info["data"] is not None]
        data = valid_data if block_is_valid else None

    block_result = {
        "is_valid": block_is_valid,
        "errors": errors,
        "warnings": warnings,
        "data": data,
        "rules": rules_info,
    }

    return block_result, invalid_rules


__all__ = ["SUPPORTED_CODE_LANGUAGES", "MAX_VALIDATION_ATTEMPTS", "validate_code_blocks"]
