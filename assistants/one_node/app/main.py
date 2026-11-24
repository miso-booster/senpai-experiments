"""Main entry point for the Senpai Assistant application."""

import logging
import sys
from argparse import Namespace
from pathlib import Path

from app.assistant.assistant import Assistant
from app.assistant.conversation import run_conversation, run_single_turn
from app.CLI.cli import parse_conversation_arguments
from app.config import config

logger = logging.getLogger(__name__)


def _configure_stdio() -> None:
    """Ensure stdout/stderr use utf-8 encoding when supported."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        logger.warning(
            "sys.stdout.reconfigure and sys.stderr.reconfigure calls "
            "failed because this environment doesn't support stdout/stderr reconfiguration"
        )


def _setup_configuration() -> Namespace:
    """Parse command line arguments.

    Returns:
        The parsed and validated command line arguments

    Raises:
        Error: If the specified technology is invalid
    """
    args = parse_conversation_arguments()

    config.VERBOSE = getattr(args, "verbose", False)

    return args


def deploy_assistant(
    thread_id: str | None,
    verbose: bool,
    project_path: Path | str | None,
    user_path: Path | str | None,
    *,
    single_turn_prompt: str | None = None,
) -> None:
    """Initialize and run an assistant instance for a given project.

    Args:
        thread_id: Unique identifier for the assistant conversation.
            When None, persistence is disabled.
        verbose: If True, enables detailed console output.
        project_path: Path to the Sensei project directory associated with the
            assistant. When None, no project context is associated.
        user_path: Path to the user folder associated with the assistant.
        single_turn_prompt: Optional prompt for single turn execution. When provided,
            only one interaction is executed and the response is printed.
    """
    persist = bool(thread_id)
    assistant = Assistant(
        thread_id=thread_id,
        verbose=verbose,
        project_path=project_path,
        user_path=user_path,
        persist=persist,
    )

    if not persist:
        print("No conversation ID provided; persistence is disabled and this conversation will not be saved.")

    if persist and thread_id:
        print(f"conversation ID: {thread_id}")
    else:
        print(f"ephemeral conversation id (not persisted): {assistant.thread_id}")

    if assistant.verbose:
        print("Verbose activated")

    try:
        if single_turn_prompt:
            answer = run_single_turn(assistant, single_turn_prompt)
            answer = f"$$$\n{answer}\n$$$"
            print(answer)
        else:
            run_conversation(assistant)
    finally:
        assistant.close()


def main() -> None:
    """Main function of the script."""
    _configure_stdio()
    args = _setup_configuration()
    thread_id = args.conversation_id
    verbose = getattr(args, "verbose", False)
    single_turn_prompt = getattr(args, "single_turn_prompt", None)
    project_path = args.project_path
    user_path = args.user_path
    deploy_assistant(
        thread_id=thread_id,
        verbose=verbose,
        project_path=project_path,
        user_path=user_path,
        single_turn_prompt=single_turn_prompt,
    )


if __name__ == "__main__":
    main()
