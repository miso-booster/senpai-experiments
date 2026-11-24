"""Graph construction and compilation for the assistant."""

from collections.abc import Mapping
from typing import Any, Dict, Literal, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.assistant.state import ChatState
from app.nodes.action.node_build_fix_system_prompt import build_fix_system_prompt
from app.nodes.action.node_decide_validation_needed import decide_validation_needed
from app.nodes.action.node_detect_code_blocks import detect_code_blocks
from app.nodes.action.node_extract_codeblocks_metadata import extract_code_blocks_metadata
from app.nodes.action.node_fix_invalid_code_blocks import fix_invalid_code_blocks
from app.nodes.action.node_render_validation_failure_response import render_validation_failure_response
from app.nodes.action.node_validate_code_blocks_content import validate_code_blocks_content
from app.nodes.answer.node_create_connector import handle_create_connector
from app.nodes.answer.node_create_profile import handle_create_profile
from app.nodes.answer.node_create_rule import handle_create_rule
from app.nodes.answer.node_explain import handle_explain
from app.nodes.answer.node_fix_connector import handle_fix_connector
from app.nodes.answer.node_fix_profile import handle_fix_profile
from app.nodes.answer.node_fix_rule import handle_fix_rule
from app.nodes.node_intent_routing import classify_request


def create_assistant_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver[Any] | None = None,  # noqa: ANN401
    project_context: str | Mapping[str, str] = "",
    verbose: bool = False,
) -> CompiledStateGraph[ChatState, None]:
    """Create and compile the assistant graph.

    Args:
        model: The LLM model to use in the graph.
        checkpointer: The checkpoint saver for persisting conversation state.
            When None, the graph is compiled without persistence.
        project_context: Either a single prompt context string applied everywhere or
            a per-intent mapping with keys like "profile", "rule", "connector", and "explain".
        verbose: Enable verbose logging for LLM input/output.

    Returns:
        A compiled LangGraph state graph ready for streaming.
    """
    graph = StateGraph(ChatState)

    def _context_for_intent(intent: str | None) -> str:
        if isinstance(project_context, Mapping):
            if intent in {"create_profile", "fix_profile"}:
                return str(project_context.get("profile", ""))
            if intent in {"create_rule", "fix_rule"}:
                return str(project_context.get("rule", ""))
            if intent in {"create_connector", "fix_connector"}:
                return str(project_context.get("connector", ""))
            return str(project_context.get("explain", ""))
        return project_context

    def classify_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return classify_request(state, model, verbose=verbose)

    def create_rule_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_create_rule(state, model, _context_for_intent("create_rule"), verbose=verbose)

    def create_profile_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_create_profile(state, model, _context_for_intent("create_profile"), verbose=verbose)

    def create_connector_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_create_connector(state, model, _context_for_intent("create_connector"), verbose=verbose)

    def fix_rule_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_fix_rule(state, model, _context_for_intent("fix_rule"), verbose=verbose)

    def fix_profile_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_fix_profile(state, model, _context_for_intent("fix_profile"), verbose=verbose)

    def fix_connector_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_fix_connector(state, model, _context_for_intent("fix_connector"), verbose=verbose)

    def explain_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_explain(state, model, _context_for_intent("explain"), verbose=verbose)

    def fix_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return fix_invalid_code_blocks(
            state,
            model,
            fix_system_prompt=build_fix_system_prompt(_context_for_intent(state.get("intent"))),
            verbose=verbose,
        )

    def failure_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return render_validation_failure_response(state, model, verbose=verbose)

    graph.add_node("classify_request", classify_with_model)
    graph.add_node("create_rule", create_rule_with_model)
    graph.add_node("create_profile", create_profile_with_model)
    graph.add_node("create_connector", create_connector_with_model)
    graph.add_node("fix_rule", fix_rule_with_model)
    graph.add_node("fix_profile", fix_profile_with_model)
    graph.add_node("fix_connector", fix_connector_with_model)
    graph.add_node("explain", explain_with_model)

    def decide_validation_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return decide_validation_needed(state, model, verbose=verbose)

    graph.add_node("decide_validation", decide_validation_with_model)
    graph.add_node("detect_code_blocks", detect_code_blocks)
    graph.add_node("extract_code_blocks", extract_code_blocks_metadata)
    graph.add_node("validate_code_blocks", validate_code_blocks_content)
    graph.add_node("fix_code_blocks", fix_with_model)
    graph.add_node("render_failure", failure_with_model)

    graph.add_edge(START, "classify_request")

    def _route_after_classification(
        state: ChatState,
    ) -> Literal[
        "create_rule",
        "create_profile",
        "create_connector",
        "fix_rule",
        "fix_profile",
        "fix_connector",
        "explain",
        "end",
    ]:
        intent = state.get("intent") or "other"
        if intent == "create_rule":
            return "create_rule"
        if intent == "create_profile":
            return "create_profile"
        if intent == "create_connector":
            return "create_connector"
        if intent == "fix_rule":
            return "fix_rule"
        if intent == "fix_profile":
            return "fix_profile"
        if intent == "fix_connector":
            return "fix_connector"
        if intent == "explain":
            return "explain"
        return "end"

    graph.add_conditional_edges(
        "classify_request",
        _route_after_classification,
        {
            "create_rule": "create_rule",
            "create_profile": "create_profile",
            "create_connector": "create_connector",
            "fix_rule": "fix_rule",
            "fix_profile": "fix_profile",
            "fix_connector": "fix_connector",
            "explain": "explain",
            "end": END,
        },
    )

    for node_name in (
        "create_rule",
        "create_profile",
        "create_connector",
        "fix_rule",
        "fix_profile",
        "fix_connector",
        "explain",
    ):
        graph.add_edge(node_name, "decide_validation")
    graph.add_edge("decide_validation", "detect_code_blocks")

    def _route_after_codeblock_detection(state: ChatState) -> Literal["extract", "end"]:
        should_validate = state.get("should_validate")
        if should_validate is False:
            return "end"
        codeblocks = state.get("is_codeblock", False)
        if codeblocks:
            return "extract"
        return "end"

    graph.add_conditional_edges(
        "detect_code_blocks",
        _route_after_codeblock_detection,
        {
            "end": END,
            "extract": "extract_code_blocks",
        },
    )

    graph.add_edge("extract_code_blocks", "validate_code_blocks")

    def _route_after_validation(state: ChatState) -> Literal["fix", "failure", "end"]:
        """Decide next step after code block validation."""
        retry_action = state.get("retry_action")
        if retry_action == "fix_blocks":
            return "fix"
        if retry_action == "final_failure":
            return "failure"
        return "end"

    graph.add_conditional_edges(
        "validate_code_blocks",
        _route_after_validation,
        {"fix": "fix_code_blocks", "failure": "render_failure", "end": END},
    )

    graph.add_edge("fix_code_blocks", "detect_code_blocks")
    graph.add_edge("render_failure", END)

    if checkpointer is None:
        return cast(CompiledStateGraph[ChatState, None], graph.compile())
    return cast(CompiledStateGraph[ChatState, None], graph.compile(checkpointer=checkpointer))
