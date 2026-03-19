import pandas as pd

from app.rq2.fallback_answer_join import build_fallback_answer_join, filter_to_any_fallback


def test_build_fallback_answer_join_pivots_answers_and_fallbacks_by_architecture() -> None:
    df = pd.DataFrame(
        [
            {
                "run_group_id": "run_a",
                "prompt_id": "p2",
                "prompt": "Second prompt",
                "arch_id": "arch_b",
                "answer": "B2",
                "fallback": False,
            },
            {
                "run_group_id": "run_a",
                "prompt_id": "p1",
                "prompt": "First prompt",
                "arch_id": "arch_a",
                "answer": "A1",
                "fallback": False,
            },
            {
                "run_group_id": "run_a",
                "prompt_id": "p1",
                "prompt": "First prompt",
                "arch_id": "arch_b",
                "answer": "B1",
                "fallback": True,
            },
            {
                "run_group_id": "run_b",
                "prompt_id": "p1",
                "prompt": "First prompt",
                "arch_id": "arch_a",
                "answer": "A1b",
                "fallback": False,
            },
            {
                "run_group_id": "run_b",
                "prompt_id": "p1",
                "prompt": "First prompt",
                "arch_id": "arch_b",
                "answer": "B1b",
                "fallback": False,
            },
        ]
    )

    joined = build_fallback_answer_join(df)

    assert joined.columns.tolist() == [
        "run_group_id",
        "prompt_id",
        "prompt",
        "answer_arch_a",
        "answer_arch_b",
        "fallback_arch_a",
        "fallback_arch_b",
    ]
    assert joined["prompt_id"].tolist() == ["p1", "p2", "p1"]
    assert joined.iloc[0]["answer_arch_a"] == "A1"
    assert joined.iloc[0]["answer_arch_b"] == "B1"
    assert bool(joined.iloc[0]["fallback_arch_a"]) is False
    assert bool(joined.iloc[0]["fallback_arch_b"]) is True
    assert pd.isna(joined.iloc[1]["answer_arch_a"])
    assert joined.iloc[1]["answer_arch_b"] == "B2"


def test_filter_to_any_fallback_keeps_only_rows_with_a_true_fallback() -> None:
    joined = pd.DataFrame(
        [
            {
                "run_group_id": "run_a",
                "prompt_id": "p1",
                "prompt": "Prompt 1",
                "answer_arch_a": "A1",
                "answer_arch_b": "B1",
                "fallback_arch_a": False,
                "fallback_arch_b": True,
            },
            {
                "run_group_id": "run_b",
                "prompt_id": "p1",
                "prompt": "Prompt 1",
                "answer_arch_a": "A1b",
                "answer_arch_b": "B1b",
                "fallback_arch_a": False,
                "fallback_arch_b": False,
            },
        ]
    )

    filtered = filter_to_any_fallback(joined)

    assert len(filtered) == 1
    assert filtered.iloc[0]["run_group_id"] == "run_a"
