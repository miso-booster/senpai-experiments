"""Tests for status message helpers."""

from __future__ import annotations

import pytest

from app.assistant import status_messages


def test_get_tool_status_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_messages, "_TOOL_STATUS_LABELS", {})

    assert status_messages.get_tool_status("unknown") == "Using tool: unknown"


def test_register_tool_status_overrides_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_messages, "_TOOL_STATUS_LABELS", {})

    status_messages.register_tool_status("search_rules", "Reading rules")

    assert status_messages.get_tool_status("search_rules") == "Reading rules"


def test_tool_status_event_appends_ellipsis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_messages, "_TOOL_STATUS_LABELS", {"list_rules": "Reading rules"})

    event = status_messages.tool_status_event("list_rules")

    assert event.text == "Reading rules..."
    assert event.is_tool is True


def test_tool_status_event_preserves_existing_ellipsis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_messages, "_TOOL_STATUS_LABELS", {"list_rules": "Reading rules..."})

    event = status_messages.tool_status_event("list_rules")

    assert event.text == "Reading rules..."
    assert event.is_tool is True


def test_as_status_event_converts_string() -> None:
    event = status_messages.as_status_event("Thinking...")

    assert event.text == "Thinking..."
    assert event.is_tool is False


def test_as_status_event_returns_existing() -> None:
    original = status_messages.StatusEvent(text="Working", is_tool=True)

    event = status_messages.as_status_event(original)

    assert event is original
