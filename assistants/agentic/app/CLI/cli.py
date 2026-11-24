"""CLI for Senpai Assistant."""

import argparse
from argparse import Namespace


def parse_conversation_arguments(argv: list[str] | None = None) -> Namespace:
    """Parses command-line arguments for the Senpai Assistant application.

    This function defines and processes command-line options that control
    how a conversation session is identified and managed.

    Args:
        argv (list[str] | None, optional): A list of command-line arguments.
            If None, the arguments are read from sys.argv by default.
            Useful for testing or programmatic invocation.

    Returns:
        argparse.Namespace: An object containing the parsed command-line options.

    Command-line options:
        -cid, --conversation-id : str
            Specifies the unique ID of the conversation session.
            This ID is used to retrieve or continue a conversation
            stored in the checkpoint database.
            If omitted, the conversation is not persisted.
        -v, --verbose : bool
            Enable verbose logging to see HTTP requests and debug information.
            (Default: False)

    Notes:
        - Any unrecognized arguments are ignored and returned as `unknown`
          for compatibility with other possible CLI components.
        - The conversation ID allows multiple sessions to coexist and
          resume independently within the same database.
    """
    parser = argparse.ArgumentParser(description="Senpai Assistant - A useful assistant for Chatbot Dojo.")

    parser.add_argument(
        "-cid",
        "--conversation-id",
        dest="conversation_id",
        type=str,
        help=("ID of the actual conversation."),
    )

    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        help="Enable verbose logging to see app logs.",
    )

    parser.add_argument(
        "-d", "--debug", dest="debug", action="store_true", help="Enable debug logging to see debug messages."
    )

    parser.add_argument(
        "-lf",
        "--log-file",
        dest="log_file",
        type=str,
        default="",
        help="Write logs to a timestamped file in this directory (e.g. logs/).",
    )

    parser.add_argument(
        "-pp",
        "--project-path",
        dest="project_path",
        type=str,
        required=True,
        help="Path to the sensei project. Senpai Assistant retrieves context from Sensei profiles in projects.",
    )

    parser.add_argument(
        "-up", "--user-path", dest="user_path", type=str, required=True, help="Path to the Chatbot Dojo user folder"
    )

    parser.add_argument(
        "-stp",
        "--single-turn-prompt",
        dest="single_turn_prompt",
        type=str,
        default=None,
        help="Prompt for single turn execution. If provided, only one interaction will take place. "
        "Designed for automated prompt interfaces. Disables save_* tools so outputs are "
        "returned in chat instead of HITL tool calls.",
    )

    args, unknown = parser.parse_known_args(argv)  # if argv, uses argv arguments
    del unknown

    return args
