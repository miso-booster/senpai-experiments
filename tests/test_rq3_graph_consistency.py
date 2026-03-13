import json

import pandas as pd
import pytest

from app.rq3.tool_consistency import (
    PromptRunItems,
    build_graph_node_presence_table,
    build_graph_prompt_consistency_summary,
    build_graph_run_level_table,
    extract_graph_prompt_run_sequences,
)


def _graph_row(
    conversation_id: str,
    name: str,
    *,
    run_type: str = "chain",
    langgraph_node: str | None = None,
    langgraph_step: int | None = None,
    ls_run_depth: int | None = None,
    row_pos: int = 0,
) -> dict:
    metadata = {}
    if langgraph_node is not None:
        metadata["langgraph_node"] = langgraph_node
    if langgraph_step is not None:
        metadata["langgraph_step"] = langgraph_step
    if ls_run_depth is not None:
        metadata["ls_run_depth"] = ls_run_depth
    return {
        "conversation_id": conversation_id,
        "run_type": run_type,
        "name": name,
        "metadata": json.dumps(metadata),
        "_start_time_dt": None,
        "_execution_order_num": None,
        "_row_pos": row_pos,
        "source_run_folder": "20260312_194857_894",
        "source_tracing_xlsx": "tracing.xlsx",
    }


def test_extract_graph_prompt_run_sequences_uses_langgraph_nodes_only():
    conversation_id = "graph_based_architecture__p7_intermediate__pizza_shop__rule__13675a4b"
    df = pd.DataFrame(
        [
            _graph_row(conversation_id, "LangGraph", ls_run_depth=0, row_pos=0),
            _graph_row(
                conversation_id,
                "classify_request",
                langgraph_node="classify_request",
                langgraph_step=1,
                ls_run_depth=1,
                row_pos=1,
            ),
            _graph_row(
                conversation_id,
                "_route_after_classification",
                langgraph_node="classify_request",
                langgraph_step=1,
                ls_run_depth=2,
                row_pos=2,
            ),
            _graph_row(
                conversation_id,
                "explain",
                langgraph_node="explain",
                langgraph_step=2,
                ls_run_depth=1,
                row_pos=3,
            ),
            _graph_row(
                conversation_id,
                "ChatOpenAI",
                run_type="llm",
                langgraph_node="explain",
                langgraph_step=2,
                ls_run_depth=2,
                row_pos=4,
            ),
            _graph_row(
                conversation_id,
                "detect_code_blocks",
                langgraph_node="detect_code_blocks",
                langgraph_step=3,
                ls_run_depth=1,
                row_pos=5,
            ),
        ]
    )

    records = extract_graph_prompt_run_sequences(df)

    assert len(records) == 1
    record = records[0]
    assert record.architecture == "graph_based_architecture"
    assert record.prompt_id == "p7"
    assert record.item_sequence == ("classify_request", "explain", "detect_code_blocks")


def test_graph_consistency_summary_and_presence_rates():
    records = [
        PromptRunItems(
            run_folder="run_1",
            tracing_xlsx="trace_1.xlsx",
            conversation_id="graph_based_architecture__p14_complex__pizza_shop__profile__aaaa1111",
            architecture="graph_based_architecture",
            prompt_key="graph_based_architecture__p14_complex__pizza_shop__profile",
            prompt_id="p14",
            difficulty="complex",
            target="profile",
            item_sequence=(
                "classify_request",
                "fix_profile",
                "decide_validation",
                "detect_code_blocks",
            ),
        ),
        PromptRunItems(
            run_folder="run_2",
            tracing_xlsx="trace_2.xlsx",
            conversation_id="graph_based_architecture__p14_complex__pizza_shop__profile__bbbb2222",
            architecture="graph_based_architecture",
            prompt_key="graph_based_architecture__p14_complex__pizza_shop__profile",
            prompt_id="p14",
            difficulty="complex",
            target="profile",
            item_sequence=(
                "classify_request",
                "fix_profile",
                "decide_validation",
                "detect_code_blocks",
            ),
        ),
        PromptRunItems(
            run_folder="run_3",
            tracing_xlsx="trace_3.xlsx",
            conversation_id="graph_based_architecture__p14_complex__pizza_shop__profile__cccc3333",
            architecture="graph_based_architecture",
            prompt_key="graph_based_architecture__p14_complex__pizza_shop__profile",
            prompt_id="p14",
            difficulty="complex",
            target="profile",
            item_sequence=(
                "classify_request",
                "fix_profile",
                "decide_validation",
                "detect_code_blocks",
                "extract_code_blocks",
            ),
        ),
    ]

    run_level = build_graph_run_level_table(records)
    prompt_summary = build_graph_prompt_consistency_summary(run_level)
    presence = build_graph_node_presence_table(run_level)

    assert len(prompt_summary) == 1
    row = prompt_summary.iloc[0]
    assert row["architecture"] == "graph_based_architecture"
    assert row["n_runs_observed"] == 3
    assert row["exact_sequence_consistency"] == pytest.approx(2 / 3)
    assert row["exact_set_consistency"] == pytest.approx(2 / 3)
    assert row["pairwise_set_jaccard_mean"] == pytest.approx(13 / 15)
    assert row["graph_nodes_mean"] == pytest.approx(13 / 3)
    assert row["graph_nodes_max"] == 5

    extract_presence = presence[presence["graph_node_name"] == "extract_code_blocks"].iloc[0]
    assert extract_presence["n_runs_with_item"] == 1
    assert extract_presence["presence_rate_across_runs"] == pytest.approx(1 / 3)
