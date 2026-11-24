# tests/test_graph.py
from __future__ import annotations

import json
from typing import Any, Dict, List, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver

from app.assistant.graph import create_assistant_graph
from app.assistant.intent import INTENT_SYSTEM_PROMPT


def _get_human_text(messages: List[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            return str(content)
    return ""


def _is_decision_call(messages: List[Any]) -> bool:
    return "DECISION TASK" in _get_human_text(messages)


def _is_fix_call(messages: List[Any]) -> bool:
    return "Please fix only code block" in _get_human_text(messages)


def _is_fallback_failure(messages: List[Any]) -> bool:
    return "Create the final assistant response after the validator failed multiple times." in _get_human_text(messages)


def _is_answer_call(messages: List[Any]) -> bool:
    return not any(
        (
            _is_intent_call(messages),
            _is_decision_call(messages),
            _is_fix_call(messages),
            _is_fallback_failure(messages),
        )
    )


def _is_intent_call(messages: List[Any]) -> bool:
    return any(isinstance(msg, SystemMessage) and msg.content == INTENT_SYSTEM_PROMPT for msg in messages)


def _extract_decision_user_request(text: str) -> str:
    start = text.find("<<<")
    if start == -1:
        return text
    start += 3
    end = text.find(">>>", start)
    if end == -1:
        end = len(text)
    return text[start:end].strip()


def _get_system_prompt(messages: List[Any]) -> str:
    for msg in messages:
        if isinstance(msg, SystemMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            return str(content)
    return ""


class RecordingModel:
    """Mock LLM that records all messages and returns a preset reply."""

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls: List[Any] = []

    def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
        self.calls.append(messages)
        if _is_intent_call(messages):
            request = _extract_decision_user_request(_get_human_text(messages)).lower()
            if "perfil" in request or "profile" in request:
                intent = "create_profile" if "crea" in request or "create" in request else "fix_profile"
            elif "regla" in request or "rule" in request:
                intent = "create_rule" if "crea" in request or "create" in request else "fix_rule"
            else:
                intent = "other"
            return AIMessage(content=json.dumps({"intent": intent}))
        if _is_decision_call(messages):
            return AIMessage(content='{"decision":"TRUE","reason":"default"}')
        return AIMessage(content=self.reply)


def test_graph_compiles_and_streams() -> None:
    # Build a graph with the mock model and memory saver
    model = RecordingModel("ready")
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)

    # stream requires a thread id in config.configurable
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-1"}})
    snapshots = list(
        graph.stream({"messages": [HumanMessage(content="hola, crea una regla sensei")]}, config, stream_mode="values")
    )

    # check that snapshot contains something
    assert snapshots, "graph produced no snapshots"
    last = snapshots[-1]
    # check that last snapshot has messages with the AI reply
    assert "messages" in last and last["messages"], "snapshot missing messages"
    assert isinstance(last["messages"][-1], AIMessage)
    # check that the last message content is the mock reply ("ready")
    assert last["messages"][-1].content == "ready"
    # check that there were actual calls to the model
    assert model.calls, "model was not invoked by the node"


def test_graph_streams_without_checkpointer_and_config() -> None:
    """Graph should stream without persistence requirements when checkpointer is None."""
    model = RecordingModel("no-checkpoint")
    graph = create_assistant_graph(cast(BaseChatModel, model), checkpointer=None)

    snapshots = list(
        graph.stream(
            {"messages": [HumanMessage(content="hola, crea una regla sensei")]},
            None,
            stream_mode="values",
        )
    )

    assert snapshots, "graph produced no snapshots without a checkpointer"
    last = snapshots[-1]
    assert "messages" in last and last["messages"], "snapshot missing messages"
    assert isinstance(last["messages"][-1], AIMessage)
    assert last["messages"][-1].content == "no-checkpoint"
    assert model.calls, "model was not invoked by the node"


def test_graph_selects_context_by_intent() -> None:
    model = RecordingModel("context-ready")
    graph = create_assistant_graph(
        cast(BaseChatModel, model),
        checkpointer=None,
        project_context={
            "profile": "PROFILE_CONTEXT_ONLY",
            "rule": "RULE_CONTEXT_ONLY",
            "connector": "CONNECTOR_CONTEXT_ONLY",
            "explain": "EXPLAIN_CONTEXT_ONLY",
        },
    )

    list(
        graph.stream(
            {"messages": [HumanMessage(content="create a sensei profile")]},
            None,
            stream_mode="values",
        )
    )

    answer_call = next(call for call in model.calls if _is_answer_call(call))
    system_prompt = _get_system_prompt(answer_call)

    assert "PROFILE_CONTEXT_ONLY" in system_prompt
    assert "RULE_CONTEXT_ONLY" not in system_prompt
    assert "CONNECTOR_CONTEXT_ONLY" not in system_prompt


def disabled_test_graph_writes_checkpoint() -> None:
    # Build a graph with the mock model and memory saver
    model = RecordingModel("yo")
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-2"}})

    # run once to create a checkpoint
    list(
        graph.stream(
            {"messages": [HumanMessage(content="hola, ajusta un perfil de Sensei")]}, config, stream_mode="values"
        )
    )

    # now ask for state, it should include messages from checkpoint
    state = graph.get_state(config)
    # state.values is a dict with "messages" after a run
    assert getattr(state, "values", None), "no state values found"
    msgs = state.values.get("messages", [])
    assert msgs and isinstance(msgs[-1], AIMessage) and msgs[-1].content == "yo"


class FixingModel:
    """Model that returns an invalid rule once, then a valid one after feedback."""

    def __init__(self) -> None:
        self.calls: List[List[Any]] = []
        self.answer_calls = 0
        self.fix_calls = 0

    def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
        self.calls.append(messages)
        human_text_raw = _get_human_text(messages)

        if _is_decision_call(messages):
            user_request = _extract_decision_user_request(human_text_raw).lower()
            if "broken rule" in user_request:
                return AIMessage(content='{"decision":"FALSE","reason":"user asked for a broken rule"}')
            return AIMessage(content='{"decision":"TRUE","reason":"user wants a valid rule"}')

        if _is_intent_call(messages):
            request = _extract_decision_user_request(human_text_raw).lower()
            if "profile" in request or "perfil" in request:
                intent = "create_profile" if "crea" in request or "create" in request else "fix_profile"
            elif "rule" in request or "regla" in request:
                intent = "create_rule" if "crea" in request or "create" in request else "fix_rule"
            else:
                intent = "explain"
            return AIMessage(content=json.dumps({"intent": intent, "reason": "test-intent"}))

        if _is_fix_call(messages):
            self.fix_calls += 1
            return AIMessage(
                content=(
                    '```yaml\nname: valid_rule\ndescription: Valid DSL rule\nconversations: 1\noracle: "True"\n```'
                )
            )

        self.answer_calls += 1
        if self.answer_calls == 1:
            return AIMessage(content=("```yaml\nname: missing_fields\ndescription: ''\n```"))
        return AIMessage(
            content=('```yaml\nname: valid_rule\ndescription: Valid DSL rule\nconversations: 1\noracle: "True"\n```')
        )


def disabled_test_graph_retries_until_rule_is_valid() -> None:
    model = FixingModel()
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-retry"}})

    snapshots = list(graph.stream({"messages": [HumanMessage(content="produce rule")]}, config, stream_mode="values"))

    assert len(model.calls) == 4, "expected intent, answer, decision, and fix calls"
    assert sum(1 for call in model.calls if _is_intent_call(call)) == 1
    assert sum(1 for call in model.calls if _is_answer_call(call)) == 1
    assert sum(1 for call in model.calls if _is_decision_call(call)) == 1
    assert sum(1 for call in model.calls if _is_fix_call(call)) == 1
    fix_call = next(call for call in model.calls if _is_fix_call(call))
    assert any(isinstance(msg, HumanMessage) and "Please fix only code block" in msg.content for msg in fix_call), (
        "fix prompt was not sent to the model"
    )

    final_messages = snapshots[-1]["messages"]
    final_ai = next(msg for msg in reversed(final_messages) if isinstance(msg, AIMessage))
    assert "valid_rule" in final_ai.content
    validation_results = snapshots[-1].get("validation_results", [])
    assert validation_results and validation_results[-1]["is_valid"] is True


class StubbornModel:
    """Model that keeps returning an invalid rule snippet."""

    def __init__(self) -> None:
        self.calls: List[List[Any]] = []

    def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
        self.calls.append(messages)
        if _is_intent_call(messages):
            request = _extract_decision_user_request(_get_human_text(messages)).lower()
            intent = "create_profile" if "profile" in request or "perfil" in request else "create_rule"
            return AIMessage(content=json.dumps({"intent": intent, "reason": "test-intent"}))
        if _is_decision_call(messages):
            return AIMessage(content='{"decision":"TRUE","reason":"default"}')
        if _is_fix_call(messages):
            return AIMessage(content=("```yaml\nname: still_broken\ndescription: ''\n```"))
        if _is_fallback_failure(messages):
            return AIMessage(
                content=(
                    "I'm sorry, but I couldn't produce a valid SENSEI RULE after 3 validation attempts. "
                    "Please review the validator feedback:\n- still fail"
                )
            )
        return AIMessage(content=("```yaml\nname: still_broken\ndescription: ''\n```"))


def disabled_test_graph_stops_after_max_validation_attempts() -> None:
    model = StubbornModel()
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-stubborn"}})

    snapshots = list(graph.stream({"messages": [HumanMessage(content="produce rule")]}, config, stream_mode="values"))

    assert len(model.calls) == 6, "expected intent, answer, decision, two fix attempts, and a final failure reply"
    assert sum(1 for call in model.calls if _is_intent_call(call)) == 1
    assert sum(1 for call in model.calls if _is_answer_call(call)) == 1
    assert sum(1 for call in model.calls if _is_decision_call(call)) == 1
    assert sum(1 for call in model.calls if _is_fix_call(call)) == 2
    assert sum(1 for call in model.calls if _is_fallback_failure(call)) == 1

    final_messages = snapshots[-1]["messages"]
    final_ai = next(msg for msg in reversed(final_messages) if isinstance(msg, AIMessage))
    assert isinstance(final_ai.content, str)
    assert final_ai.content.startswith(
        "I'm sorry, but I couldn't produce a valid SENSEI RULE after 3 validation attempts."
    )
    assert snapshots[-1].get("validation_attempts") == 3


class MultiRuleModel:
    """Model that returns a YAML list of rules requiring fixes."""

    def __init__(self) -> None:
        self.calls: List[List[Any]] = []
        self.answer_calls = 0
        self.fix_calls = 0

    def invoke(self, messages: List[Any]) -> AIMessage:  # noqa: ANN401
        self.calls.append(messages)

        if _is_intent_call(messages):
            request = _extract_decision_user_request(_get_human_text(messages)).lower()
            intent = "create_rule" if "rule" in request or "regla" in request else "explain"
            return AIMessage(content=json.dumps({"intent": intent}))

        if _is_decision_call(messages):
            return AIMessage(content='{"decision":"TRUE","reason":"list of rules must be validated"}')

        if _is_fix_call(messages):
            self.fix_calls += 1
            return AIMessage(
                content=(
                    "```yaml\n"
                    "- name: missing_conversations\n"
                    "  description: Falta el campo conversations\n"
                    '  oracle: "True"\n'
                    "- name: segunda_regla\n"
                    "  description: Regla corregida dos\n"
                    "  conversations: 2\n"
                    "  if: condicion\n"
                    "  then: resultado\n"
                    "```"
                )
            )

        self.answer_calls += 1
        if self.answer_calls == 1:
            return AIMessage(
                content=(
                    "```yaml\n"
                    "- name: missing_conversations\n"
                    "  description: Falta el campo conversations\n"
                    '  oracle: "True"\n'
                    "- name: well_defined_rule\n"
                    "  description: Regla casi correcta\n"
                    "  conversations: 1\n"
                    '  oracle: "True"\n'
                    "```"
                )
            )
        return AIMessage(
            content=(
                "```yaml\n"
                "- name: primera_regla\n"
                "  description: Regla corregida uno\n"
                "  conversations: 1\n"
                '  oracle: "True"\n'
                "- name: segunda_regla\n"
                "  description: Regla corregida dos\n"
                "  conversations: 2\n"
                "  if: condicion\n"
                "  then: resultado\n"
                "```"
            )
        )


def disabled_test_graph_rejects_multiple_rules_in_single_block() -> None:
    model = MultiRuleModel()
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-multi"}})

    snapshots = list(graph.stream({"messages": [HumanMessage(content="multi rules")]}, config, stream_mode="values"))

    assert len(model.calls) == 6, "validator should retry until giving up"
    assert sum(1 for call in model.calls if _is_intent_call(call)) == 1
    assert sum(1 for call in model.calls if _is_answer_call(call)) == 1
    assert sum(1 for call in model.calls if _is_decision_call(call)) == 1
    assert sum(1 for call in model.calls if _is_fix_call(call)) == 2
    assert sum(1 for call in model.calls if _is_fallback_failure(call)) == 1

    validation_results = snapshots[-1].get("validation_results", [])
    assert validation_results, "expected validation results"
    final_result = validation_results[-1]
    assert final_result["is_valid"] is False
    errors = cast(list[str], final_result.get("errors") or [])
    assert any("exactly one" in err.lower() for err in errors)

    failure_messages = [msg for msg in snapshots[-1].get("messages", []) if isinstance(msg, AIMessage)]
    assert failure_messages
    assert any("exactly one" in cast(str, msg.content).lower() for msg in failure_messages)


def disabled_test_graph_skips_validation_when_user_requests_broken_rule() -> None:
    model = FixingModel()
    saver = MemorySaver()
    graph = create_assistant_graph(cast(BaseChatModel, model), saver)
    config = cast(RunnableConfig, {"configurable": {"thread_id": "t-skip"}})

    first_snapshots = list(
        graph.stream(
            {"messages": [HumanMessage(content="Please share a broken rule without validating it")]},
            config,
            stream_mode="values",
        )
    )

    assert len(model.calls) == 3, "intent, answer, and decision calls should occur even when skipping validation"
    assert sum(1 for call in model.calls if _is_intent_call(call)) == 1
    assert sum(1 for call in model.calls if _is_answer_call(call)) == 1
    assert sum(1 for call in model.calls if _is_decision_call(call)) == 1
    assert sum(1 for call in model.calls if _is_fix_call(call)) == 0
    final_first = first_snapshots[-1]
    assert final_first.get("should_validate") is False
    assert final_first.get("validation_results") == []
    assert final_first.get("validation_attempts") == 0
    assert final_first.get("retry_action") == "none"

    second_snapshots = list(
        graph.stream(
            {"messages": [HumanMessage(content="Now fix that rule so it is valid")]},
            config,
            stream_mode="values",
        )
    )

    assert len(model.calls) == 6, "second turn should add another intent, answer, and decision call"
    second_run_calls = model.calls[3:]
    assert sum(1 for call in second_run_calls if _is_intent_call(call)) == 1
    assert sum(1 for call in second_run_calls if _is_answer_call(call)) == 1
    assert sum(1 for call in second_run_calls if _is_decision_call(call)) == 1
    assert sum(1 for call in second_run_calls if _is_fix_call(call)) == 0
    final_second = second_snapshots[-1]
    assert final_second.get("should_validate") is True
    validation_results = cast(List[Dict[str, Any]], final_second.get("validation_results") or [])
    assert validation_results, "validation results should be present when validation runs"
    assert validation_results[-1]["is_valid"] is True
