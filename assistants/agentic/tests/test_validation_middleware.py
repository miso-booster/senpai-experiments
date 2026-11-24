from __future__ import annotations

import logging
from textwrap import dedent
from typing import Any, List, cast

from langchain.agents import AgentState
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolCall
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import RunnableConfig
from pydantic import ConfigDict, ValidationError
from senpai_validators import ValidationResult

import app.assistant.validation_middleware as vm
from app.assistant.validation import MAX_VALIDATION_ATTEMPTS
from app.assistant.validation_middleware import (
    _VALIDATION_ATTEMPTS_STATE_KEY,
    MessageValidationMiddleware,
    ToolCallValidationMiddleware,
    ValidationDecisionMiddleware,
)


class DummyModel(BaseChatModel):
    """Minimal chat model stub; never actually called in these tests."""

    model_config = ConfigDict(extra="allow")

    @property
    def _llm_type(self) -> str:
        return "dummy"

    def _generate(  # pragma: no cover
        self,
        messages: List[Any],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **_: Any,
    ) -> Any:
        del messages, stop, run_manager
        raise NotImplementedError("Dummy model should not be invoked in these tests.")

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        del tools, kwargs
        return self


def _make_state(user_text: str, assistant_text: str) -> AgentState[Any]:
    """Helper to build a lightweight agent state for middleware tests."""
    return cast(
        AgentState[Any],
        {"messages": [HumanMessage(content=user_text), AIMessage(content=assistant_text)]},
    )


def test_validator_skips_when_no_yaml(monkeypatch: Any, caplog: Any) -> None:
    mw = MessageValidationMiddleware(model=DummyModel())
    state: AgentState[Any] = _make_state("hi", "plain text reply")

    with caplog.at_level(logging.INFO, logger=vm.logger.name):
        result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final == "plain text reply"
    assert "[message_validation] skipped (no YAML code blocks found)." in caplog.text


def test_validation_decision_skips_when_no_yaml_or_save(monkeypatch: Any) -> None:
    """Decision middleware should skip classification when nothing to validate."""
    mw = ValidationDecisionMiddleware(model=DummyModel())

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("should not be called")

    monkeypatch.setattr(mw._model, "with_structured_output", boom)

    state = _make_state("hi", "plain text reply")
    result = mw.after_model(state, cast(Any, None))

    assert result is None
    assistant = cast(AIMessage, state["messages"][-1])
    assert assistant.additional_kwargs.get(vm._VALIDATION_DECISION_STATE_KEY) is False


def test_validation_decision_sets_cache_on_yaml(monkeypatch: Any) -> None:
    """Decision middleware should cache the classification result on message metadata."""
    mw = ValidationDecisionMiddleware(model=DummyModel())

    class Decision:
        requires_validation = True

    class FakeStructured:
        def __init__(self, decision: Any) -> None:
            self._decision = decision

        def invoke(self, _prompt: Any) -> Any:
            return self._decision

    monkeypatch.setattr(mw._model, "with_structured_output", lambda *_: FakeStructured(Decision()))

    state = _make_state("please generate", "```yaml\nfoo: bar\n```")
    result = mw.after_model(state, cast(Any, None))

    assert result is None
    assistant = cast(AIMessage, state["messages"][-1])
    assert assistant.additional_kwargs.get(vm._VALIDATION_DECISION_STATE_KEY) is True


