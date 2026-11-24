"""Node that inspects the latest assistant response for fenced code blocks."""

from typing import Any, Dict

from langchain_core.messages import AIMessage

from app.assistant.codeblocks import extract_code_blocks
from app.assistant.state import ChatState
from app.utils.utilities import normalise_message_content


def detect_code_blocks(state: ChatState) -> Dict[str, Any]:
    """Analyze the last AI message in the chat state and determine whether it contains code blocks.

    This function retrieves all messages from the current `ChatState`, locates the most recent
    AI-generated message, normalizes its content, and checks for the presence of code blocks.
    It returns a dictionary containing a boolean flag under the key `"is_codeblock"` indicating
    whether code blocks were found.

    Args:
        state (ChatState): The current chat state containing message history and other context.

    Returns:
        Dict[str, Any]: A dictionary with a single key:
            - `"is_codeblock"` (bool): True if the last AI message contains code blocks, False otherwise.
    """
    messages = state.get("messages", [])
    last_ai = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
    if last_ai is None:
        return {"is_codeblock": False}
    text = normalise_message_content(last_ai)
    codeblocks = extract_code_blocks(text)
    if codeblocks:
        return {"is_codeblock": True}
    return {"is_codeblock": False}
