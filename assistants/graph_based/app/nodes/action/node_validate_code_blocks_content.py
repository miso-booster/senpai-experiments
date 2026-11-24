"""Invoke the YAML validator for any extracted code blocks in the chat state."""

from typing import Any, Dict

from app.assistant.state import ChatState
from app.assistant.validation import validate_code_blocks


def validate_code_blocks_content(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
    """Validate extracted code blocks using the appropriate validator based on content type."""
    code_blocks = state.get("code_blocks", []) or []
    if not code_blocks:
        return {
            "validation_results": [],
            "needs_retry": False,
            "validation_attempts": 0,
        }

    attempts_so_far = state.get("validation_attempts", 0)
    intent = state.get("intent")

    result = validate_code_blocks(
        code_blocks,
        attempts_so_far,
        intent=intent,
    )
    if intent:
        result.setdefault("intent", intent)
    elif "intent" not in result:
        result["intent"] = "other"
    return result
