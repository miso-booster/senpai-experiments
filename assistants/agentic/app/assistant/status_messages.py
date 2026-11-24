"""Helpers for consistent status messaging in the CLI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusEvent:
    """Structured status update event for the CLI.

    Args:
        text: Status text displayed to the user.
        is_tool: True when the status comes from a tool action.
    """

    text: str
    is_tool: bool = False


StatusUpdate = StatusEvent | str


_TOOL_STATUS_LABELS: dict[str, str] = {}


def register_tool_status(tool_name: str, label: str) -> None:
    """Register a tool status label.

    Args:
        tool_name: Tool name to register.
        label: Status label shown in the CLI.

    Returns:
        None
    """
    _TOOL_STATUS_LABELS[tool_name] = label


def get_tool_status(tool_name: str) -> str:
    """Return the status label for a tool.

    Args:
        tool_name: Tool name invoked by the agent.

    Returns:
        Status label for the tool, or a fallback label.
    """
    return _TOOL_STATUS_LABELS.get(tool_name, f"Using tool: {tool_name}")


def tool_status_event(tool_name: str) -> StatusEvent:
    """Create a status event for a tool invocation.

    Args:
        tool_name: Tool name invoked by the agent.

    Returns:
        Structured status event for the CLI.
    """
    label = get_tool_status(tool_name)
    if not label.endswith("..."):
        label = f"{label}..."
    return StatusEvent(text=label, is_tool=True)


def as_status_event(update: StatusUpdate) -> StatusEvent:
    """Normalize raw status updates into structured events.

    Args:
        update: Status update payload.

    Returns:
        Structured status event for the CLI.
    """
    if isinstance(update, StatusEvent):
        return update
    return StatusEvent(text=update, is_tool=False)
