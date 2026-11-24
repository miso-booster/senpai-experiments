"""Shared testing utilities."""

from __future__ import annotations

from typing import Any, List


class RecordingModel:
    """Simple fake LLM that stores prompts and returns a preset result."""

    def __init__(self, result: Any) -> None:
        self._result = result
        self.recorded_messages: List[Any] = []

    def invoke(self, messages: List[Any]) -> Any:  # noqa: ANN401
        self.recorded_messages.extend(messages)
        if isinstance(self._result, BaseException):
            raise self._result
        if callable(self._result):
            return self._result()
        return self._result
