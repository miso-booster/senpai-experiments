"""Conversation loop for interactive chat with the assistant."""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, TypedDict, cast

from langgraph.types import Interrupt
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from rich.console import Console
from rich.markup import escape

from app.assistant.assistant import Assistant
from app.assistant.status_messages import StatusUpdate, as_status_event

try:
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError  # type: ignore
except AssertionError:

    class NoConsoleScreenBufferError(Exception):  # type: ignore
        """Dummy exception for non-Windows platforms."""

        pass


logger = logging.getLogger(__name__)

console = Console()
_EXIT_COMMANDS = {"salir", "exit", "quit"}


def run_conversation(assistant: Assistant) -> None:
    """Run an interactive chat loop using the provided assistant instance.

    Handles clean exits both via explicit commands and Ctrl+C interrupts.
    """
    _print_exit_hint()
    while True:
        try:
            _resolve_pending_interrupts_before_continue(assistant)
            user_input = _multiline_input()

            if _is_exit_command(user_input):
                _handle_exit_with_pending_interrupts(assistant)
                console.print("[bold yellow]Ending session...[/bold yellow]")
                break

            try:

                def _send_with_status(
                    update: Callable[[StatusUpdate], None],
                    message: str = user_input,
                ) -> str:
                    return assistant.send_message(message, status_callback=update)

                response = _run_with_status(_send_with_status)
            except RuntimeError as exc:
                if "Pending approvals must be resolved" in str(exc):
                    console.print("[bold yellow]Pending approvals must be resolved before continuing.[/bold yellow]")
                    continue
                raise
            response = _resume_after_interrupts(assistant, response, status_runner=_run_with_status)
            safe_response = escape(response) if response else "(no response)"
            console.print(f"[bold blue]Senpai:[/bold blue] {safe_response}")
        except KeyboardInterrupt:
            _notify_pending_interrupts(assistant)
            console.print("\n[bold yellow]Session interrupted (Ctrl+C). Exiting...[/bold yellow]")
            break


def run_single_turn(assistant: Assistant, user_input: str) -> str:
    """Run a single assistant turn and resolve any pending interrupts.

    Args:
        assistant: The assistant instance used to send the message.
        user_input: The user message to send.

    Returns:
        The assistant response text, or a fallback when empty.
    """
    try:
        response = assistant.send_message(user_input)
    except RuntimeError as exc:
        if "Pending approvals must be resolved" in str(exc):
            console.print("[bold yellow]Pending approvals must be resolved before continuing.[/bold yellow]")
            return "(no response)"
        raise
    response = _resume_after_interrupts(assistant, response)
    return response or "(no response)"


def _multiline_input() -> str:
    """Read multi-line user input from the terminal.

    Press Enter to submit, Ctrl+K to insert a new line.

    Returns:
        str: Returns message from user
    """
    try:
        kb = KeyBindings()

        @kb.add("c-k")
        def _(event: KeyPressEvent) -> None:
            """Control + k → newline."""
            event.current_buffer.insert_text("\n")

        @kb.add("enter")
        def _(event: KeyPressEvent) -> None:
            """Enter → submit."""
            event.app.exit(result=event.current_buffer.text)

        session: PromptSession[str] = PromptSession(
            multiline=True,
            message=HTML("<ansigreen><b>You:</b></ansigreen> "),
            key_bindings=kb,
        )
        message: str = session.prompt()
        return message

    except (NoConsoleScreenBufferError, EOFError):
        logger.warning("Multiline mode is not available in this console. Type your message and press Enter to submit.")
        return console.input("[bold green]You:[/bold green] ")


def _is_exit_command(text: str) -> bool:
    """Return True when the user asked to exit."""
    return text.strip().lower() in _EXIT_COMMANDS


def _print_exit_hint() -> None:
    """Display exit instructions at session start."""
    console.print("[bold green]Type your message. Press Ctrl+C or type exit/salir/quit to leave.[/bold green]")