def test_cached_requires_validation_uses_message(monkeypatch: Any) -> None:
    """Message cache should be used to skip validation."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda *_: (_ for _ in ()).throw(RuntimeError("should not validate")),
    )
    monkeypatch.setattr(
        mw,
        "_classify_requires_validation",
        lambda *_: (_ for _ in ()).throw(RuntimeError("should not classify")),
    )

    state = _make_state("please generate", "```yaml\nfoo: bar\n```")
    assistant = cast(AIMessage, state["messages"][-1])
    assistant.additional_kwargs[vm._VALIDATION_DECISION_STATE_KEY] = False

    result = mw.after_model(state, cast(Any, None))

    assert result is None


def test_validator_skips_when_classifier_says_no(monkeypatch: Any, caplog: Any) -> None:
    mw = MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: False)
    state = _make_state("please generate", "```yaml\nfoo: bar\n```")

    with caplog.at_level(logging.INFO, logger=vm.logger.name):
        result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final == "```yaml\nfoo: bar\n```"
    assert "[message_validation] skipped (classifier decided not to validate)." in caplog.text


def test_validator_passes_and_logs_status(monkeypatch: Any, caplog: Any) -> None:
    mw = MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, _attempts=0: {"invalid_snippets": [], "validation_feedback": None},
    )
    state = _make_state("please generate", "```yaml\nfoo: bar\n```")

    with caplog.at_level(logging.INFO, logger=vm.logger.name):
        result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final == "```yaml\nfoo: bar\n```"
    assert "[message_validation] passed (1 block)." in caplog.text


def test_validator_retries_and_regenerates_on_failure(monkeypatch: Any, caplog: Any) -> None:
    """When validation fails, the middleware should ask the agent to retry with feedback and keep the regenerated reply."""
    mw = MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, attempts_so_far=0: {"invalid_snippets": [{"block_index": 0}], "validation_feedback": "broken"}
        if attempts_so_far == 0
        else {"invalid_snippets": [], "validation_feedback": ""},
    )
    monkeypatch.setattr(
        mw._model,
        "invoke",
        lambda msgs: AIMessage(content="Thanks for your patience.\n```yaml\nfixed: true\n```"),
    )

    state = _make_state("fix please", "```yaml\nfoo: {{missing}}\n```")

    with caplog.at_level(logging.WARNING, logger=vm.logger.name):
        result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    assert isinstance(state["messages"][-1], AIMessage)
    assert cast(str, state["messages"][-1].content) == "Thanks for your patience.\n```yaml\nfixed: true\n```"
    assert len(state["messages"]) == 2  # no extra human/tool messages persisted
    assert "[message_validation] failed (see feedback)" in caplog.text


def test_validator_skips_when_no_messages() -> None:
    mw = MessageValidationMiddleware(model=DummyModel())
    state = cast(AgentState[Any], {"messages": []})

    result = mw.after_model(state, cast(Any, None))

    assert result is None


def test_validator_skips_when_no_assistant_message() -> None:
    mw = MessageValidationMiddleware(model=DummyModel())
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="hello")]})

    result = mw.after_model(state, cast(Any, None))

    assert result is None


def test_validator_skip_no_yaml_resets_attempts() -> None:
    """If prior attempts exist and no YAML is present, reset the attempt counter."""
    mw = MessageValidationMiddleware(model=DummyModel())
    state = cast(
        AgentState[Any],
        {
            "messages": [HumanMessage(content="hi"), AIMessage(content="plain text reply")],
            _VALIDATION_ATTEMPTS_STATE_KEY: 2,
        },
    )

    result = mw.after_model(state, cast(Any, None))

    assert result == {_VALIDATION_ATTEMPTS_STATE_KEY: 0}


def test_validator_skip_classifier_false_resets_attempts(monkeypatch: Any) -> None:
    """If classifier opts out and attempts existed, reset the counter."""
    mw = MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: False)
    state = cast(
        AgentState[Any],
        {
            "messages": [HumanMessage(content="please generate"), AIMessage(content="```yaml\nfoo: bar\n```")],
            _VALIDATION_ATTEMPTS_STATE_KEY: 2,
        },
    )

    result = mw.after_model(state, cast(Any, None))

    assert result == {_VALIDATION_ATTEMPTS_STATE_KEY: 0}


def test_validator_skips_when_no_yaml_blocks() -> None:
    """The reply should remain unchanged when no YAML blocks are present."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="hi"), AIMessage(content="plain text reply")]})

    result = mw.after_model(state, cast(Any, None))

    # No state update when nothing changes; content should remain identical.
    assert result is None


def test_validator_passes_no_verbose(monkeypatch: Any) -> None:
    """If the validation passes, the reply should remain unchanged"""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, _attempts=0: {"invalid_snippets": [], "validation_feedback": None},
    )
    state = cast(
        AgentState[Any], {"messages": [HumanMessage(content="hi"), AIMessage(content="```yaml\nfoo: bar\n```")]}
    )

    result = mw.after_model(state, cast(Any, None))

    # No state update when the validation passes
    assert result is None


