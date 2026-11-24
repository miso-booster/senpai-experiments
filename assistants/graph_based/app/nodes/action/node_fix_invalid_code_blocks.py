"""LLM-driven fixer that replaces invalid code blocks with corrected versions."""

import logging
from typing import Any, Dict, Iterable, List, Tuple

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.assistant.codeblocks import extract_code_blocks
from app.assistant.state import ChatState
from app.utils.utilities import normalise_message_content

log = logging.getLogger(__name__)


def _render_block_for_prompt(content: str, language: str | None) -> str:
    """Wrap block content inside a fenced code block for prompts.

    Args:
        content: Raw block content.
        language: Optional language identifier extracted from the fence.

    Returns:
        The content wrapped in a Markdown fence with the provided language.
    """
    lang = (language or "").strip()
    fence = f"```{lang}\n{content}\n```"
    return fence


def _format_block_issues(
    block_index: int,
    validation_result: Dict[str, Any],
    invalid_snippets: Iterable[Dict[str, Any]] | None,
) -> str:
    """Create a textual summary of validator findings for a specific block.

    Args:
        block_index: Index of the code block being summarised.
        validation_result: Aggregated validation result for that block.
        invalid_snippets: Granular validator entries (rules, profiles, etc.).

    Returns:
        A bullet-style text summary describing the issues to fix.
    """
    lines: List[str] = []

    if invalid_snippets:
        for snippet in invalid_snippets:
            if snippet.get("block_index") != block_index:
                continue
            snippet_kind = snippet.get("snippet_kind") or ""
            snippet_number = snippet.get("snippet_number")
            prefix_parts: List[str] = []
            if snippet_kind:
                prefix_parts.append(str(snippet_kind).title())
            if snippet_number is not None:
                prefix_parts.append(str(snippet_number))
            prefix = " ".join(prefix_parts).strip()
            if prefix:
                prefix = f"{prefix}: "

            for error in snippet.get("errors", []) or []:
                lines.append(f"- {prefix}{error}")
            for warning in snippet.get("warnings", []) or []:
                lines.append(f"- {prefix}(warning) {warning}")

    if not lines:
        for error in validation_result.get("errors", []) or []:
            lines.append(f"- {error}")
        for warning in validation_result.get("warnings", []) or []:
            lines.append(f"- (warning) {warning}")

    if not lines:
        return "- The validator reported issues but none were captured."
    return "\n".join(lines)


def fix_invalid_code_blocks(
    state: ChatState,
    model: BaseChatModel,
    *,
    fix_system_prompt: str,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Ask the model to repair only the invalid code blocks from the last AI message.

    The function builds per-block prompts that include the failing snippet and the
    validator findings, requests a corrected Markdown fence from the LLM, and
    replaces the corresponding segments in the original assistant reply.

    Args:
        state: Current chat state containing messages and validation metadata.
        model: Bound LLM used to generate the fixes.
        fix_system_prompt: System prompt that puts the LLM into "fix" mode.
        verbose: Enables debug logging of prompts and outputs when True.

    Returns:
        A partial state update that swaps the failing blocks with fixed versions,
        or indicates that no retry is required when nothing was replaced.
    """
    messages = state.get("messages", []) or []
    if not messages:
        return {"retry_action": "none"}

    last_ai_index = None
    last_ai_message: AIMessage | None = None
    for index in range(len(messages) - 1, -1, -1):
        candidate = messages[index]
        if isinstance(candidate, AIMessage):
            last_ai_index = index
            last_ai_message = candidate
            break

    if last_ai_index is None or last_ai_message is None:
        return {"retry_action": "none"}

    raw_text = normalise_message_content(last_ai_message.content)
    if not raw_text:
        return {"retry_action": "none"}

    code_blocks: List[Dict[str, Any]] = state.get("code_blocks", []) or []
    validation_results: List[Dict[str, Any]] = state.get("validation_results", []) or []
    invalid_snippets: List[Dict[str, Any]] = state.get("invalid_snippets", []) or []

    results_by_index = {result.get("index"): result for result in validation_results if isinstance(result, dict)}
    invalid_indexes = [
        index
        for index, result in results_by_index.items()
        if isinstance(index, int)
        and isinstance(result, dict)
        and not result.get("skipped")
        and result.get("is_valid") is False
    ]

    if not invalid_indexes:
        return {"retry_action": "none", "needs_retry": False}

    replacements: List[tuple[int, int, str]] = []

    for block_index in sorted(invalid_indexes, reverse=True):
        try:
            block = code_blocks[block_index]
        except (IndexError, TypeError):
            log.warning("Missing code block metadata for index %s", block_index)
            continue

        start = block.get("start")
        end = block.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            log.warning("Invalid offsets for code block %s", block_index)
            continue

        block_language = block.get("language")
        block_type = block.get("block_type") or results_by_index[block_index].get("block_type")
        issues_text = _format_block_issues(block_index, results_by_index[block_index], invalid_snippets)

        current_block_content = block.get("content", "")
        prompt_block = _render_block_for_prompt(current_block_content, block_language)
        human_prompt = (
            f"Please fix only code block #{block_index + 1} (type: {block_type}).\n\n"
            f"Current block:\n{prompt_block}\n\n"
            f"Validator feedback:\n{issues_text}\n\n"
            "Return only the corrected Markdown code fence, keeping the same language tag. "
            "Do not add explanations before or after the block."
        )

        prompt_messages = [SystemMessage(content=fix_system_prompt), HumanMessage(content=human_prompt)]

        if verbose:
            print("\n" + "=" * 80)
            print(f"FIX INPUT (block {block_index + 1}):")
            print("=" * 80)
            print(human_prompt)
            print("=" * 80 + "\n")

        try:
            fix_response = model.invoke(prompt_messages)
        except Exception:
            log.exception("Error requesting fix for block %s", block_index)
            continue

        fix_text = normalise_message_content(fix_response)
        fix_blocks = extract_code_blocks(fix_text)
        if not fix_blocks:
            log.warning("Fix response did not contain a code block for index %s", block_index)
            continue

        replacement_block = fix_text[fix_blocks[0].start : fix_blocks[0].end]
        replacements.append((start, end, replacement_block))

        if verbose:
            print("\n" + "=" * 80)
            print(f"FIX OUTPUT (block {block_index + 1}):")
            print("=" * 80)
            print(replacement_block)
            print("=" * 80 + "\n")

    if not replacements:
        return {"retry_action": "none", "needs_retry": False}

    new_text: str

    # Apply all replacements in a single pass to avoid offset issues
    if replacements:
        replacements_sorted: List[Tuple[int, int, str]] = sorted(replacements, key=lambda x: x[0])
        new_text_parts: List[str] = []
        last_index: int = 0

        for start, end, replacement in replacements_sorted:
            new_text_parts.append(raw_text[last_index:start])
            new_text_parts.append(replacement)
            last_index = end

        new_text_parts.append(raw_text[last_index:])
        new_text = "".join(new_text_parts)
    else:
        new_text = raw_text

    updated_message = last_ai_message.model_copy(update={"content": new_text})
    return {
        "messages": [updated_message],
        "retry_action": "none",
        "needs_retry": False,
    }
