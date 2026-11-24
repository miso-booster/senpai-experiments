"""Handlers for create-profile intents backed by the profile system prompt."""

import logging
from typing import Any, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from app.assistant.project_context import resolve_project_context
from app.assistant.prompt import SENSEI_PROFILES_SYSTEM_PROMPT
from app.assistant.state import ChatState

log = logging.getLogger(__name__)


def answer_create_profile(
    state: ChatState, model: BaseChatModel, project_context: str = "", verbose: bool = False
) -> Dict[str, Any]:
    """Main node. Generates response using the provided model.

    Args:
        state: The current chat state containing messages.
        model: The LLM model to use for generating responses.
        project_context: The project information parsed as text for extended project context.
        verbose: Enable verbose logging for LLM input/output.

    Returns:
        A dictionary with updated messages list.
    """
    context_text = resolve_project_context(project_context)
    sys_msg = f"{SENSEI_PROFILES_SYSTEM_PROMPT}\n{context_text}"
    try:
        messages = state.get("messages", [])
        formatted_messages = [SystemMessage(content=sys_msg), *messages]

        # uncomment for debugging LLM inputs/outputs
        # if verbose:
        #     print("\n" + "=" * 80)
        #     print("LLM INPUT:")
        #     print("=" * 80)
        #     for i, msg in enumerate(formatted_messages):
        #         msg_type = type(msg).__name__
        #         print(f"\n[Message {i + 1} - {msg_type}]")
        #         print("-" * 40)
        #         print(msg.content)
        #     print("=" * 80 + "\n")

        ai_msg = model.invoke(formatted_messages)

        # uncomment for debugging LLM inputs/outputs
        # if verbose:
        #     print("\n" + "=" * 80)
        #     print("LLM OUTPUT:")
        #     print("=" * 80)
        #     if isinstance(ai_msg, BaseMessage):
        #         print(ai_msg.content)
        #     else:
        #         print(str(ai_msg))
        #     print("=" * 80 + "\n")

        ai_message = ai_msg if isinstance(ai_msg, BaseMessage) else AIMessage(content=str(ai_msg))
        # adds message to history using reducer
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


def handle_create_profile(
    state: ChatState, model: BaseChatModel, project_context: str = "", verbose: bool = False
) -> Dict[str, Any]:
    """Entry point for create-profile intents."""
    return answer_create_profile(state, model, project_context, verbose=verbose)