def test_validator_accepts_connector_block(monkeypatch: Any) -> None:
    """Connector YAML should validate successfully and leave the message untouched."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    connector_yaml = dedent(
        """
        base_url: https://api.example.com
        send_message:
          path: /chat
          payload_template:
            message: "{user_msg}"
        response_path: data.message.text
        """
    ).strip()
    state = _make_state("please generate connector", f"```yaml\n{connector_yaml}\n```")

    result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final.strip() == f"```yaml\n{connector_yaml}\n```"


def test_validator_accepts_rule_block(monkeypatch: Any) -> None:
    """Rule YAML should validate successfully and leave the message untouched."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    rule_yaml = dedent(
        """
        name: division
        description: Checks the operation
        active: False
        conversations: 1
        when: operation[0]=='dividing'
        oracle: abs(number1[0]/number2[0] - result) < 1e-03
        yields: |
          f"Wrong result for dividing {number1} and {number2}: expected {number1[0]/number2[0]} but got {result}"
        """
    ).strip()
    state = _make_state("please generate rule", f"```yaml\n{rule_yaml}\n```")

    result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final.strip() == f"```yaml\n{rule_yaml}\n```"


def test_validator_accepts_profile_block(monkeypatch: Any) -> None:
    """Profile YAML should validate successfully and leave the message untouched."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, _attempts=0: {"invalid_snippets": [], "validation_feedback": None},
    )
    profile_yaml = dedent(
        """
        test_name: appointment
        llm:
          temperature: 0.0
          model: gpt-4o-mini
        user:
          language: English
          role:
            you have to act as a user talking to a virtual assistant of a bike shop
        chatbot:
          is_starter: True
          fallback: I'm sorry it's a little loud in my shop, can you say that again?
        """
    ).strip()
    state = _make_state("please generate profile", f"```yaml\n{profile_yaml}\n```")

    result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final.strip() == f"```yaml\n{profile_yaml}\n```"


def test_validator_runs_end_to_end_logs_pass(monkeypatch: Any, caplog: Any) -> None:
    """Ensure classifier + connector validator run end-to-end and surface pass status."""

    class StructuredModel(DummyModel):
        """Model stub that forces requires_validation=True via structured output."""

        def with_structured_output(self, *_: Any, **__: Any) -> Any:
            class Decision:
                requires_validation = True

            class Wrapper:
                def invoke(self, *__: Any, **___: Any) -> Any:
                    return Decision()

            return Wrapper()

    mw = vm.MessageValidationMiddleware(model=StructuredModel())
    monkeypatch.setattr(
        vm,
        "validate_code_blocks",
        lambda _blocks, _attempts=0: {"invalid_snippets": [], "validation_feedback": None},
    )
    connector_yaml = dedent(
        """
        base_url: https://api.example.com
        send_message:
          path: /chat
          payload_template:
            message: "{user_msg}"
        response_path: data.message.text
        """
    ).strip()
    state = _make_state("please create a connector", f"```yaml\n{connector_yaml}\n```")

    with caplog.at_level(logging.INFO, logger=vm.logger.name):
        result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final.strip() == f"```yaml\n{connector_yaml}\n```"
    assert "[message_validation] passed (1 block)." in caplog.text


def test_classifier_false_with_yaml_no_verbose(monkeypatch: Any) -> None:
    """When we have a YAML block but the classifier says no validation is required, reply should be unchanged."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: False)
    state = _make_state("please generate", "```yaml\nfoo: bar\n```")

    result = mw.after_model(state, cast(Any, None))

    assert result is None
    final = cast(str, state["messages"][-1].content)
    assert final == "```yaml\nfoo: bar\n```"


