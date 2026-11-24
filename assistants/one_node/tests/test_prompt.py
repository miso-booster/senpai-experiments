"""Tests for building the assistant system prompt."""

from __future__ import annotations

from app.assistant.prompt import (
    PROMPT_NODE_GUIDELINES,
    build_prompt_node_system_prompt,
    build_system_prompt,
)


def test_build_system_prompt_includes_reference_docs() -> None:
    prompt = build_system_prompt()

    assert "You are Senpai" in prompt
    assert "### sensei-check-doc.md" in prompt
    assert "### rules-examples.md" in prompt
    assert "### sensei-chat-guide.md" in prompt


def test_build_prompt_node_wraps_guidelines_and_context() -> None:
    prompt = build_prompt_node_system_prompt("### User Project Context\nrule: demo", "### User Folder Context\nx: y")

    assert "Assistant Responsibilities" in prompt
    assert PROMPT_NODE_GUIDELINES.strip().splitlines()[1] in prompt
    assert "rule: demo" in prompt
    assert "### User Folder Context" in prompt
