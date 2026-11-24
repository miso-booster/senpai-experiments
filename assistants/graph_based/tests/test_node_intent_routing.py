"""Tests for the intent routing node that handles LLM-driven classification."""

from __future__ import annotations

import json
from typing import Any, List, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.assistant.intent import INTENT_SYSTEM_PROMPT
from app.assistant.state import ChatState
from app.nodes.node_intent_routing import classify_request, extract_user_text


class RecordingIntentModel:
    """Test double that records prompts and returns static JSON."""

    def __init__(self, payload: dict[str, Any], *, raise_on_invoke: bool = False) -> None:
        self.response = json.dumps(payload)
        self.raise_on_invoke = raise_on_invoke
        self.calls: List[List[Any]] = []

    def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
        self.calls.append(list(messages))
        if self.raise_on_invoke:
            raise RuntimeError("llm boom")
        return AIMessage(content=self.response)


def test_classify_request_uses_llm_intent() -> None:
    model = RecordingIntentModel({"intent": "create_rule", "reason": "user asked"})
    state = ChatState(messages=[HumanMessage(content="Please create a Sensei rule about refunds.")])

    result = classify_request(state, cast(BaseChatModel, model))

    assert result["intent"] == "create_rule"
    assert result["last_user_message"] == "Please create a Sensei rule about refunds."
    assert any(isinstance(msg, SystemMessage) and msg.content == INTENT_SYSTEM_PROMPT for msg in model.calls[0])


def test_classify_request_assigns_profiles_topic() -> None:
    model = RecordingIntentModel({"intent": "fix_profile"})
    state = ChatState(messages=[HumanMessage(content="Please fix this profile")])

    result = classify_request(state, cast(BaseChatModel, model))

    assert result["intent"] == "fix_profile"


def test_classify_request_assigns_connector_topic() -> None:
    model = RecordingIntentModel({"intent": "create_connector"})
    state = ChatState(messages=[HumanMessage(content="Create a connector yaml for my chatbot API")])

    result = classify_request(state, cast(BaseChatModel, model))

    assert result["intent"] == "create_connector"


def test_classify_request_handles_unparsed_response() -> None:
    class GarbageModel:
        def __init__(self) -> None:
            self.calls: List[List[Any]] = []

        def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
            self.calls.append(list(messages))
            return AIMessage(content="not json")

    model = GarbageModel()
    state = ChatState(messages=[HumanMessage(content="Fix this Sensei profile")])

    result = classify_request(state, cast(BaseChatModel, model))

    assert result["intent"] == "other"
    assert result["messages"][0].content.startswith("I can only help")


def test_classify_request_handles_llm_failure() -> None:
    model = RecordingIntentModel({}, raise_on_invoke=True)
    state = ChatState(messages=[HumanMessage(content="Explain the rule format")])

    result = classify_request(state, cast(BaseChatModel, model))

    assert result["intent"] == "other"
    assert result["messages"][0].content.startswith("I can only help")


def test_classify_request_skips_llm_for_empty_input() -> None:
    model = RecordingIntentModel({"intent": "explain"})
    state = ChatState()

    result = classify_request(state, cast(BaseChatModel, model))

    assert result["intent"] == "other"
    assert result["messages"][0].content.startswith("I can only help")
    assert model.calls == []


def test_extract_user_text_supports_structured_content() -> None:
    state = ChatState(messages=[HumanMessage(content=[{"text": "Hola"}, "amigo"])])
    result = extract_user_text(state)
    assert result == "Hola amigo"


def test_extract_user_text_fallback_to_input_key() -> None:
    state = ChatState(input="fallback message")
    result = extract_user_text(state)
    assert result == "fallback message"