def test_validator_retries_on_failure_and_succeeds(monkeypatch: Any) -> None:
    """When validation fails, we request a retry with feedback and track attempts."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, attempts_so_far=0: {"invalid_snippets": [{"block_index": 0}], "validation_feedback": "broken"}
        if attempts_so_far == 0
        else {"invalid_snippets": [], "validation_feedback": ""},
    )
    monkeypatch.setattr(
        mw._model,
        "invoke",
        lambda msgs: AIMessage(content="Here's the fix.\n```yaml\nfixed: true\n```"),
    )
    state = _make_state("please fix", "```yaml\nfoo: {{missing}}\n```")

    result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    assert isinstance(state["messages"][-1], AIMessage)
    assert "fixed: true" in cast(str, state["messages"][-1].content)
    assert len(state["messages"]) == 2


def test_validator_handles_repair_invoke_failure(monkeypatch: Any) -> None:
    """If the repair call fails, return the original conversation without retry prompts."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, attempts_so_far=0: {"invalid_snippets": [{"block_index": 0}], "validation_feedback": "broken"},
    )

    def _raise_invoke(_: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(mw._model, "invoke", _raise_invoke)

    state = _make_state("please fix", "```yaml\nfoo: {{missing}}\n```")

    result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    assert len(result["messages"]) == 2
    assert cast(str, state["messages"][-1].content) == "```yaml\nfoo: {{missing}}\n```"


def test_validator_stops_retrying_when_repair_returns_no_yaml(monkeypatch: Any, caplog: Any) -> None:
    """If a retry becomes a normal follow-up message, do not keep validating stale YAML."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    validate_calls = {"count": 0}

    def _always_invalid(_blocks: Any, attempts_so_far: int = 0) -> dict[str, Any]:
        validate_calls["count"] += 1
        return {"invalid_snippets": [{"block_index": 0}], "validation_feedback": f"broken-{attempts_so_far}"}

    monkeypatch.setattr(mw, "_validate_code_blocks", _always_invalid)
    monkeypatch.setattr(
        mw._model,
        "invoke",
        lambda _msgs: AIMessage(content="Could you share the expected oracle format for the last rule?"),
    )

    state = _make_state("please fix", "```yaml\nfoo: {{missing}}\n```")

    with caplog.at_level(logging.INFO, logger=vm.logger.name):
        result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    assert cast(str, state["messages"][-1].content) == "Could you share the expected oracle format for the last rule?"
    assert validate_calls["count"] == 1
    assert "repair produced no YAML code blocks" in caplog.text


def test_validator_skips_when_assistant_content_not_str() -> None:
    """Early exit when the assistant message content is not a string."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    # AIMessage content accepts list[str|dict]; using list triggers the non-str branch without raising.
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="hi"), AIMessage(content=["foo"])]})

    result = mw.after_model(state, cast(Any, None))

    assert result is None


def test_classify_returns_true_on_structured_output(monkeypatch: Any) -> None:
    """If the LLM with structured output indicates validation is needed, return True."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())

    class Decision:  # mimic pydantic model instance
        requires_validation = True

    class FakeStructured:
        def __init__(self, decision: Any) -> None:
            self._decision = decision

        def invoke(self, _prompt: Any) -> Any:
            return self._decision

    monkeypatch.setattr(mw._model, "with_structured_output", lambda *_: FakeStructured(Decision()))

    assert mw._classify_requires_validation("u", "a") is True


def test_classify_handles_validation_error(monkeypatch: Any) -> None:
    """ValidationError should be treated as a negative classification."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())

    def raise_validation_error(*_: Any, **__: Any) -> Any:
        raise ValidationError.from_exception_data(
            "Decision",
            [{"loc": ("requires_validation",), "input": None, "type": "value_error"}],
        )

    monkeypatch.setattr(mw._model, "with_structured_output", raise_validation_error)

    assert mw._classify_requires_validation("u", "a") is False


def test_classify_handles_generic_exception(monkeypatch: Any) -> None:
    """Any other exception should also be treated as negative classification."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(
        mw._model,
        "with_structured_output",
        lambda *_: cast(
            Any,
            type(
                "Raiser",
                (),
                {
                    "invoke": lambda *__, **___: (_ for _ in ()).throw(RuntimeError("boom")),
                },
            )(),
        ),
    )

    assert mw._classify_requires_validation("u", "a") is False


def test_classify_handles_validation_error_from_invoke(monkeypatch: Any) -> None:
    """If invoke raises ValidationError, classifier should return False."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())

    class Raiser:
        def invoke(self, *_: Any) -> Any:
            raise ValidationError.from_exception_data(
                "Decision",
                [{"loc": ("requires_validation",), "input": None, "type": "value_error"}],
            )

    monkeypatch.setattr(mw._model, "with_structured_output", lambda *_: Raiser())

    assert mw._classify_requires_validation("u", "a") is False


