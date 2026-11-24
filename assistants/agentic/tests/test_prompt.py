"""Tests for building the assistant system prompt."""

from __future__ import annotations

from app.assistant.prompt import (
    build_prompt_node_system_prompt,
    build_system_prompt,
)


def test_build_system_prompt_includes_reference_docs() -> None:
    prompt = build_system_prompt()

    assert "You are Senpai" in prompt
    assert "Reference documentation" in prompt
    assert "get_docs" in prompt
    assert "High-level mental model" in prompt
    assert "profiles generate conversations and define extracted data" in prompt
    assert "implicit project-local documentation or file questions" in prompt
    assert "What is an oracle?" not in prompt
    for name in ("sensei-check-doc.md", "rules-examples.md", "sensei-chat-guide.md"):
        assert name in prompt


def test_build_prompt_node_wraps_guidelines() -> None:
    prompt = build_prompt_node_system_prompt()
    base_prompt = build_system_prompt()

    assert prompt == base_prompt
    assert "ROLE AND DOMAIN FOCUS" in prompt
    assert "ABSOLUTE RULE: DOC-FIRST WORKFLOW" in prompt
    assert "TODO LIST" in prompt
    assert "get_docs" in prompt
    assert "If the user asks for anything outside these areas" not in prompt
