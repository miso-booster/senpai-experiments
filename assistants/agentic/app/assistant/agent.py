"""Agent construction for the assistant."""

from functools import partial
from pathlib import Path
from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, SummarizationMiddleware, TodoListMiddleware
from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig
from langchain.agents.middleware.types import AgentState
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import ToolCall
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.runtime import Runtime

from app.assistant.hitl_feedback_middleware import HitlFeedbackMiddleware
from app.assistant.prompt import (
    CODING_SUMMARY_PROMPT,
    SENSEI_TODO_SYSTEM_PROMPT,
    SENSEI_TODO_TOOL_DESCRIPTION,
    build_prompt_node_system_prompt,
)
from app.assistant.scope_guardrail_middleware import ScopeGuardrailMiddleware
from app.assistant.tools import build_project_tools
from app.assistant.validation_middleware import (
    MessageValidationMiddleware,
    ToolCallValidationMiddleware,
    ValidationDecisionMiddleware,
)

AssistantAgent = Any


def _format_target_dir(target_dir: Path | None) -> str:
    if target_dir is None:
        return "(unknown)"
    project_name = target_dir.parent.name
    if project_name:
        return f"{project_name}/{target_dir.name}"
    return target_dir.as_posix()


def _format_save_file_interrupt(
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
    *,
    label: str,
    target_dir: Path | None = None,
) -> str:
    args = tool_call.get("args", {})
    filename = args.get("filename", "")
    overwrite = args.get("overwrite", False)
    content = args.get("content", "")
    preview = str(content)
    target_label = _format_target_dir(target_dir)

    return (
        f"{label} save request:\n"
        f"- target: {target_label}\n"
        f"- filename: {filename}\n"
        f"- overwrite: {overwrite}\n"
        "---- content preview ----\n"
        f"{preview}\n"
        "-------------------------"
    )


def _format_delete_file_interrupt(
    tool_call: ToolCall,
    _state: AgentState[Any],
    _runtime: Runtime[Any],
    *,
    label: str,
    target_dir: Path | None = None,
) -> str:
    args = tool_call.get("args", {})
    filename = args.get("filename", "")
    target_label = _format_target_dir(target_dir)

    return f"{label} deletion request:\n- target: {target_label}\n- filename: {filename}\n"


def _build_interrupt_config(description: object) -> InterruptOnConfig:
    return InterruptOnConfig(
        allowed_decisions=["approve", "reject"],
        description=cast(Any, description),
    )


def create_assistant_agent(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver[Any],  # noqa: ANN401
    project_path: Path | None = None,
    connectors_path: Path | None = None,
    embedding_path: Path | None = None,
    connectors_embedding_path: Path | None = None,
    *,
    include_create_tools: bool = True,
) -> AssistantAgent:
    """Create the assistant agent using LangChain's v1 create_agent helper."""
    tools = build_project_tools(
        project_path,
        connectors_path,
        embedding_path,
        connectors_embedding_path,
        include_create_tools=include_create_tools,
    )
    profiles_dir = project_path / "profiles" if project_path else None
    rules_dir = project_path / "rules" if project_path else None
    describe_save_profile = partial(_format_save_file_interrupt, label="Profile", target_dir=profiles_dir)
    describe_delete_profile = partial(_format_delete_file_interrupt, label="Profile", target_dir=profiles_dir)
    describe_save_rule = partial(_format_save_file_interrupt, label="Rule", target_dir=rules_dir)
    describe_delete_rule = partial(_format_delete_file_interrupt, label="Rule", target_dir=rules_dir)
    describe_save_connector = partial(
        _format_save_file_interrupt,
        label="Connector",
        target_dir=connectors_path,
    )
    describe_delete_connector = partial(
        _format_delete_file_interrupt,
        label="Connector",
        target_dir=connectors_path,
    )

    middleware = [
        ScopeGuardrailMiddleware(
            model=model,
            has_workspace_context=project_path is not None or connectors_path is not None,
        ),
        TodoListMiddleware(
            system_prompt=SENSEI_TODO_SYSTEM_PROMPT,
            tool_description=SENSEI_TODO_TOOL_DESCRIPTION,
        ),
        SummarizationMiddleware(
            model=model, trigger=("fraction", 0.85), keep=("fraction", 0.1), summary_prompt=CODING_SUMMARY_PROMPT
        ),
        HitlFeedbackMiddleware(),
        HumanInTheLoopMiddleware(
            interrupt_on={
                **(
                    {
                        "save_profile": _build_interrupt_config(describe_save_profile),
                        "save_rule": _build_interrupt_config(describe_save_rule),
                        "save_connector": _build_interrupt_config(describe_save_connector),
                    }
                    if include_create_tools
                    else {}
                ),
                "delete_profile": _build_interrupt_config(describe_delete_profile),
                "delete_rule": _build_interrupt_config(describe_delete_rule),
                "delete_connector": _build_interrupt_config(describe_delete_connector),
            }
        ),
        # Validation middlewares run in inverse order, so keep them last to run before HITL.
        MessageValidationMiddleware(model=model),
        ToolCallValidationMiddleware(model=model),
        ValidationDecisionMiddleware(model=model),
    ]

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=build_prompt_node_system_prompt(),
        checkpointer=checkpointer,
        middleware=middleware,
    )