def test_build_failure_message_uses_model_text(monkeypatch: Any) -> None:
    """_build_failure_message should surface the model-produced text when available."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())

    class Resp:
        content = "custom fallback"

    monkeypatch.setattr(mw._model, "invoke", lambda *_: Resp())

    msg = mw._build_failure_message("user msg", "assistant reply", "feedback")
    assert msg == "custom fallback"


def test_validation_pass_resets_attempts(monkeypatch: Any) -> None:
    """When validation passes after previous failures, reset the attempt counter."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, _attempts=0: {"invalid_snippets": [], "validation_feedback": None},
    )
    state = _make_state("fix it", "```yaml\nfoo: ok\n```")
    state["_validator_attempts"] = 2  # type: ignore[typeddict-unknown-key]

    result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    final = cast(str, state["messages"][-1].content)
    assert final.strip() == "```yaml\nfoo: ok\n```"


def test_validation_hits_max_attempts_and_falls_back(monkeypatch: Any) -> None:
    """After exceeding max attempts, replace the assistant reply with a friendly fallback."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, _attempts=0: {"invalid_snippets": [{"block_index": 0}], "validation_feedback": "still bad"},
    )
    monkeypatch.setattr(mw, "_build_failure_message", lambda *_: "fallback message")
    state = _make_state("fix please", "```yaml\nfoo: bad\n```")
    state["_validator_attempts"] = MAX_VALIDATION_ATTEMPTS - 1  # type: ignore[typeddict-unknown-key]

    result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    final = cast(str, state["messages"][-1].content)
    assert final == "fallback message"


def test_validation_attempts_increment_once_per_loop(monkeypatch: Any) -> None:
    """Ensure attempts are passed as 0,1,2 before fallback when MAX is 3."""
    mw = vm.MessageValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    call_attempts: list[int] = []

    def fake_validate(_blocks: list[dict[str, Any]], attempts_so_far: int = 0) -> dict[str, Any]:
        call_attempts.append(attempts_so_far)
        return {"invalid_snippets": [{"block_index": 0}], "validation_feedback": "bad"}

    monkeypatch.setattr(mw, "_validate_code_blocks", fake_validate)
    monkeypatch.setattr(mw, "_build_failure_message", lambda *_: "fallback message")
    monkeypatch.setattr(mw._model, "invoke", lambda *_: AIMessage(content="meta\n```yaml\nstill bad\n```"))

    state = _make_state("fix please", "```yaml\nfoo: bad\n```")

    result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    assert call_attempts == [0, 1, 2]


def test_validator_retry_injects_reference_docs(monkeypatch: Any) -> None:
    """Retry path should inject reference docs for the repair model."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    class CapturingModel(DummyModel):
        def __init__(self) -> None:
            super().__init__()
            self.last_input: object | None = None

        def invoke(  # type: ignore[override]
            self,
            input: PromptValue | str | list[BaseMessage | list[str] | tuple[str, str] | str | dict[str, Any]],
            config: RunnableConfig | None = None,
            *,
            stop: list[str] | None = None,
            **kwargs: Any,
        ) -> AIMessage:
            del config, stop, kwargs
            self.last_input = input
            return AIMessage(content="```yaml\nfixed: true\n```")

    model = CapturingModel()
    mw = vm.MessageValidationMiddleware(model=model)
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    monkeypatch.setattr(
        mw,
        "_validate_code_blocks",
        lambda _blocks, attempts_so_far=0: {"invalid_snippets": [{"block_index": 0}], "validation_feedback": "broken"}
        if attempts_so_far == 0
        else {"invalid_snippets": [], "validation_feedback": ""},
    )

    state = _make_state(
        "please fix",
        "```yaml\nname: check_opening_hours\ndescription: test\nconversations: 1\nif: true\nthen: pass\n```",
    )
    result = mw.after_model(state, cast(Any, None))

    assert result == {"messages": state["messages"], "_validator_attempts": 0}
    assert "fixed: true" in cast(str, state["messages"][-1].content)
    assert isinstance(model.last_input, list)
    assert any(
        isinstance(msg, SystemMessage) and "Reference documentation" in cast(str, msg.content)
        for msg in model.last_input
    )


