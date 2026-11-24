"""Tests for building the assistant system prompt."""

from __future__ import annotations

from app.assistant.prompt import build_system_prompt


def test_build_system_prompt_includes_reference_docs() -> None:
    prompt = build_system_prompt()

    assert "You are Senpai" in prompt
    assert "### sensei-check-doc.md" in prompt
    assert "### rules-examples.md" in prompt
    assert "### sensei-chat-guide.md" in prompt
