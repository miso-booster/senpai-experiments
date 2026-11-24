from __future__ import annotations

from typing import Any, cast

from langchain.agents import AgentState
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult
from pydantic import ConfigDict

from app.assistant.scope_guardrail_middleware import ScopeGuardrailMiddleware


class DummyModel(BaseChatModel):
    """Minimal chat model stub; middleware internals are monkeypatched in tests."""

    model_config = ConfigDict(extra="allow")

    @property
    def _llm_type(self) -> str:
        return "dummy"

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **_: Any,
    ) -> ChatResult:  # pragma: no cover
        del messages, stop, run_manager
        raise NotImplementedError

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        del tools, kwargs
        return self


def test_scope_guardrail_skips_when_no_messages() -> None:
    mw = ScopeGuardrailMiddleware(model=cast(BaseChatModel, DummyModel()))
    state = cast(AgentState[Any], {"messages": []})

    result = mw.before_agent(state, cast(Any, None))

    assert result is None


def test_scope_guardrail_skips_on_resume_when_last_message_is_not_human() -> None:
    mw = ScopeGuardrailMiddleware(model=cast(BaseChatModel, DummyModel()))
    state = cast(
        AgentState[Any],
        {
            "messages": [
                HumanMessage(content="create a rule"),
                AIMessage(content="I can do that"),
            ]
        },
    )

    result = mw.before_agent(state, cast(Any, None))

    assert result is None


def test_scope_guardrail_allows_in_scope_requests(monkeypatch: Any) -> None:
    mw = ScopeGuardrailMiddleware(model=cast(BaseChatModel, DummyModel()))
    monkeypatch.setattr(mw, "_classify_request_scope", lambda **_: (True, "sensei"))
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="Create a SENSEI rule for topic scope")]})

    result = mw.before_agent(state, cast(Any, None))

    assert result is None


def test_scope_guardrail_blocks_out_of_scope_requests(monkeypatch: Any) -> None:
    mw = ScopeGuardrailMiddleware(model=cast(BaseChatModel, DummyModel()))
    monkeypatch.setattr(mw, "_classify_request_scope", lambda **_: (False, "generic_coding"))
    monkeypatch.setattr(mw, "_build_out_of_scope_reply", lambda **_: "Solo puedo ayudar con SENSEI.")
    state = cast(AgentState[Any], {"messages": [HumanMessage(content="Escríbeme una app en React")]})

    result = mw.before_agent(state, cast(Any, None))

    assert result is not None
    assert result["jump_to"] == "end"
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == "Solo puedo ayudar con SENSEI."


def test_scope_guardrail_scope_prompt_mentions_active_workspace_examples() -> None:
    mw = ScopeGuardrailMiddleware(model=cast(BaseChatModel, DummyModel()), has_workspace_context=True)
    prompt = mw._build_scope_prompt(
        user_text="What does this validation term mean?",
        messages=[HumanMessage(content="What does this validation term mean?")],
    )
    system_message = cast(SystemMessage, prompt[0])
    human_message = cast(HumanMessage, prompt[1])

    assert "A SENSEI workspace is currently open" in cast(str, system_message.content)
    assert "SENSEI domain vocabulary you should recognize as in-scope" in cast(str, system_message.content)
    assert "oracle" in cast(str, system_message.content)
    assert "Defining or clarifying SENSEI terminology and validation vocabulary." in cast(str, system_message.content)
    assert "Implicit project-local documentation or file questions" in cast(str, system_message.content)
    assert "What is an oracle?" not in cast(str, system_message.content)
    assert "Latest user request:\nWhat does this validation term mean?" in cast(str, human_message.content)


def test_scope_guardrail_scope_prompt_mentions_non_workspace_mode() -> None:
    mw = ScopeGuardrailMiddleware(model=cast(BaseChatModel, DummyModel()))
    prompt = mw._build_scope_prompt(
        user_text="What files do I have?",
        messages=[HumanMessage(content="What files do I have?")],
    )
    system_message = cast(SystemMessage, prompt[0])

    assert "No active SENSEI workspace is guaranteed." in cast(str, system_message.content)
