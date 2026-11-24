from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.assistant.state import ChatState
from app.nodes.answer.node_create_rule import answer_create_rule
from tests.helpers import RecordingModel


def _invoke(model_result: Any, message: HumanMessage) -> tuple[dict[str, Any], RecordingModel]:
    model = RecordingModel(model_result)
    state = ChatState(messages=[message])
    result = answer_create_rule(state, cast(BaseChatModel, model))
    return result, model


def test_answer_create_rule_includes_system_prompt() -> None:
    message = HumanMessage(content="Hello there, can you explain the Sensei rules?")
    result, model = _invoke(AIMessage(content="Hola"), message)

    assert any(
        isinstance(msg, SystemMessage)
        and isinstance(msg.content, str)
        and msg.content.strip().startswith("You are Senpai, an assistant for the Chatbot Dojo")
        for msg in model.recorded_messages
    )
    assert any(isinstance(msg, HumanMessage) and "Sensei rules" in str(msg.content) for msg in model.recorded_messages)

    ai_msg = result["messages"][0]
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.content == "Hola"


def test_answer_create_rule_wraps_plain_string_results() -> None:
    message = HumanMessage(content="Necesito un perfil de Sensei")
    result, _ = _invoke("Simple string response", message)

    ai_msg = result["messages"][0]
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.content == "Simple string response"


@pytest.mark.parametrize(
    ("exception", "expected_prefix"),
    [
        (TimeoutError("took too long"), "Timeout error invoking the model: took too long"),
        (ValueError("bad input"), "Value error invoking the model: bad input"),
        (RuntimeError("boom"), "Runtime error invoking the model: boom"),
        (Exception("mystery"), "Unexpected error invoking the model: mystery"),
    ],
)
def test_answer_create_rule_handles_exceptions(exception: BaseException, expected_prefix: str) -> None:
    message = HumanMessage(content="Por favor, corrige esta regla de Sensei")
    result, _ = _invoke(exception, message)

    ai_msg = result["messages"][0]
    assert isinstance(ai_msg, AIMessage)
    assert ai_msg.content == expected_prefix
