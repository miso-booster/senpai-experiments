"""High-level runtime interface for the Senpai Assistant."""

from __future__ import annotations

import sqlite3
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, Interrupt

from app.assistant.agent import create_assistant_agent
from app.assistant.status_messages import StatusUpdate, tool_status_event

_DEFAULT_MODEL_NAME = os.getenv("SENPAI_MODEL", "gpt-4o-mini")
_DEFAULT_PROVIDER = os.getenv("SENPAI_MODEL_PROVIDER", "openai")
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_DB_NAME = "senpai_memory.db"
StatusCallback = Callable[[StatusUpdate], None]


class Assistant:
    """Programmatic interface for interacting with the Senpai Assistant."""

    def __init__(
        self,
        *,
        model: BaseChatModel | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        db_path: str | Path | None = None,
        thread_id: str | None = None,
        embedding_path: Path | None = None,
        project_path: Path | None = None,
        connectors_path: Path | None = None,
        connectors_embedding_path: Path | None = None,
        include_create_tools: bool = True,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Instantiate the assistant.

        Args:
            model: Preconfigured chat model instance to use.
            checkpointer: External checkpoint saver. If omitted an internal SQLite
                saver is created automatically.
            db_path: Custom path for the SQLite database when the assistant owns it.
            thread_id: Default conversation identifier for message persistence.
            embedding_path: Path to the Sensei project folder.
            project_path: Root path to the Sensei project; used by tools.
            connectors_path: Path to the connectors' folder.
            connectors_embedding_path: Path to the connectors' embedding folder.
            include_create_tools: When False, omit save_* tools and their HITL interrupts.
            model_kwargs: Extra keyword arguments forwarded to `init_chat_model`.
        """
        self._default_thread_id = thread_id or uuid.uuid4().hex

        self._external_connection = checkpointer is not None
        self._conn: sqlite3.Connection | None = None
        self._db_path: Path | None = None

        if self._external_connection:
            if checkpointer is None:
                raise ValueError("checkpointer must be provided when using external connections")
            if db_path is not None:
                self._db_path = Path(db_path)
            self._checkpointer: BaseCheckpointSaver[Any] = checkpointer
        else:
            self._db_path = _resolve_db_path(db_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path.as_posix(), check_same_thread=False)
            self._checkpointer = SqliteSaver(self._conn)

        if model is not None:
            self._model: BaseChatModel = model
        else:
            extra_kwargs = dict(model_kwargs or {})
            extra_kwargs.setdefault("temperature", _DEFAULT_TEMPERATURE)
            # Optional OpenAI-compatible endpoint (e.g. DeepSeek) for the model comparison experiments.
            if os.getenv("SENPAI_MODEL_BASE_URL"):
                extra_kwargs.setdefault("base_url", os.environ["SENPAI_MODEL_BASE_URL"])
                extra_kwargs.setdefault("api_key", os.environ["SENPAI_MODEL_API_KEY"])
                # LangChain has no profile for such models; SummarizationMiddleware needs the context window.
                extra_kwargs.setdefault(
                    "profile", {"max_input_tokens": int(os.getenv("SENPAI_MODEL_MAX_INPUT_TOKENS", "1048576"))}
                )
            self._model = init_chat_model(
                model=_DEFAULT_MODEL_NAME,
                model_provider=_DEFAULT_PROVIDER,
                **extra_kwargs,
            )

        self._project_embedding_path = embedding_path
        self._project_path = project_path
        self._connectors_path = connectors_path
        self._connectors_embedding_path = connectors_embedding_path

        self._agent = create_assistant_agent(
            self._model,
            self._checkpointer,
            project_path=self._project_path,
            connectors_path=self._connectors_path,
            embedding_path=self._project_embedding_path,
            connectors_embedding_path=self._connectors_embedding_path,
            include_create_tools=include_create_tools,
        )
        self._last_interrupts: list[Interrupt] = []
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

    def send_message(
        self,
        message: str,
        *,
        thread_id: str | None = None,
        status_callback: StatusCallback | None = None,
    ) -> str:
        """Send a single message to the assistant and return the response text.

        status_callback, when provided, receives short status updates during streaming.
        """
        if self._closed:
            raise RuntimeError("Assistant is closed.")
        if not isinstance(message, str):
            raise TypeError("message must be a string")

        active_thread = thread_id or self._default_thread_id
        self.refresh_pending_interrupts(thread_id=active_thread)
        if self._last_interrupts:
            raise RuntimeError("Pending approvals must be resolved before sending a new message.")
        run_config = self._build_run_config(active_thread)
        state = {"messages": [HumanMessage(content=message)]}
        self._last_interrupts = []
        return self._stream_response(state, run_config, status_callback=status_callback)

    def get_pending_interrupts(self) -> list[Interrupt]:
        """Return any pending interrupts from the last run."""
        return list(self._last_interrupts)

    def refresh_pending_interrupts(self, *, thread_id: str | None = None) -> list[Interrupt]:
        """Load pending interrupts from the checkpointer for the given thread."""
        active_thread = thread_id or self._default_thread_id
        run_config = self._build_run_config(active_thread)
        self._last_interrupts = []

        checkpoint = self._agent.get_state(config=run_config)
        if checkpoint is None:
            return list(self._last_interrupts)

        interrupts_attr = getattr(checkpoint, "interrupts", None)
        if interrupts_attr:
            self._last_interrupts = list(interrupts_attr)
            return list(self._last_interrupts)

        values = getattr(checkpoint, "values", None)
        if isinstance(values, dict):
            interrupts = values.get("__interrupt__")
            if interrupts:
                self._last_interrupts = list(interrupts)

        return list(self._last_interrupts)

    def resume_pending_interrupts(
        self,
        decisions: list[dict[str, Any]] | dict[str, dict[str, Any]],
        *,
        thread_id: str | None = None,
        status_callback: StatusCallback | None = None,
    ) -> str:
        """Resume execution after handling a human-in-the-loop interrupt.

        status_callback, when provided, receives short status updates during streaming.
        """
        if not self._last_interrupts:
            self.refresh_pending_interrupts(thread_id=thread_id)
        if not self._last_interrupts:
            return ""

        active_thread = thread_id or self._default_thread_id
        run_config = self._build_run_config(active_thread)

        if isinstance(decisions, list):
            if len(self._last_interrupts) > 1:
                raise ValueError("Multiple interrupts require decisions mapped by interrupt id.")
            resume_value: dict[str, Any] = {"decisions": decisions}
        else:
            resume_value = decisions

        self._last_interrupts = []
        command: Command[object] = Command(resume=resume_value)
        return self._stream_response(command, run_config, status_callback=status_callback)

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

    def _build_run_config(self, active_thread: str) -> dict[str, object]:
        """Build a consistent run configuration for agent executions."""
        config: dict[str, object] = {"configurable": {"thread_id": active_thread}}
        tags = ["senpai-assistant", f"thread:{active_thread}"]
        if tags:
            config["tags"] = tags

        metadata: dict[str, object] = {}
        if self._project_path:
            metadata["project_path"] = str(self._project_path)
        if self._connectors_path:
            metadata["connectors_path"] = str(self._connectors_path)
        if self._project_embedding_path:
            metadata["embedding_path"] = str(self._project_embedding_path)
        if self._connectors_embedding_path:
            metadata["connectors_embedding_path"] = str(self._connectors_embedding_path)
        if metadata:
            config["metadata"] = metadata

        return config

    def _stream_response(
        self,
        input_payload: object,
        run_config: dict[str, object],
        *,
        status_callback: StatusCallback | None = None,
    ) -> str:
        final_text: str | None = None
        reported_tool_calls: set[str] = set()

        if status_callback:
            status_callback("Thinking...")

        for event in self._agent.stream(
            input_payload,
            config=run_config,
            stream_mode=["messages", "updates"],
        ):
            if isinstance(event, tuple) and len(event) == 2:
                stream_mode, data = event
            else:
                stream_mode, data = "values", event

            if stream_mode == "messages":
                continue

            if not isinstance(data, dict):
                continue

            updates = data if stream_mode == "updates" else {"values": data}
            for update in updates.values():
                if not isinstance(update, dict):
                    continue

                interrupts = update.get("__interrupt__")
                if interrupts:
                    self._last_interrupts = list(interrupts)

                msgs = update.get("messages", [])
                for msg in msgs:
                    if isinstance(msg, AIMessage):
                        tool_calls = list(getattr(msg, "tool_calls", None) or [])
                        for index, tool_call in enumerate(tool_calls):
                            tool_name = tool_call.get("name") or "tool"
                            # Tool calls can repeat across streamed updates; emit status once per call.
                            tool_id = tool_call.get("id")
                            if not tool_id:
                                tool_id = f"{tool_name}:{index}:{hash(str(tool_call.get('args')))}"
                            if tool_id in reported_tool_calls:
                                continue
                            reported_tool_calls.add(tool_id)
                            if status_callback:
                                status_callback(tool_status_event(tool_name))
                        content = msg.content
                        if isinstance(content, str) and content:
                            final_text = content

        # Refresh checkpoint interrupts when the stream did not surface any, to avoid missing pending approvals.
        if final_text is None or not self._last_interrupts:
            checkpoint = self._agent.get_state(config=run_config)
            if checkpoint is not None:
                interrupts_attr = getattr(checkpoint, "interrupts", None)
                if interrupts_attr:
                    self._last_interrupts = list(interrupts_attr)

                values = getattr(checkpoint, "values", None)
                if final_text is None and isinstance(values, dict):
                    msgs = values.get("messages", [])
                    for msg in reversed(msgs):
                        if not isinstance(msg, AIMessage):
                            continue
                        content = msg.content
                        if isinstance(content, str) and content:
                            final_text = content
                            break

        return final_text or ""


def _resolve_db_path(db_path: str | Path | None) -> Path:
    if db_path is not None:
        return Path(db_path)
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "data" / _DEFAULT_DB_NAME
