import pandas as pd

from app.rq3_clustering.answer_clustering import build_architecture_tables, build_duplicates_report


def test_build_architecture_tables_pivots_answers_by_prompt_and_run_group() -> None:
    df = pd.DataFrame(
        [
            {"arch_id": "arch_a", "prompt_id": "p2_basic", "run_group_id": "run_b", "answer": "A-2-B"},
            {"arch_id": "arch_a", "prompt_id": "p1_basic", "run_group_id": "run_a", "answer": "A-1-A"},
            {"arch_id": "arch_a", "prompt_id": "p1_basic", "run_group_id": "run_b", "answer": "A-1-B"},
            {"arch_id": "arch_b", "prompt_id": "p1_basic", "run_group_id": "run_a", "answer": "B-1-A"},
        ]
    )

    tables = build_architecture_tables(df)

    assert sorted(tables) == ["arch_a", "arch_b"]
    assert tables["arch_a"].index.tolist() == ["p1_basic", "p2_basic"]
    assert tables["arch_a"].columns.tolist() == ["run_a", "run_b"]
    assert tables["arch_a"].loc["p1_basic", "run_a"] == "A-1-A"
    assert tables["arch_a"].loc["p1_basic", "run_b"] == "A-1-B"
    assert pd.isna(tables["arch_a"].loc["p2_basic", "run_a"])
    assert tables["arch_b"].loc["p1_basic", "run_a"] == "B-1-A"


def test_build_duplicates_report_detects_multiple_answers_for_same_group() -> None:
    df = pd.DataFrame(
        [
            {"arch_id": "arch_a", "prompt_id": "p1_basic", "run_group_id": "run_a", "answer": "first"},
            {"arch_id": "arch_a", "prompt_id": "p1_basic", "run_group_id": "run_a", "answer": "second"},
            {"arch_id": "arch_a", "prompt_id": "p2_basic", "run_group_id": "run_a", "answer": "only"},
        ]
    )

    duplicates = build_duplicates_report(df)

    assert len(duplicates) == 1
    row = duplicates.iloc[0]
    assert row["arch_id"] == "arch_a"
    assert row["prompt_id"] == "p1_basic"
    assert row["run_group_id"] == "run_a"
    assert row["answer_count"] == 2
    assert row["distinct_answer_count"] == 2
    assert row["sample_answer"] == "first"
