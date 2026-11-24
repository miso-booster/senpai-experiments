"""Chat state definition for the assistant."""

from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.assistant.intent import IntentLiteral


class ChatState(TypedDict, total=False):
    """Defines the state of the chat.

    'messages' is a list of messages (human/AI/system). The reducer 'add_messages'
    automatically appends/merges them across steps and turns.
    """

    messages: Annotated[List[BaseMessage], add_messages]
    code_blocks: List[Dict[str, Any]]
    validation_results: List[Dict[str, Any]]
    validation_attempts: int
    needs_retry: bool
    retry_action: Literal["fix_blocks", "final_failure", "none"]
    invalid_snippets: List[Dict[str, Any]]
    validation_feedback: Optional[str]
    intent: IntentLiteral
    final_failure_context: Optional[Dict[str, Any]]
    is_codeblock: bool
    should_validate: bool
    validation_decision_reason: Optional[str]
    input: Optional[str]
    last_user_message: Optional[str]
