"""Single-node handler that answers every request with one big prompt."""

import logging
from pathlib import Path
from typing import Any, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from app.assistant.project_context import resolve_project_context, resolve_user_context
from app.assistant.prompt import build_prompt_node_system_prompt
from app.assistant.state import ChatState

log = logging.getLogger(__name__)


def answer_prompt_node(
    state: ChatState,
    model: BaseChatModel,
    project_context: Path | str | None = None,
    user_context: Path | str | None = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Use a single, rich system prompt to answer any user message."""
    try:
        messages = state.get("messages", [])
        project_context_text = resolve_project_context(messages, project_context, state=True)
        user_context_text = resolve_user_context(messages, user_context, state=True)
        system_prompt = build_prompt_node_system_prompt(project_context_text, user_context_text)

        formatted_messages = [SystemMessage(content=system_prompt), *messages]

        ai_msg = model.invoke(formatted_messages)
        ai_message = ai_msg if isinstance(ai_msg, BaseMessage) else AIMessage(content=str(ai_msg))
        return {"messages": [ai_message]}
    except TimeoutError as exc:  # pragma: no cover - defensive guard
        log.exception("Timeout error invoking the model")
        return {"messages": [AIMessage(content=f"Timeout error invoking the model: {exc}")]}
    except ValueError as exc:  # pragma: no cover - defensive guard
        log.exception("Value error invoking the model")
        return {"messages": [AIMessage(content=f"Value error invoking the model: {exc}")]}
    except RuntimeError as exc:  # pragma: no cover - defensive guard
        log.exception("Runtime error invoking the model")
        return {"messages": [AIMessage(content=f"Runtime error invoking the model: {exc}")]}
    except Exception as exc:  # pragma: no cover - defensive guard
        log.exception("Unexpected error invoking the model")
        return {"messages": [AIMessage(content=f"Unexpected error invoking the model: {exc}")]}


def handle_prompt_node(
    state: ChatState,
    model: BaseChatModel,
    project_context: Path | str | None = None,
    user_context: Path | str | None = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Entry point wired into the LangGraph state machine."""
    return answer_prompt_node(state, model, project_context, user_context, verbose=verbose)


__all__ = ["answer_prompt_node", "handle_prompt_node"]
