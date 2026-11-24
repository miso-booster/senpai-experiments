"""Tests for the interactive conversation loop."""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Tuple, cast

import pytest

from app.assistant.assistant import Assistant
from app.assistant.conversation import console, run_conversation


class StubAssistant:
    """Mock assistant for testing the conversation loop."""

    def __init__(self) -> None:
        self.messages: List[str] = []
        self.replies: Deque[str] = deque(["response"])

    def send_message(self, message: str) -> str:
        self.messages.append(message)
        return self.replies.popleft()


def test_run_conversation_processes_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the conversation loop works correctly and exits on 'exit'."""
    inputs: Deque[str] = deque(["hola", "exit"])
    monkeypatch.setattr("builtins.input", lambda: inputs.popleft())

    printed: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = []

    def capture_print(*args: Any, **kwargs: Any) -> None:
        printed.append((args, kwargs))

    monkeypatch.setattr(console, "print", capture_print)

    assistant = StubAssistant()
    run_conversation(cast(Assistant, assistant))

    assert assistant.messages == ["hola"]
    assert ("[bold blue]Senpai:[/bold blue] response",) in [entry[0] for entry in printed]


def test_run_conversation_allows_spanish_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the conversation loop exits on 'salir'."""
    inputs: Deque[str] = deque(["salir"])
    monkeypatch.setattr("builtins.input", lambda: inputs.popleft())

    assistant = StubAssistant()
    run_conversation(cast(Assistant, assistant))

    assert assistant.messages == []
