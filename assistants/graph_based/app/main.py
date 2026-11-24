"""Main entry point for the Senpai Assistant application."""

import sys
from argparse import Namespace
from pathlib import Path

from app.assistant.assistant import Assistant
from app.assistant.conversation import run_conversation, run_single_turn
from app.CLI.cli import parse_conversation_arguments
from app.utils.utilities import safe_close

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _setup_configuration() -> Namespace:
    """Parse command line arguments.

    Returns:
        The parsed and validated command line arguments

    Raises:
        Error: If the specified technology is invalid
    """
    args = parse_conversation_arguments()

    return args


def deploy_assistant(
    thread_id: str | None,
    verbose: bool,
    project_path: str | Path,
    user_path: str | Path,
    single_turn_prompt: str | None = None,
) -> None:
    """Initialize and run an assistant instance for a given project.

    Args:
        thread_id (str | None): Unique identifier for the assistant conversation.
        verbose (bool): If True, enables detailed console output.
        project_path (str | Path): Path to the project directory associated with the assistant.
        user_path (str | Path): Path to the user directory containing connectors.
        single_turn_prompt (str | None): Optional prompt for single turn execution.

    Returns:
        None
    """
    assistant = Assistant(thread_id=thread_id, verbose=verbose, project_path=project_path, user_path=user_path)

    if assistant.thread_id:
        print(f"conversation ID: {assistant.thread_id}")
    else:
        print("No conversation ID provided; running without conversation persistence.")

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
        safe_close(assistant)


def main() -> None:
    """Main function of the script."""
    args = _setup_configuration()
    thread_id = args.conversation_id
    verbose = getattr(args, "verbose", False)
    project_path = args.project_path
    user_path = args.user_path
    single_turn_prompt = getattr(args, "single_turn_prompt", None)
    deploy_assistant(
        thread_id=thread_id,
        verbose=verbose,
        project_path=project_path,
        user_path=user_path,
        single_turn_prompt=single_turn_prompt,
    )


if __name__ == "__main__":
    main()
