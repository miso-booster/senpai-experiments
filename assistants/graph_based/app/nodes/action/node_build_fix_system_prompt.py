"""Helper for constructing the fix-mode system prompt used during retries."""

from pathlib import Path

from app.assistant.project_context import resolve_project_context
from app.assistant.prompt import SYSTEM_PROMPT

_FIX_MODE_SUFFIX = (
    "You are now in fix mode. When you receive a YAML code block that failed validation, "
    "analyse the reported issues and respond ONLY with a corrected Markdown-fenced code block. "
    "Preserve the language identifier (for example, ```yaml) and do not include explanations, "
    "extra commentary, or additional code outside the block."
)


def build_fix_system_prompt(project_context: str | Path) -> str:
    """Compose the system prompt used when requesting targeted fixes.

    Args:
        project_context: Additional project context appended to the system prompt.

    Returns:
        A system message string that instructs the LLM how to behave in fix mode.
    """
    parts = [SYSTEM_PROMPT]
    context_text = resolve_project_context(project_context)
    if context_text:
        parts.append(context_text)
    parts.append(_FIX_MODE_SUFFIX)
    return "\n".join(part for part in parts if part)
