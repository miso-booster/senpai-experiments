"""High-level runtime interface for the Senpai Assistant."""

from __future__ import annotations

import logging
import re
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

from app.assistant.codeblocks import extract_code_blocks
from app.assistant.graph import create_assistant_graph
from app.assistant.project_context import (
    ProjectContextStats,
    UserContextStats,
    build_prompt_contexts,
)
from app.assistant.state import ChatState

_DEFAULT_MODEL_NAME = os.getenv("SENPAI_MODEL", "gpt-4o-mini")
_DEFAULT_PROVIDER = os.getenv("SENPAI_MODEL_PROVIDER", "openai")
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_DB_NAME = "senpai_memory.db"
_FAIL_CLOSED_VALIDATION_FALLBACK = (
    "I'm sorry, but I couldn't produce a YAML response that passed validation after multiple attempts. "
    "Please adjust your instructions and try again."
)
_VALIDATED_YAML_INTENTS = {
    "create_rule",
    "create_profile",
    "create_connector",
    "fix_rule",
    "fix_profile",
    "fix_connector",
}
_YAMLISH_KEY_LINE = re.compile(r"^\s*(?:-\s+)?[a-z_][a-z0-9_-]*\s*:\s*", re.IGNORECASE)


def _looks_like_unfenced_yaml_payload(text: str) -> bool:
    """Heuristic for YAML-like payloads returned without Markdown code fences."""
    stripped = text.strip()
    if not stripped or "```" in stripped:
        return False

    lines = [line.rstrip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return False

    key_like_count = sum(1 for line in lines if _YAMLISH_KEY_LINE.match(line))
    if key_like_count >= 2:
        return True

    # Accept common one-line YAML such as "name: my_rule", but avoid prose prefixes
    # like "Note: ..." by requiring a lowercase-ish key token.
    if key_like_count == 1 and len(lines) == 1:
        key = lines[0].split(":", 1)[0].strip()
        if key and key == key.lower() and " " not in key:
            return True

    return False


def _should_block_unvalidated_yaml(snapshot: object, text: str | None) -> bool:
    """Fail closed when a YAML-generating flow ends without a valid final validation result."""
    if not isinstance(snapshot, dict):
        return False
    if not isinstance(text, str) or not text.strip():
        return False

    intent = snapshot.get("intent")
    if intent not in _VALIDATED_YAML_INTENTS:
        return False

    # Respect explicit opt-out flows (e.g. user requested intentionally broken output).
    if snapshot.get("should_validate") is False:
        return False

    has_fenced_code = bool(extract_code_blocks(text))
    has_yamlish_unfenced_payload = _looks_like_unfenced_yaml_payload(text)
    if not has_fenced_code and not has_yamlish_unfenced_payload:
        return False

    raw_results = snapshot.get("validation_results") or []
    if not isinstance(raw_results, list) or not raw_results:
        return True

    saw_non_skipped = False
    saw_valid = False

    for result in raw_results:
        if not isinstance(result, dict):
            continue
        if result.get("skipped"):
            continue
        saw_non_skipped = True
        if result.get("is_valid") is False:
            return True
        if result.get("is_valid") is True:
            saw_valid = True

    if not saw_non_skipped:
        return True
    if not saw_valid:
        return True

    return False


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
        project_path: Path | str = "",
        user_path: Path | str = "",
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Instantiate the assistant.

        Args:
            model: Preconfigured chat model instance to use.
            checkpointer: External checkpoint saver. If omitted an internal SQLite
                saver is created only when a conversation ID is provided.
            db_path: Custom path for the SQLite database when the assistant owns it.
            thread_id: Default conversation identifier for message persistence.
                When omitted and no external ``checkpointer`` is provided, the assistant
                runs without persistence. When an external ``checkpointer`` is provided
                and ``thread_id`` is omitted, persistence is still enabled and a UUID
                thread identifier may be auto-generated.
            verbose: Enable verbose logging for the application logger when True.
            project_path: Path to the Sensei project folder.
            user_path: Path to the user's connector folder.
            model_kwargs: Extra keyword arguments forwarded to `init_chat_model`.
        """
        setup_logging(verbose=verbose)

        self.verbose = bool(verbose)

        self._external_connection = checkpointer is not None
        self._conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None
        self._pending_db_path: str | Path | None = db_path
        self._checkpointer: BaseCheckpointSaver[Any] | None = None
        self._persistence_enabled = False
        self._default_thread_id: str | None = None

        if self._external_connection:
            if checkpointer is None:
                raise ValueError("checkpointer must be provided when using external connections")
            if db_path is not None:
                self._db_path = Path(db_path)
            self._checkpointer = checkpointer
            self._persistence_enabled = True
            self._default_thread_id = thread_id or uuid.uuid4().hex
        else:
            if thread_id:
                self._enable_internal_persistence(thread_id=thread_id, db_path=db_path)

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

        self._prompt_contexts, self._project_context_stats, self._user_context_stats = self._load_prompt_contexts(
            project_path,
            user_path,
        )

        self._graph = create_assistant_graph(
            self._model,
            self._checkpointer,
            self._prompt_contexts,
            verbose=self.verbose,
        )
        self._closed = False

    @property
    def thread_id(self) -> str | None:
        """Return the default thread identifier used for conversations."""
        return self._default_thread_id

    @thread_id.setter
    def thread_id(self, value: str | None) -> None:
        # If persistence was disabled because no conversation ID was provided,
        # lazily enable it when a thread ID becomes available.
        if value and not self._persistence_enabled and not self._external_connection:
            self._enable_internal_persistence(thread_id=value, db_path=self._pending_db_path)
            self._graph = create_assistant_graph(
                self._model,
                self._checkpointer,
                self._prompt_contexts,
                verbose=self.verbose,
            )
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

        if thread_id and not self._persistence_enabled and not self._external_connection:
            self.thread_id = thread_id

        active_thread = thread_id or self._default_thread_id
        state: ChatState = {"messages": [HumanMessage(content=message)]}
        final_text: str | None = None
        final_snapshot: dict[str, Any] | None = None

        config: RunnableConfig | None
        if self._persistence_enabled and active_thread:
            config = cast(RunnableConfig, {"configurable": {"thread_id": active_thread}})
        else:
            config = None

        for snapshot in self._graph.stream(
            state,
            config=config,
            stream_mode="values",
        ):
            if isinstance(snapshot, dict):
                final_snapshot = snapshot
            msgs = snapshot.get("messages", [])
            for msg in reversed(msgs):
                if isinstance(msg, AIMessage):
                    content = msg.content
                    if isinstance(content, str):
                        final_text = content
                    break

        if final_text is None and self._persistence_enabled and active_thread:
            checkpoint_config = cast(RunnableConfig, {"configurable": {"thread_id": active_thread}})
            checkpoint = self._graph.get_state(config=checkpoint_config)
            if checkpoint and isinstance(checkpoint.values, dict):
                msgs = checkpoint.values.get("messages", [])
                for msg in reversed(msgs):
                    if isinstance(msg, AIMessage):
                        content = msg.content
                        if isinstance(content, str):
                            final_text = content
                        break

        if _should_block_unvalidated_yaml(final_snapshot, final_text):
            final_text = _FAIL_CLOSED_VALIDATION_FALLBACK

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

    def _load_prompt_contexts(
        self,
        project_path: Path | str | None,
        user_path: Path | str | None,
    ) -> tuple[dict[str, str], ProjectContextStats, UserContextStats]:
        prompt_contexts, project_stats, user_stats = build_prompt_contexts(project_path or "", user_path or "")
        if self.verbose:
            if project_stats.root is None:
                print("[project-context] No project path provided; continuing without extra context.")
            else:
                profile_list = ", ".join(file.name for file in project_stats.profiles) or "none"
                rule_list = ", ".join(file.name for file in project_stats.rules) or "none"
                print(
                    "[project-context] "
                    f"Loaded {len(project_stats.profiles)} profile(s) [{profile_list}] and "
                    f"{len(project_stats.rules)} rule(s) [{rule_list}] from {project_stats.root}"
                )
            if user_stats.root is None:
                print("[user-context] No user path provided; continuing without connector context.")
            else:
                connector_list = ", ".join(file.name for file in user_stats.connectors) or "none"
                connector_root = user_stats.connectors_root or user_stats.root
                print(
                    "[user-context] "
                    f"Loaded {len(user_stats.connectors)} connector(s) [{connector_list}] from {connector_root}"
                )
        return prompt_contexts, project_stats, user_stats

    def _enable_internal_persistence(self, *, thread_id: str, db_path: str | Path | None) -> None:
        """Initialize the internal SQLite checkpointer for a given thread ID."""
        self._default_thread_id = thread_id
        self._db_path = _resolve_db_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path.as_posix(), check_same_thread=False)
        self._checkpointer = SqliteSaver(self._conn)
        self._persistence_enabled = True


def _resolve_db_path(db_path: str | Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "data" / _DEFAULT_DB_NAME
