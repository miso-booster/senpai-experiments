"""Render the closing assistant response after repeated validation failures."""

import logging
from typing import Any, Dict, List

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.assistant.state import ChatState
from app.nodes.node_intent_routing import extract_user_text
from app.utils.utilities import normalise_message_content

log = logging.getLogger(__name__)


_FINAL_FAILURE_SYSTEM_PROMPT = (
    "You are an assistant that must close a conversation after repeated validation failures. "
    "Write a concise, empathetic plain-text response (no code blocks) that:\n"
    "- Apologises for the failure.\n"
    "- Mentions the number of validation attempts.\n"
    "- References whether the user wanted a new item or a fix.\n"
    "- Encourages the user to adjust instructions or use the provided feedback.\n"
    "Keep the tone helpful and actionable."
)


def render_validation_failure_response(  # noqa: ANN401
    state: ChatState,
    model: BaseChatModel,
    *,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Generate a final assistant message after exhausting validation retries."""
    failure_context = state.get("final_failure_context") or {}
    feedback = failure_context.get("feedback") or state.get("validation_feedback") or ""
    attempts = failure_context.get("attempts") or state.get("validation_attempts") or 0
    intent = failure_context.get("intent") or state.get("intent") or "other"

    user_text = extract_user_text(state)
    feedback_text = feedback.strip() or "No validator feedback was captured."

    guidance_lines = [
        f"- User intent: {intent}",
        f"- Validation attempts: {attempts}",
        "- Mention that validation was attempted multiple times.",
        "- Encourage the user to adjust the instructions or apply the feedback.",
    ]

    human_prompt = (
        "Create the final assistant response after the validator failed multiple times.\n"
        f"User request:\n{user_text or '(empty)'}\n\n"
        "Context:\n" + "\n".join(guidance_lines) + "\n\nValidation feedback:\n"
        f"{feedback_text}\n\n"
        "Reply with a single plain-text paragraph or two short paragraphs. Do not include code blocks."
    )

    if verbose:
        print("\n" + "=" * 80)
        print("FINAL FAILURE PROMPT:")
        print("=" * 80)
        print(human_prompt)
        print("-" * 80)
        print(f"[final-failure] intent={intent} attempts={attempts}")
        print("=" * 80 + "\n")

    messages: List[SystemMessage | HumanMessage] = [
        SystemMessage(content=_FINAL_FAILURE_SYSTEM_PROMPT),
        HumanMessage(content=human_prompt),
    ]

    try:
        response = model.invoke(messages)
    except Exception:
        log.exception("Failed to generate final validation failure response via LLM.")
        fallback = (
            "I'm sorry, but I couldn't complete the request after several validation attempts. "
            "Please review the feedback and adjust your instructions before trying again."
        )
        text_content = fallback
    else:
        text_content = normalise_message_content(response).strip()

    if feedback_text and feedback_text.lower() not in text_content.lower():
        text_content = f"{text_content}\n\nValidator feedback:\n{feedback_text}"

    result_payload: Dict[str, Any] = {
        "messages": [AIMessage(content=text_content)],
        "retry_action": "none",
        "needs_retry": False,
        "final_failure_context": None,
    }
    return result_payload
