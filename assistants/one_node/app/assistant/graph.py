"""Graph construction and compilation for the assistant."""

from pathlib import Path
from typing import Any, Dict, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.assistant.state import ChatState
from app.nodes.answer.node_prompt import handle_prompt_node


def create_assistant_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver[Any] | None = None,  # noqa: ANN401
    project_path: Path | str | None = None,
    user_path: Path | str | None = None,
    verbose: bool = False,
) -> CompiledStateGraph[ChatState, None]:
    """Create and compile the assistant graph.

    Args:
        model: The LLM model to use in the graph.
        checkpointer: The checkpoint saver for persisting conversation state.
            When None, the graph is compiled without persistence.
        project_path: Sensei project directory used to load prompt context.
        user_path: User folder directory used to load extra prompt context.
        verbose: Enable verbose logging for LLM input/output.

    Returns:
        A compiled LangGraph state graph ready for streaming.
    """
    graph = StateGraph(ChatState)

    def respond_with_model(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
        return handle_prompt_node(state, model, project_path, user_path, verbose=verbose)

    graph.add_node("respond", respond_with_model)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)

    if checkpointer is None:
        return cast(CompiledStateGraph[ChatState, None], graph.compile())
    return cast(CompiledStateGraph[ChatState, None], graph.compile(checkpointer=checkpointer))
