"""Utility helpers for normalising language-model message content."""

import sqlite3
from collections.abc import Iterable
from typing import List, Protocol

from langchain_core.messages import AIMessage, BaseMessage


class SupportsClose(Protocol):
    """Protocol for resources that can be closed."""

    def close(self) -> None:
        """Close the underlying resource."""
        ...


def safe_close(resource: SupportsClose) -> None:
    """Safely closes a resource by calling its close method, suppressing OSError and RuntimeError exceptions."""
    try:
        resource.close()
    except (OSError, RuntimeError, sqlite3.ProgrammingError):
        # Intentionally ignore errors raised while closing resources.
        pass


def normalise_message_content(content: object) -> str:
    """Return LLM message content as plain text for downstream parsing."""
    if isinstance(content, AIMessage):
        return normalise_message_content(content.content)
    if isinstance(content, BaseMessage):
        return normalise_message_content(content.content)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Iterable) and not isinstance(content, (str, bytes)):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
                elif value is not None:
                    parts.append(str(value))
            else:
                parts.append(str(item))
        return " ".join(part.strip() for part in parts if part).strip()
    if content is None:
        return ""
    return str(content).strip()
