import math

import pandas as pd

from app.rq2_aggregate_metrics import build_pairwise_wilcoxon_summary


def test_build_pairwise_wilcoxon_summary_uses_matched_run_and_prompt_pairs() -> None:
    df = pd.DataFrame(
        [
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_a", "latency_s": 1.0},
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_b", "latency_s": 2.0},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_a", "latency_s": 2.0},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_b", "latency_s": 4.0},
            {"run_group_id": "r2", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_a", "latency_s": 3.0},
            {"run_group_id": "r2", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_b", "latency_s": 6.0},
            # Unmatched row should be ignored.
            {"run_group_id": "r2", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_a", "latency_s": 9.0},
        ]
    )

    summary = build_pairwise_wilcoxon_summary(df, ["latency_s"])

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["arch_a"] == "arch_a"
    assert row["arch_b"] == "arch_b"
    assert row["metric"] == "latency_s"
    assert row["n_pairs"] == 3
    assert row["n_nonzero_pairs"] == 3
    assert math.isclose(row["arch_a_median"], 2.0)
    assert math.isclose(row["arch_b_median"], 4.0)
    assert math.isclose(row["mean_difference_a_minus_b"], -2.0)
    assert row["arch_a_lt_arch_b_count"] == 3
    assert row["arch_a_gt_arch_b_count"] == 0
    assert row["tie_count"] == 0
    assert not math.isnan(row["p_value"])


def test_build_pairwise_wilcoxon_summary_handles_all_zero_differences() -> None:
    df = pd.DataFrame(
        [
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_a", "latency_s": 3.0},
            {"run_group_id": "r1", "prompt_id": "p1", "prompt": "A", "arch_id": "arch_b", "latency_s": 3.0},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_a", "latency_s": 4.0},
            {"run_group_id": "r1", "prompt_id": "p2", "prompt": "B", "arch_id": "arch_b", "latency_s": 4.0},
        ]
    )

    summary = build_pairwise_wilcoxon_summary(df, ["latency_s"])

    row = summary.iloc[0]
    assert row["n_pairs"] == 2
    assert row["n_nonzero_pairs"] == 0
    assert row["wilcoxon_statistic"] == 0.0
    assert row["p_value"] == 1.0
    assert row["notes"] == "all paired differences are zero"
    assert bool(row["significant_p_lt_0_05"]) is False
