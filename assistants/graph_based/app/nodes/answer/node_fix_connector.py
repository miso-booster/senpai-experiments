"""Handlers for fix-connector intents powered by the connectors system prompt."""

import logging
from typing import Any, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from app.assistant.project_context import resolve_project_context
from app.assistant.prompt import SENSEI_CONNECTORS_SYSTEM_PROMPT
from app.assistant.state import ChatState

log = logging.getLogger(__name__)


def answer_fix_connector(
    state: ChatState, model: BaseChatModel, project_context: str = "", verbose: bool = False
) -> Dict[str, Any]:
    """Generate a connector-fix response using the provided model."""
    context_text = resolve_project_context(project_context)
    sys_msg = f"{SENSEI_CONNECTORS_SYSTEM_PROMPT}\n{context_text}"
    try:
        messages = state.get("messages", [])
        formatted_messages = [SystemMessage(content=sys_msg), *messages]
        ai_msg = model.invoke(formatted_messages)
        ai_message = ai_msg if isinstance(ai_msg, BaseMessage) else AIMessage(content=str(ai_msg))
        return {"messages": [ai_message]}
    except TimeoutError as e:
        log.exception("Timeout error invoking the model")
        return {"messages": [AIMessage(content=f"Timeout error invoking the model: {e}")]}
    except ValueError as e:
        log.exception("Value error invoking the model")
        return {"messages": [AIMessage(content=f"Value error invoking the model: {e}")]}
    except RuntimeError as e:
        log.exception("Runtime error invoking the model")
        return {"messages": [AIMessage(content=f"Runtime error invoking the model: {e}")]}
    except Exception as e:
        log.exception("Unexpected error invoking the model")
        return {"messages": [AIMessage(content=f"Unexpected error invoking the model: {e}")]}


def handle_fix_connector(
    state: ChatState, model: BaseChatModel, project_context: str = "", verbose: bool = False
) -> Dict[str, Any]:
    """Entry point for fix-connector intents."""
    return answer_fix_connector(state, model, project_context, verbose=verbose)
