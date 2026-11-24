from __future__ import annotations

from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.assistant.state import ChatState
from app.nodes.action.node_decide_validation_needed import decide_validation_needed
from tests.helpers import RecordingModel


def test_decide_validation_defaults_to_true() -> None:
    model = RecordingModel(AIMessage(content='{"decision":"TRUE","reason":"user requests valid rule"}'))
    state = ChatState(messages=[HumanMessage(content="Please create a valid Sensei rule.")], intent="create_rule")

    result = decide_validation_needed(state, cast(BaseChatModel, model))

    assert result["should_validate"] is True
    assert result.get("validation_decision_reason") == "user requests valid rule"
    assert any(
        isinstance(msg, SystemMessage) and "classifier" in str(msg.content).lower() for msg in model.recorded_messages
    )
    assert any(isinstance(msg, HumanMessage) and "DECISION TASK" in str(msg.content) for msg in model.recorded_messages)


def test_decide_validation_detects_skip_request() -> None:
    model = RecordingModel(AIMessage(content='{"decision":"FALSE","reason":"user explicitly wants a broken rule"}'))
    state = ChatState(
        messages=[HumanMessage(content="Show me a broken rule without validating it.")],
        intent="create_rule",
    )

    result = decide_validation_needed(state, cast(BaseChatModel, model))

    assert result["should_validate"] is False
    assert result.get("validation_decision_reason") == "user explicitly wants a broken rule"
    assert result["validation_results"] == []
    assert result["validation_attempts"] == 0
    assert result["retry_action"] == "none"
    assert result["invalid_snippets"] == []
    assert result["code_blocks"] == []
