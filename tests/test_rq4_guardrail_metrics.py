import math
from pathlib import Path

import pandas as pd

from app.rq4.aggregate_metrics import (
    build_architecture_summary,
    build_pairwise_wilcoxon_summary,
    build_prompt_arch_summary,
    enrich_rows,
    load_prompt_catalog,
)


def test_enrich_rows_uses_fallback_column_as_block_signal() -> None:
    df = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "run_group_id": "r1",
                "prompt_id": "p1_basic",
                "conversation_id": "conv_1",
                "fallback": True,
            },
            {
                "arch_id": "arch_a",
                "run_group_id": "r1",
                "prompt_id": "p2_basic",
                "conversation_id": "conv_2",
                "fallback": False,
            },
        ]
    )
    prompt_catalog = pd.DataFrame(
        [
            {"prompt_id": "p1_basic", "prompt_text": "A", "expected_decision": "block", "difficulty_bucket": "basic"},
            {"prompt_id": "p2_basic", "prompt_text": "B", "expected_decision": "block", "difficulty_bucket": "basic"},
        ]
    )
    middleware = pd.DataFrame(
        [
            {"run_group_id": "r1", "conversation_id": "conv_1", "middleware_decision": "block"},
            {"run_group_id": "r1", "conversation_id": "conv_2", "middleware_decision": "allow"},
        ]
    )

    enriched = enrich_rows(df, prompt_catalog, middleware)

    assert enriched.loc[0, "final_decision"] == "block"
    assert bool(enriched.loc[0, "correct_behavior_int"]) is True
    assert enriched.loc[1, "final_decision"] == "allow"
    assert bool(enriched.loc[1, "unsafe_allow_int"]) is True


def test_build_architecture_summary_computes_guardrail_rates() -> None:
    df = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "run_group_id": "r1",
                "prompt_id": "p1_basic",
                "expected_decision": "block",
                "difficulty_bucket": "basic",
                "project": "pizza_shop",
                "type": "profile",
                "correct_behavior_int": 1,
                "correct_block_int": 1,
                "correct_allow_int": 0,
                "unsafe_allow_int": 0,
                "false_block_int": 0,
                "final_allow_int": 0,
                "final_block_int": 1,
                "middleware_signal_present": 1,
                "middleware_correct_int": 1,
                "latency_s": 1.0,
                "total_input_tokens": 10,
                "llm_call_count": 1,
                "answer_code_lines": 0,
            },
            {
                "arch_id": "arch_a",
                "run_group_id": "r1",
                "prompt_id": "p4_basic",
                "expected_decision": "allow",
                "difficulty_bucket": "basic",
                "project": "pizza_shop",
                "type": "profile",
                "correct_behavior_int": 1,
                "correct_block_int": 0,
                "correct_allow_int": 1,
                "unsafe_allow_int": 0,
                "false_block_int": 0,
                "final_allow_int": 1,
                "final_block_int": 0,
                "middleware_signal_present": 1,
                "middleware_correct_int": 1,
                "latency_s": 2.0,
                "total_input_tokens": 20,
                "llm_call_count": 2,
                "answer_code_lines": 5,
            },
            {
                "arch_id": "arch_b",
                "run_group_id": "r1",
                "prompt_id": "p1_basic",
                "expected_decision": "block",
                "difficulty_bucket": "basic",
                "project": "pizza_shop",
                "type": "profile",
                "correct_behavior_int": 0,
                "correct_block_int": 0,
                "correct_allow_int": 0,
                "unsafe_allow_int": 1,
                "false_block_int": 0,
                "final_allow_int": 1,
                "final_block_int": 0,
                "middleware_signal_present": 0,
                "middleware_correct_int": 0,
                "latency_s": 3.0,
                "total_input_tokens": 30,
                "llm_call_count": 3,
                "answer_code_lines": 8,
            },
            {
                "arch_id": "arch_b",
                "run_group_id": "r1",
                "prompt_id": "p4_basic",
                "expected_decision": "allow",
                "difficulty_bucket": "basic",
                "project": "pizza_shop",
                "type": "profile",
                "correct_behavior_int": 0,
                "correct_block_int": 0,
                "correct_allow_int": 0,
                "unsafe_allow_int": 0,
                "false_block_int": 1,
                "final_allow_int": 0,
                "final_block_int": 1,
                "middleware_signal_present": 0,
                "middleware_correct_int": 0,
                "latency_s": 4.0,
                "total_input_tokens": 40,
                "llm_call_count": 4,
                "answer_code_lines": 0,
            },
        ]
    )

    prompt_summary = build_prompt_arch_summary(df)
    architecture_summary = build_architecture_summary(df, prompt_summary)

    arch_a = architecture_summary[architecture_summary["arch_id"] == "arch_a"].iloc[0]
    arch_b = architecture_summary[architecture_summary["arch_id"] == "arch_b"].iloc[0]

    assert math.isclose(arch_a["overall_accuracy_rate"], 1.0)
    assert math.isclose(arch_a["expected_block_success_rate"], 1.0)
    assert math.isclose(arch_a["expected_allow_success_rate"], 1.0)
    assert math.isclose(arch_a["unsafe_allow_rate"], 0.0)
    assert math.isclose(arch_a["false_block_rate"], 0.0)

    assert math.isclose(arch_b["overall_accuracy_rate"], 0.0)
    assert math.isclose(arch_b["expected_block_success_rate"], 0.0)
    assert math.isclose(arch_b["expected_allow_success_rate"], 0.0)
    assert math.isclose(arch_b["unsafe_allow_rate"], 0.5)
    assert math.isclose(arch_b["false_block_rate"], 0.5)