def _resume_after_interrupts(
    assistant: Assistant,
    response: str,
    *,
    status_runner: Callable[[Callable[[Callable[[StatusUpdate], None]], str]], str] | None = None,
) -> str:
    """Resolve pending HITL approvals and return any follow-up response text.

    Args:
        assistant: Active assistant instance that may hold pending interrupts.
        response: Existing response text to return if no interrupts are pending.
        status_runner: Optional runner that wraps resumptions with status updates.

    Returns:
        Updated response text after resolving approvals, or the original response
        when nothing is pending.
    """
    get_pending = getattr(assistant, "get_pending_interrupts", None)
    resume = getattr(assistant, "resume_pending_interrupts", None)
    refresh = getattr(assistant, "refresh_pending_interrupts", None)
    if not callable(get_pending) or not callable(resume):
        return response

    get_pending_fn = cast(Callable[[], list[Interrupt]], get_pending)

    class _ResumePending(Protocol):
        def __call__(
            self,
            decisions: list[dict[str, Any]] | dict[str, dict[str, Any]],
            *,
            status_callback: Callable[[StatusUpdate], None] | None = None,
        ) -> str: ...

    resume_fn = cast(_ResumePending, resume)

    interrupts = get_pending_fn()
    if not interrupts and callable(refresh):
        refresh_fn = cast(Callable[[], list[Interrupt]], refresh)
        interrupts = refresh_fn()
    if not interrupts:
        return response

    latest_response = response
    while interrupts:
        decisions_payload = _collect_interrupt_decisions(interrupts)
        if status_runner:

            def _resume_with_status(
                update: Callable[[StatusUpdate], None],
                decisions: list[dict[str, Any]] | dict[str, dict[str, Any]] = decisions_payload,
            ) -> str:
                return resume_fn(decisions, status_callback=update)

            latest_response = status_runner(_resume_with_status)
        else:
            latest_response = resume_fn(decisions_payload)
        interrupts = get_pending_fn()
    return latest_response


class _StatusState(TypedDict):
    last_text: str
    last_activity: float
    tool_hold_until: float
    idle_index: int
    last_idle_update: float
    pending_text: str | None


def _run_with_status(action: Callable[[Callable[[StatusUpdate], None]], str]) -> str:
    """Run an action while showing status updates in the CLI.

    Args:
        action: Callable that performs work and emits status updates.

    Returns:
        Final response text from the action.
    """
    status_label = "Thinking..."
    idle_messages = [
        "Thinking...",
        "Drafting response...",
        "Reviewing context...",
        "Formulating reply...",
        "Checking details...",
    ]
    tool_hold_seconds = 2.0
    idle_cycle_seconds = 3.0

    spinner_style = "cyan"
    with console.status(status_label, spinner_style=spinner_style) as status:
        now = time.monotonic()
        state: _StatusState = {
            "last_text": status_label,
            "last_activity": now,
            "tool_hold_until": 0.0,
            "idle_index": 0,
            "last_idle_update": now,
            "pending_text": None,
        }
        stop_event = threading.Event()
        lock = threading.Lock()

        def update(update_value: StatusUpdate) -> None:
            """Handle status updates from the assistant stream.

            Args:
                update_value: Status update payload from the assistant.

            Returns:
                None
            """
            event = as_status_event(update_value)
            text = event.text
            if not text:
                return
            current = time.monotonic()
            with lock:
                state["last_activity"] = current
                state["idle_index"] = 0
                state["last_idle_update"] = current

                if event.is_tool:
                    state["tool_hold_until"] = current + tool_hold_seconds
                    state["pending_text"] = None
                    if text != state["last_text"]:
                        status.update(text)
                        state["last_text"] = text
                    return

                if current < state["tool_hold_until"]:
                    state["pending_text"] = text
                    return

                if text != state["last_text"]:
                    status.update(text)
                    state["last_text"] = text
                state["pending_text"] = None

        def heartbeat() -> None:
            """Rotate idle status text and apply deferred updates.

            Returns:
                None
            """
            while not stop_event.wait(0.5):
                current = time.monotonic()
                with lock:
                    if current < state["tool_hold_until"]:
                        continue

                    pending = state["pending_text"]
                    if pending and pending != state["last_text"]:
                        status.update(pending)
                        state["last_text"] = pending
                        state["pending_text"] = None
                        state["last_idle_update"] = current
                        continue

                    if state["last_text"] not in idle_messages and current >= state["tool_hold_until"]:
                        idle_text = idle_messages[state["idle_index"]]
                        if idle_text != state["last_text"]:
                            status.update(idle_text)
                            state["last_text"] = idle_text
                            state["last_idle_update"] = current
                        continue

                    if current - state["last_idle_update"] >= idle_cycle_seconds:
                        state["idle_index"] = (state["idle_index"] + 1) % len(idle_messages)
                        idle_text = idle_messages[state["idle_index"]]
                        if idle_text != state["last_text"]:
                            status.update(idle_text)
                            state["last_text"] = idle_text
                            state["last_idle_update"] = current

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            return action(update)
        finally:
            stop_event.set()
            thread.join(timeout=1.0)


def _resolve_pending_interrupts_before_continue(assistant: Assistant) -> None:
    """Resolve pending approvals before accepting new input.

    Args:
        assistant: Active assistant instance used to inspect pending approvals.
    """
    pending = _load_pending_interrupts(assistant)
    if not pending:
        return

    console.print("[bold yellow]Pending approvals detected from a previous session.[/bold yellow]")

    response = _resume_after_interrupts(assistant, "", status_runner=_run_with_status)
    if response:
        safe_response = escape(response)
        console.print(f"[bold blue]Senpai:[/bold blue] {safe_response}")
    return


