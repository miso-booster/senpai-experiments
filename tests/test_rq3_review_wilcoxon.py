import math

import pandas as pd

from app.rq3_clustering.review import (
    build_pairwise_wilcoxon_summary,
    build_summaries_from_assignments,
)


def test_build_pairwise_wilcoxon_summary_uses_matched_prompt_pairs() -> None:
    df = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1",
                "majority_cluster_share": 1.0,
                "is_perfect_consensus": True,
                "cluster_count": 1,
                "fallback_rate": 0.0,
            },
            {
                "arch_id": "arch_b",
                "prompt_id": "p1",
                "majority_cluster_share": 0.5,
                "is_perfect_consensus": False,
                "cluster_count": 2,
                "fallback_rate": 0.2,
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p2",
                "majority_cluster_share": 0.8,
                "is_perfect_consensus": False,
                "cluster_count": 2,
                "fallback_rate": 0.1,
            },
            {
                "arch_id": "arch_b",
                "prompt_id": "p2",
                "majority_cluster_share": 0.4,
                "is_perfect_consensus": False,
                "cluster_count": 3,
                "fallback_rate": 0.4,
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p3",
                "majority_cluster_share": 0.7,
                "is_perfect_consensus": False,
                "cluster_count": 3,
                "fallback_rate": 0.3,
            },
        ]
    )

    summary = build_pairwise_wilcoxon_summary(df)

    assert len(summary) == 4

    majority_row = summary[summary["overall_metric"] == "mean_majority_cluster_share"].iloc[0]
    assert majority_row["arch_a"] == "arch_a"
    assert majority_row["arch_b"] == "arch_b"
    assert majority_row["n_pairs"] == 2
    assert majority_row["n_nonzero_pairs"] == 2
    assert math.isclose(majority_row["arch_a_mean"], 0.9)
    assert math.isclose(majority_row["arch_b_mean"], 0.45)
    assert math.isclose(majority_row["mean_difference_a_minus_b"], 0.45)
    assert majority_row["arch_a_gt_arch_b_count"] == 2
    assert majority_row["tie_count"] == 0
    assert not math.isnan(majority_row["p_value"])


def test_build_pairwise_wilcoxon_summary_handles_all_zero_differences() -> None:
    df = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1",
                "majority_cluster_share": 1.0,
                "is_perfect_consensus": True,
                "cluster_count": 1,
                "fallback_rate": 0.0,
            },
            {
                "arch_id": "arch_b",
                "prompt_id": "p1",
                "majority_cluster_share": 1.0,
                "is_perfect_consensus": True,
                "cluster_count": 1,
                "fallback_rate": 0.0,
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p2",
                "majority_cluster_share": 0.5,
                "is_perfect_consensus": False,
                "cluster_count": 2,
                "fallback_rate": 0.4,
            },
            {
                "arch_id": "arch_b",
                "prompt_id": "p2",
                "majority_cluster_share": 0.5,
                "is_perfect_consensus": False,
                "cluster_count": 2,
                "fallback_rate": 0.4,
            },
        ]
    )

    summary = build_pairwise_wilcoxon_summary(df)

    row = summary[summary["overall_metric"] == "fallback_rate"].iloc[0]
    assert row["n_pairs"] == 2
    assert row["n_nonzero_pairs"] == 0
    assert row["wilcoxon_statistic"] == 0.0
    assert row["p_value"] == 1.0
    assert row["notes"] == "all paired differences are zero"
    assert bool(row["significant_p_lt_0_05"]) is False


def test_build_summaries_from_assignments_penalizes_full_fallback_prompts() -> None:
    assignments = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1",
                "prompt": "Prompt 1",
                "response_index": 1,
                "answer": "Fallback 1",
                "final_cluster_id": "FB",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1",
                "prompt": "Prompt 1",
                "response_index": 2,
                "answer": "Fallback 2",
                "final_cluster_id": "FB",
            },
        ]
    )

    overall_summary, prompt_summary, _ = build_summaries_from_assignments(
        assignments,
        final_cluster_id_col="final_cluster_id",
        proposed_cluster_label_col=None,
        proposed_cluster_reason_col=None,
        reviewed_flag_col=None,
        review_notes_col=None,
        result_source="human_review",
    )

    prompt_row = prompt_summary.iloc[0]
    assert prompt_row["substantive_response_count"] == 0
    assert prompt_row["majority_cluster_share"] == 0.0
    assert prompt_row["cluster_count"] == 0
    assert bool(prompt_row["is_perfect_consensus"]) is False

    overall_row = overall_summary.iloc[0]
    assert overall_row["mean_majority_cluster_share"] == 0.0
    assert overall_row["mean_cluster_count"] == 0.0
    assert math.isnan(overall_row["perfect_consensus_rate"])
