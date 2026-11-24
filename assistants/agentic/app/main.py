"""Main entry point for the Senpai Assistant application."""

import logging
import os
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from app.assistant.assistant import Assistant
from app.assistant.conversation import console as conversation_console
from app.assistant.conversation import run_conversation, run_single_turn
from app.CLI.cli import parse_conversation_arguments
from app.embeddings.embedding_build import get_or_build_index
from app.utils.logger import logging_config
from app.utils.sensei_path_validation import validate_sensei_path
from app.utils.tracing import enable_langsmith_tracing
from app.utils.utilities import safe_close

logger = logging.getLogger(__name__)
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    # In some environments (e.g., redirected streams or certain test/CI setups),
    # stdout/stderr may not support reconfiguration. Failing silently here avoids
    # breaking module import while keeping default behavior otherwise.
    logger.warning(
        "sys.stdout.reconfigure and sys.stderr.reconfigure calls at module level "
        "failed because this environment doesn't support stdout/stderr reconfiguration"
    )
    pass


_ROOT_PATH = Path(".Senpai-Assistant").resolve()


def _setup_configuration() -> Namespace:
    """Parse command line arguments.

    Returns:
        The parsed and validated command line arguments

    Raises:
        Error: If the specified technology is invalid
    """
    args = parse_conversation_arguments()

    verbose = getattr(args, "verbose", False)
    debug = getattr(args, "debug", False)
    log_file = getattr(args, "log_file", "") or None

    logging_config(verbose, debug, log_file=log_file)

    enable_langsmith_tracing(
        enabled=bool(os.getenv("LANGSMITH_TRACING", "").lower() == "true"),
        project_name=None,
        api_key=None,
    )

    return args


def get_index_dir(project_dir: Path) -> Path:
    """Devuelve la carpeta donde se guardará el índice dentro del proyecto."""
    index_dir = project_dir / ".sensei_index"
    index_dir.mkdir(exist_ok=True)
    return index_dir


def get_index_path(project_dir: Path) -> Path:
    """Ruta al fichero principal del índice."""
    return get_index_dir(project_dir) / "index.pkl"


def _normalize_project_path(project_path: Path | str) -> Path:
    """Expand and validate the provided Sensei project path."""
    return validate_sensei_path(project_path, "project")


def _normalize_user_path(user_path: Path | str) -> Path:
    """Expand and validate the provided Sensei user path."""
    return validate_sensei_path(user_path, "user")


def _create_embedding_path(path: Path | None) -> Path | None:
    """Create or retrieve the embedding index path for a given project/user.

    Args:
        path (Path | None): Path to the Sensei project root, Chatbot Dojo user root or None
            if no project/user is associated with the conversation.

    Returns:
        Path | None: The path to the embedding index for the project/user, or None
        if no project/user path was provided.
    """
    if path:
        return get_or_build_index(path)
    return None


def deploy_assistant(
    thread_id: str | None,
    embedding_path: Path | None,
    project_path: Path | None,
    connectors_path: Path | None,
    connectors_embedding_path: Path | None,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    checkpointer_connection: sqlite3.Connection | None = None,
    single_turn_prompt: str | None = None,
) -> None:
    """Initialize and run an assistant instance for a given project.

    Args:
        thread_id (str | None): Unique identifier for the assistant conversation.
        embedding_path (Path | None): Path to the project embedding directory associated with the assistant.
        project_path (Path | None): Path to the Sensei project root.
        connectors_path (Path | None): Path to the connectors' directory.
        connectors_embedding_path (Path | None): Path to the connectors' embedding directory.
        checkpointer (BaseCheckpointSaver[Any] | None): Optional checkpointer override used
            to persist state outside the default database.
        checkpointer_connection (sqlite3.Connection | None): Connection tied to the optional
            checkpointer, closed after the conversation ends.
        single_turn_prompt (str | None): Optional prompt for single turn execution. Designed for
            automated prompt interface. When provided, save_* tools are disabled.

    Returns:
        None
    """
    assistant = Assistant(
        thread_id=thread_id,
        project_path=project_path,
        embedding_path=embedding_path,
        connectors_path=connectors_path,
        connectors_embedding_path=connectors_embedding_path,
        checkpointer=checkpointer,
        include_create_tools=single_turn_prompt is None,
    )

    print(f"conversation ID: {assistant.thread_id}")

    try:
        if single_turn_prompt:
            answer = run_single_turn(assistant, single_turn_prompt)
            answer = f"$$$\n{answer}\n$$$"
            print(answer)
        else:
            run_conversation(assistant)
    finally:
        safe_close(assistant)
        if checkpointer_connection is not None:
            safe_close(checkpointer_connection)


def _build_checkpointer(
    conversation_id: str | None,
) -> tuple[BaseCheckpointSaver[Any] | None, sqlite3.Connection | None]:
    if conversation_id:
        return None, None
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    return SqliteSaver(connection), connection


def main() -> None:
    """Main function of the script."""
    try:
        args = _setup_configuration()
        thread_id = getattr(args, "conversation_id", None)
        single_turn_prompt = getattr(args, "single_turn_prompt", None)
        try:
            project_path = _normalize_project_path(args.project_path)
            user_path = _normalize_user_path(args.user_path)
            connectors_path = user_path / "connectors"
            project_embedding_path = _create_embedding_path(project_path)
            connectors_embedding_path = _create_embedding_path(connectors_path)
        except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
            logger.error("%s", exc)
            conversation_console.print(f"[bold red]{exc}[/bold red]")
            sys.exit(1)
        if not thread_id:
            conversation_console.print(
                "[bold yellow]No conversation ID was added to this run, conversation memory will not be saved.[/bold yellow]"
            )

        checkpointer, checkpointer_connection = _build_checkpointer(thread_id)
        deploy_assistant(
            thread_id=thread_id,
            embedding_path=project_embedding_path,
            connectors_embedding_path=connectors_embedding_path,
            project_path=project_path,
            connectors_path=connectors_path,
            checkpointer=checkpointer,
            checkpointer_connection=checkpointer_connection,
            single_turn_prompt=single_turn_prompt,
        )
    except KeyboardInterrupt:
        conversation_console.print("\n[bold yellow]Session interrupted (Ctrl+C). Exiting...[/bold yellow]")


if __name__ == "__main__":
    main()