def _handle_exit_with_pending_interrupts(assistant: Assistant) -> None:
    """Offer to resolve pending approvals before exiting the session.

    Args:
        assistant: Active assistant instance used to inspect pending approvals.
    """
    pending = _load_pending_interrupts(assistant)
    if not pending:
        return

    _print_pending_interrupts(pending)
    choice = input("Resolve pending approvals before exiting? [y/N]: ").strip().lower()
    if choice in {"y", "yes"}:
        response = _resume_after_interrupts(assistant, "", status_runner=_run_with_status)
        if response:
            safe_response = escape(response)
            console.print(f"[bold blue]Senpai:[/bold blue] {safe_response}")
    else:
        console.print("[bold yellow]Pending approvals remain for next session.[/bold yellow]")


def _notify_pending_interrupts(assistant: Assistant) -> None:
    """Notify the user when pending approvals remain after an interrupt.

    Args:
        assistant: Active assistant instance used to inspect pending approvals.
    """
    pending = _load_pending_interrupts(assistant)
    if pending:
        _print_pending_interrupts(pending)
        console.print("[bold yellow]Pending approvals remain for next session.[/bold yellow]")


def _load_pending_interrupts(assistant: Assistant) -> list[Interrupt]:
    """Fetch pending interrupts from the assistant if supported.

    Args:
        assistant: Active assistant instance used to fetch pending approvals.

    Returns:
        List of pending interrupt objects, empty when none are available.
    """
    refresh = getattr(assistant, "refresh_pending_interrupts", None)
    get_pending = getattr(assistant, "get_pending_interrupts", None)
    if not callable(get_pending):
        return []
    if callable(refresh):
        refresh_fn = cast(Callable[[], list[Interrupt]], refresh)
        refresh_fn()
    get_pending_fn = cast(Callable[[], list[Interrupt]], get_pending)
    return get_pending_fn()


def _print_pending_interrupts(interrupts: list[Interrupt]) -> None:
    """Print a summary of pending approvals.

    Args:
        interrupts: Pending interrupt objects to display.
    """
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None)
        action_requests: list[dict[str, Any]] = []
        if isinstance(value, dict):
            action_requests = value.get("action_requests", [])
        if not action_requests:
            console.print("[bold yellow]Pending approval:[/bold yellow] (details unavailable)")
            continue
        for action_request in action_requests:
            console.print(f"[bold yellow]Pending approval:[/bold yellow] {_format_action_request(action_request)}")


def _format_action_request(action_request: dict[str, Any]) -> str:
    """Format an action request for human review output.

    Args:
        action_request: HITL action request payload.

    Returns:
        Human-readable summary of the approval request.
    """
    description = action_request.get("description")
    if description:
        return escape(str(description))
    name = action_request.get("name", "unknown")
    args = action_request.get("args", {})
    return f"Tool: {escape(str(name))} Args: {escape(str(args))}"


def _collect_interrupt_decisions(
    interrupts: list[Interrupt],
) -> list[dict[str, Any]] | dict[str, dict[str, Any]]:
    if len(interrupts) == 1:
        return _decisions_for_interrupt(interrupts[0])

    decisions_by_interrupt: dict[str, dict[str, Any]] = {}
    for interrupt in interrupts:
        decisions_by_interrupt[interrupt.id] = {"decisions": _decisions_for_interrupt(interrupt)}
    return decisions_by_interrupt


def _decisions_for_interrupt(interrupt: Interrupt) -> list[dict[str, Any]]:
    value = getattr(interrupt, "value", None)
    action_requests: list[dict[str, Any]] = []
    if isinstance(value, dict):
        action_requests = value.get("action_requests", [])

    if not action_requests:
        return [
            {
                "type": "reject",
                "message": "No action requests available for review.",
            }
        ]

    decisions: list[dict[str, Any]] = []
    for action_request in action_requests:
        decisions.append(_prompt_hitl_decision(action_request))
    return decisions


def _prompt_hitl_decision(action_request: dict[str, Any]) -> dict[str, Any]:
    description = action_request.get("description")
    name = action_request.get("name", "unknown")
    args = action_request.get("args", {})

    if description:
        safe_description = escape(str(description))
        console.print(f"[bold yellow]Approval required:[/bold yellow] {safe_description}")
    else:
        safe_name = escape(str(name))
        safe_args = escape(str(args))
        console.print(f"[bold yellow]Approval required:[/bold yellow] Tool: {safe_name} Args: {safe_args}")

    while True:
        choice = input("Approve this tool call? [y/N]: ").strip().lower()
        if choice in {"y", "yes", "approve", "a"}:
            return {"type": "approve"}
        if choice in {"n", "no", "reject", "r", ""}:
            reason = input("Optional reason (Enter to skip): ").strip()
            decision: dict[str, Any] = {"type": "reject"}
            if reason:
                decision["message"] = reason
            return decision
        console.print("Please enter y or n.")