def test_after_model_blocks_invalid_profile_tool_call(monkeypatch: Any) -> None:
    mw = ToolCallValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    spec = mw._tool_validators["save_profile"]
    monkeypatch.setitem(
        mw._tool_validators,
        "save_profile",
        vm._ToolValidationSpec(
            label=spec.label,
            validator=lambda _content: ValidationResult(is_valid=False, errors=["missing user"], warnings=[]),
            doc_type=spec.doc_type,
        ),
    )

    tool_call = cast(ToolCall, {"id": "tool-3", "name": "save_profile", "args": {"content": "bad: true"}})
    ai_message = AIMessage(content="", tool_calls=[tool_call])
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="hi"), ai_message]})

    result = mw.after_model(state, cast(Any, None))

    assert isinstance(result, dict)
    assert result.get("jump_to") == "model"
    messages = result.get("messages", [])
    assert len(messages) == 2
    assert isinstance(messages[0], AIMessage)
    assert isinstance(messages[1], HumanMessage)
    assert ai_message.tool_calls == []
    assert "Profile validation failed." in cast(str, messages[1].content)
    assert "get_docs" in cast(str, messages[1].content)


def test_after_model_retries_when_invalid_profile_with_other_tools(monkeypatch: Any) -> None:
    mw = ToolCallValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(mw, "_classify_requires_validation", lambda *_: True)
    spec = mw._tool_validators["save_profile"]
    monkeypatch.setitem(
        mw._tool_validators,
        "save_profile",
        vm._ToolValidationSpec(
            label=spec.label,
            validator=lambda _content: ValidationResult(is_valid=False, errors=["missing user"], warnings=[]),
            doc_type=spec.doc_type,
        ),
    )

    tool_calls = [
        cast(ToolCall, {"id": "tool-1", "name": "get_docs", "args": {"doc_types": ["profiles"]}}),
        cast(ToolCall, {"id": "tool-2", "name": "save_profile", "args": {"content": "bad: true"}}),
    ]
    ai_message = AIMessage(content="", tool_calls=tool_calls)
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="hi"), ai_message]})

    result = mw.after_model(state, cast(Any, None))

    assert isinstance(result, dict)
    assert result.get("jump_to") == "model"
    messages = result.get("messages", [])
    assert len(messages) == 2
    assert isinstance(messages[0], AIMessage)
    assert isinstance(messages[1], HumanMessage)
    assert len(ai_message.tool_calls) == 1
    assert ai_message.tool_calls[0].get("name") == "get_docs"
    assert "Profile validation failed." in cast(str, messages[1].content)


def test_tool_validation_skips_when_classifier_cache_false(monkeypatch: Any) -> None:
    """Tool validation should skip when cached decision says no validation."""
    mw = ToolCallValidationMiddleware(model=DummyModel())
    monkeypatch.setattr(
        mw,
        "_classify_requires_validation",
        lambda *_: (_ for _ in ()).throw(RuntimeError("should not classify")),
    )
    monkeypatch.setattr(
        mw,
        "_filter_invalid_tool_calls",
        lambda *_: (_ for _ in ()).throw(RuntimeError("should not validate tools")),
    )

    tool_call = cast(ToolCall, {"id": "tool-1", "name": "save_profile", "args": {"content": "bad: true"}})
    ai_message = AIMessage(content="", tool_calls=[tool_call])
    ai_message.additional_kwargs[vm._VALIDATION_DECISION_STATE_KEY] = False
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="hi"), ai_message]})

    result = mw.after_model(state, cast(Any, None))

    assert result is None
    assert len(ai_message.tool_calls) == 1
    assert ai_message.tool_calls[0].get("name") == "save_profile"
    assert ai_message.tool_calls[0].get("id") == "tool-1"
    assert ai_message.tool_calls[0].get("args") == {"content": "bad: true"}