def test_build_pairwise_wilcoxon_summary_uses_matched_pairs_for_guardrail_metrics() -> None:
    df = pd.DataFrame(
        [
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_a", "correct_behavior_int": 1},
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_b", "correct_behavior_int": 0},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_a", "correct_behavior_int": 1},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_b", "correct_behavior_int": 0},
            {"run_group_id": "r2", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_a", "correct_behavior_int": 0},
            {"run_group_id": "r2", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_b", "correct_behavior_int": 0},
        ]
    )

    summary = build_pairwise_wilcoxon_summary(df, ["correct_behavior_int"])
    row = summary.iloc[0]

    assert row["metric"] == "correct_behavior_int"
    assert row["n_pairs"] == 3
    assert row["n_nonzero_pairs"] == 2
    assert row["arch_a_gt_arch_b_count"] == 2
    assert row["tie_count"] == 1
    assert math.isclose(row["a12_arch_a_over_arch_b"], 5.0 / 6.0)
    assert math.isclose(row["a12_arch_b_over_arch_a"], 1.0 / 6.0)
    assert row["a12_magnitude"] == "large"


def test_build_pairwise_wilcoxon_summary_keeps_models_separate() -> None:
    df = pd.DataFrame(
        [
            {
                "model_label": "model_a",
                "run_group_id": "r1",
                "prompt_id": "p1",
                "arch_id": "arch_a",
                "correct_behavior_int": 1,
            },
            {
                "model_label": "model_a",
                "run_group_id": "r1",
                "prompt_id": "p1",
                "arch_id": "arch_b",
                "correct_behavior_int": 0,
            },
            {
                "model_label": "model_b",
                "run_group_id": "r1",
                "prompt_id": "p1",
                "arch_id": "arch_a",
                "correct_behavior_int": 0,
            },
            {
                "model_label": "model_b",
                "run_group_id": "r1",
                "prompt_id": "p1",
                "arch_id": "arch_b",
                "correct_behavior_int": 1,
            },
        ]
    )

    summary = build_pairwise_wilcoxon_summary(df, ["correct_behavior_int"])

    assert set(summary["model_label"]) == {"model_a", "model_b"}
    assert len(summary) == 2
    model_a = summary[summary["model_label"] == "model_a"].iloc[0]
    model_b = summary[summary["model_label"] == "model_b"].iloc[0]
    assert model_a["arch_a_gt_arch_b_count"] == 1
    assert model_b["arch_a_lt_arch_b_count"] == 1


def test_build_pairwise_wilcoxon_summary_handles_all_zero_differences_for_a12() -> None:
    df = pd.DataFrame(
        [
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_a", "correct_behavior_int": 1},
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_b", "correct_behavior_int": 1},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_a", "correct_behavior_int": 0},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_b", "correct_behavior_int": 0},
        ]
    )

    summary = build_pairwise_wilcoxon_summary(df, ["correct_behavior_int"])
    row = summary.iloc[0]

    assert row["n_pairs"] == 2
    assert row["n_nonzero_pairs"] == 0
    assert row["wilcoxon_statistic"] == 0.0
    assert row["p_value"] == 1.0
    assert row["a12_arch_a_over_arch_b"] == 0.5
    assert row["a12_arch_b_over_arch_a"] == 0.5
    assert row["a12_magnitude"] == "negligible"
    assert row["notes"] == "all paired differences are zero"


def test_load_prompt_catalog_respects_optional_expected_decision(tmp_path: Path) -> None:
    prompt_config = tmp_path / "rq4_prompts.json"
    prompt_config.write_text(
        (
            '[{"id":"p1_basic","text":"A","expected_decision":"allow"},'
            '{"id":"p2_basic","text":"B","expected_decision":" BLOCK "},'
            '{"id":"p3_basic","text":"C","expected_decision":"invalid"},'
            '{"id":"p4_basic","text":"D"}]'
        ),
        encoding="utf-8",
    )

    prompts = load_prompt_catalog(prompt_config)
    decisions = dict(zip(prompts["prompt_id"], prompts["expected_decision"]))

    assert decisions["p1_basic"] == "allow"
    assert decisions["p2_basic"] == "block"
    assert decisions["p3_basic"] == "block"
    assert decisions["p4_basic"] == "block"
