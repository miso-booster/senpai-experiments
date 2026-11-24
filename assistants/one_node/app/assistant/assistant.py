"""High-level runtime interface for the Senpai Assistant."""

from __future__ import annotations

import logging
import sqlite3
import os
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver

from app.assistant.graph import create_assistant_graph
from app.assistant.state import ChatState

_DEFAULT_MODEL_NAME = os.getenv("SENPAI_MODEL", "gpt-4o-mini")
_DEFAULT_PROVIDER = os.getenv("SENPAI_MODEL_PROVIDER", "openai")
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_DB_NAME = "senpai_memory.db"


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the assistant runtime."""
    logging.getLogger().setLevel(logging.ERROR)

    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO if verbose else logging.WARNING)

    for name in (
        "httpx",
        "openai",
        "langgraph",
        "urllib3",
        "langchain",
        "langchain_openai",
    ):
        logging.getLogger(name).setLevel(logging.ERROR)


class Assistant:
    """Programmatic interface for interacting with the Senpai Assistant."""

    def __init__(
        self,
        *,
        model: BaseChatModel | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        db_path: str | Path | None = None,
        thread_id: str | None = None,
        verbose: bool = False,
        project_path: Path | str | None = None,
        user_path: Path | str | None = None,
        model_kwargs: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> None:
        """Instantiate the assistant.

        Args:
            model: Preconfigured chat model instance to use.
            checkpointer: External checkpoint saver. If omitted an internal SQLite
                saver is created automatically when persistence is enabled.
            db_path: Custom path for the SQLite database when the assistant owns it.
            thread_id: Default conversation identifier for message persistence.
            verbose: Enable verbose logging for the application logger when True.
            project_path: Path to the Sensei project folder.
            user_path: Path to the user folder.
            model_kwargs: Extra keyword arguments forwarded to `init_chat_model`.
            persist: When False, disable checkpoint persistence and avoid creating the SQLite DB.
        """
        setup_logging(verbose=verbose)

        self.verbose = bool(verbose)
        self._persist = bool(persist)

        self._default_thread_id = thread_id or uuid.uuid4().hex

        self._external_connection = checkpointer is not None
        self._conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None

        if self._external_connection:
            if checkpointer is None:
                raise ValueError("checkpointer must be provided when using external connections")
            if db_path is not None:
                self._db_path = Path(db_path)
            self._checkpointer: BaseCheckpointSaver[Any] | None = checkpointer
        elif self._persist:
            self._db_path = _resolve_db_path(db_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path.as_posix(), check_same_thread=False)
            self._checkpointer = SqliteSaver(self._conn)
        else:
            self._checkpointer = None

        if model is not None:
            self._model: BaseChatModel = model
        else:
            extra_kwargs = dict(model_kwargs or {})
            extra_kwargs.setdefault("temperature", _DEFAULT_TEMPERATURE)
            # Optional OpenAI-compatible endpoint (e.g. DeepSeek) for the model comparison experiments.
            if os.getenv("SENPAI_MODEL_BASE_URL"):
                extra_kwargs.setdefault("base_url", os.environ["SENPAI_MODEL_BASE_URL"])
                extra_kwargs.setdefault("api_key", os.environ["SENPAI_MODEL_API_KEY"])
            self._model = init_chat_model(
                model=_DEFAULT_MODEL_NAME,
                model_provider=_DEFAULT_PROVIDER,
                **extra_kwargs,
            )

        self._project_path = project_path
        self._user_path = user_path

        self._graph = create_assistant_graph(
            self._model,
            self._checkpointer,
            self._project_path,
            self._user_path,
            verbose=self.verbose,
        )
        self._closed = False

    @property
    def thread_id(self) -> str:
        """Return the default thread identifier used for conversations."""
        return self._default_thread_id

    @thread_id.setter
    def thread_id(self, value: str) -> None:
        self._default_thread_id = value

    @property
    def db_path(self) -> Path | None:
        """Return the path to the SQLite database if owned by this instance."""
        return self._db_path

    def send_message(self, message: str, *, thread_id: str | None = None) -> str:
        """Send a single message to the assistant and return the response text."""
        if self._closed:
            raise RuntimeError("Assistant is closed.")
        if not isinstance(message, str):
            raise TypeError("message must be a string")

        active_thread = thread_id or self._default_thread_id
        state: ChatState = {"messages": [HumanMessage(content=message)]}
        final_text: str | None = None

        stream_config: RunnableConfig | None = (
            cast(RunnableConfig, {"configurable": {"thread_id": active_thread}}) if self._checkpointer else None
        )

        for snapshot in self._graph.stream(
            state,
            config=stream_config,
            stream_mode="values",
        ):
            msgs = snapshot.get("messages", [])
            for msg in reversed(msgs):
                if isinstance(msg, AIMessage):
                    content = msg.content
                    if isinstance(content, str):
                        final_text = content
                    break

        if final_text is None and self._checkpointer is not None:
            checkpoint = self._graph.get_state(config={"configurable": {"thread_id": active_thread}})
            if checkpoint and isinstance(checkpoint.values, dict):
                msgs = checkpoint.values.get("messages", [])
                for msg in reversed(msgs):
                    if isinstance(msg, AIMessage):
                        content = msg.content
                        if isinstance(content, str):
                            final_text = content
                        break

        return final_text or ""

    def close(self) -> None:
        """Close underlying resources owned by the assistant."""
        if self._closed:
            return
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._closed = True

    def __enter__(self) -> "Assistant":
        """Enter the managed context returning self."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        """Ensure owned resources are released when leaving the context."""
        self.close()


def _resolve_db_path(db_path: str | Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "data" / _DEFAULT_DB_NAME
