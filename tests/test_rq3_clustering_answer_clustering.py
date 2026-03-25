import pandas as pd
import pytest

from app.rq3_clustering import answer_clustering
from app.rq3_clustering.answer_clustering import (
    _build_cluster_messages,
    build_architecture_tables,
    build_cluster_frames_for_group,
    build_duplicates_report,
    normalize_cluster_payload,
    repair_cluster_payload,
)
from app.rq3_clustering.plots import generate_plots
from app.rq3_clustering.review import (
    build_review_assignments,
    build_review_cluster_reference,
    build_summaries_from_assignments,
)
from app.rq3_clustering.review_metrics import validate_review_assignments


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


def test_prepare_group_rows_prefers_existing_fallback_detected_column() -> None:
    group = pd.DataFrame(
        [
            {
                "run_group_id": "run_a",
                "run_id": "run_a__1",
                "answer": "Please rephrase.",
                "fallback_detected": True,
            },
            {
                "run_group_id": "run_b",
                "run_id": "run_b__1",
                "answer": "Actual answer.",
                "fallback_detected": False,
            },
        ]
    )

    prepared = answer_clustering._prepare_group_rows(group)

    assert prepared["fallback_detected"].tolist() == [True, False]


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


def test_normalize_cluster_payload_rejects_missing_or_duplicate_response_ids() -> None:
    payload = {
        "clusters": [
            {
                "cluster_label": "A",
                "cluster_summary": "same",
                "response_ids": ["r01", "r01"],
            }
        ],
        "notes": "",
    }

    try:
        normalize_cluster_payload(payload, ["r01", "r02"])
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected normalize_cluster_payload() to fail")

    assert "duplicate ids: r01" in message
    assert "missing ids: r02" in message


def test_build_cluster_frames_for_group_builds_summary_counts_and_assignments() -> None:
    group = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Which profile is used?",
                "run_group_id": "run_a",
                "run_id": "run_a__1",
                "answer": "Profile alpha",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Which profile is used?",
                "run_group_id": "run_b",
                "run_id": "run_b__1",
                "answer": "Profile alpha with extra wording",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Which profile is used?",
                "run_group_id": "run_c",
                "run_id": "run_c__1",
                "answer": "Profile beta",
            },
        ]
    )
    payload = {
        "clusters": [
            {
                "cluster_label": "Selects alpha",
                "cluster_summary": "The response points to alpha.",
                "response_ids": ["r01", "r02"],
            },
            {
                "cluster_label": "Selects beta",
                "cluster_summary": "The response points to beta.",
                "response_ids": ["r03"],
            },
        ],
        "notes": "One minority answer.",
    }

    prompt_summary, cluster_summary, assignments = build_cluster_frames_for_group(
        group,
        payload,
        model="gpt-4o-mini",
        result_source="api",
    )

    assert len(prompt_summary) == 1
    assert prompt_summary.iloc[0]["majority_cluster_id"] == "c1"
    assert prompt_summary.iloc[0]["majority_cluster_size"] == 2
    assert prompt_summary.iloc[0]["cluster_count"] == 2
    assert bool(prompt_summary.iloc[0]["is_perfect_consensus"]) is False
    assert "c1=2 (Selects alpha)" in prompt_summary.iloc[0]["cluster_breakdown"]

    assert cluster_summary["cluster_id"].tolist() == ["c1", "c2"]
    assert cluster_summary["response_count"].tolist() == [2, 1]
    assert cluster_summary.iloc[0]["representative_response_id"] == "r01"
    assert cluster_summary.iloc[0]["response_indexes"] == "1, 2"
    assert cluster_summary.iloc[0]["run_group_ids"] == "run_a, run_b"

    assert assignments["response_id"].tolist() == ["r01", "r02", "r03"]
    assert assignments["response_index"].tolist() == [1, 2, 3]
    assert assignments["cluster_id"].tolist() == ["c1", "c1", "c2"]
    assert assignments.iloc[2]["cluster_label"] == "Selects beta"


def test_repair_cluster_payload_adds_missing_ids_as_singletons() -> None:
    payload = {
        "clusters": [
            {
                "cluster_label": "Shared answer",
                "cluster_summary": "Two responses agree.",
                "response_ids": ["r01", "r03", "r03", "r99"],
            }
        ],
        "notes": "initial notes",
    }

    repaired = repair_cluster_payload(payload, ["r01", "r02", "r03", "r04"])

    normalized = normalize_cluster_payload(repaired, ["r01", "r02", "r03", "r04"])
    assert [cluster["response_ids"] for cluster in normalized] == [["r01", "r03"], ["r02"], ["r04"]]
    assert "auto_repair=" in repaired["notes"]
    assert "added singleton clusters for missing ids: r02, r04" in repaired["notes"]


def test_normalize_cluster_payload_requires_fallback_ids_in_fb_cluster() -> None:
    payload = {
        "clusters": [
            {
                "cluster_label": "Some other cluster",
                "cluster_summary": "Wrongly placed fallback.",
                "response_ids": ["r01"],
            },
            {
                "cluster_label": "Regular answer",
                "cluster_summary": "Normal answer.",
                "response_ids": ["r02"],
            },
        ],
        "notes": "",
    }

    with pytest.raises(ValueError, match="fallback ids missing from FB cluster: r01"):
        normalize_cluster_payload(payload, ["r01", "r02"], fallback_response_ids=["r01"])


def test_normalize_cluster_payload_rejects_fb_cluster_without_fallbacks() -> None:
    payload = {
        "clusters": [
            {
                "cluster_label": "FB",
                "cluster_summary": "Should not exist.",
                "response_ids": ["r01"],
            },
            {
                "cluster_label": "Regular answer",
                "cluster_summary": "Normal answer.",
                "response_ids": ["r02"],
            },
        ],
        "notes": "",
    }

    with pytest.raises(ValueError, match="FB cluster is not allowed when no fallback ids were detected"):
        normalize_cluster_payload(payload, ["r01", "r02"], fallback_response_ids=[])


def test_normalize_cluster_payload_rejects_multiple_fb_clusters() -> None:
    payload = {
        "clusters": [
            {
                "cluster_label": "FB",
                "cluster_summary": "Fallback group one.",
                "response_ids": ["r01"],
            },
            {
                "cluster_label": "FB",
                "cluster_summary": "Fallback group two.",
                "response_ids": ["r02"],
            },
        ],
        "notes": "",
    }

    with pytest.raises(ValueError, match="multiple FB clusters are not allowed"):
        normalize_cluster_payload(payload, ["r01", "r02"], fallback_response_ids=["r01", "r02"])


def test_build_cluster_frames_for_group_assigns_fb_cluster_to_fallback_answers() -> None:
    group = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "run_group_id": "run_a",
                "run_id": "run_a__1",
                "answer": "Please rephrase your question.",
                "fallback": True,
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "run_group_id": "run_b",
                "run_id": "run_b__1",
                "answer": "Concrete answer",
                "fallback": False,
            },
        ]
    )
    payload = {
        "clusters": [
            {
                "cluster_label": "FB",
                "cluster_summary": "Fallback or non-answer responses.",
                "response_ids": ["r01"],
            },
            {
                "cluster_label": "Concrete answer",
                "cluster_summary": "Provides the requested answer.",
                "response_ids": ["r02"],
            },
        ],
        "notes": "",
    }

    prompt_summary, cluster_summary, assignments = build_cluster_frames_for_group(
        group,
        payload,
        model="gpt-4o-mini",
        result_source="api",
    )

    assert cluster_summary["cluster_id"].tolist() == ["FB", "c2"]
    assert cluster_summary["cluster_label"].tolist() == ["FB", "Concrete answer"]
    assert assignments["cluster_id"].tolist() == ["FB", "c2"]
    assert prompt_summary.iloc[0]["cluster_breakdown"].startswith("FB=1 (FB)")


def test_build_cluster_frames_for_group_keeps_majority_cluster_size_based_when_fb_exists() -> None:
    group = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "run_group_id": "run_a",
                "run_id": "run_a__1",
                "answer": "Please rephrase your question.",
                "fallback": True,
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "run_group_id": "run_b",
                "run_id": "run_b__1",
                "answer": "Concrete answer",
                "fallback": False,
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "run_group_id": "run_c",
                "run_id": "run_c__1",
                "answer": "Concrete answer",
                "fallback": False,
            },
        ]
    )
    payload = {
        "clusters": [
            {
                "cluster_label": "FB",
                "cluster_summary": "Fallback or non-answer responses.",
                "response_ids": ["r01"],
            },
            {
                "cluster_label": "Concrete answer",
                "cluster_summary": "Same substantive answer.",
                "response_ids": ["r02", "r03"],
            },
        ],
        "notes": "",
    }

    prompt_summary, cluster_summary, assignments = build_cluster_frames_for_group(
        group,
        payload,
        model="gpt-4o-mini",
        result_source="api",
    )

    assert cluster_summary["cluster_id"].tolist() == ["FB", "c2"]
    assert assignments["cluster_id"].tolist() == ["FB", "c2", "c2"]
    assert prompt_summary.iloc[0]["majority_cluster_id"] == "c2"
    assert prompt_summary.iloc[0]["majority_cluster_label"] == "Concrete answer"
    assert prompt_summary.iloc[0]["majority_cluster_size"] == 2


def test_repair_cluster_payload_builds_fb_cluster_for_known_fallbacks() -> None:
    payload = {
        "clusters": [
            {
                "cluster_label": "Regular answer",
                "cluster_summary": "Contains both kinds of responses.",
                "response_ids": ["r01", "r02"],
            }
        ],
        "notes": "",
    }

    repaired = repair_cluster_payload(payload, ["r01", "r02"], fallback_response_ids=["r01"])
    normalized = normalize_cluster_payload(
        repaired,
        ["r01", "r02"],
        fallback_response_ids=["r01"],
    )

    assert normalized[0]["cluster_id"] == "FB"
    assert normalized[0]["response_ids"] == ["r01"]
    assert normalized[1]["response_ids"] == ["r02"]


def test_repair_cluster_payload_does_not_duplicate_inserted_fallback_ids() -> None:
    payload = {
        "clusters": [
            {
                "cluster_label": "Regular answer",
                "cluster_summary": "Contains only the non-fallback response.",
                "response_ids": ["r02"],
            }
        ],
        "notes": "",
    }

    repaired = repair_cluster_payload(payload, ["r01", "r02"], fallback_response_ids=["r01"])
    normalized = normalize_cluster_payload(
        repaired,
        ["r01", "r02"],
        fallback_response_ids=["r01"],
    )

    assert [cluster["response_ids"] for cluster in normalized] == [["r01"], ["r02"]]


def test_build_cluster_messages_mentions_fb_rule_and_fallback_ids() -> None:
    rows = pd.DataFrame(
        [
            {
                "response_id": "r01",
                "run_group_id": "run_a",
                "run_id": "run_a__1",
                "answer": "Please rephrase.",
                "fallback_detected": True,
            },
            {
                "response_id": "r02",
                "run_group_id": "run_b",
                "run_id": "run_b__1",
                "answer": "Actual answer.",
                "fallback_detected": False,
            },
        ]
    )

    system_message, user_message = _build_cluster_messages(
        "arch_a",
        "p1_basic",
        "Question?",
        rows,
        ["r01"],
    )

    assert "cluster labeled exactly 'FB'" in system_message
    assert "Known fallback response_ids from run metadata: r01." in user_message
    assert "fallback_detected: true" in user_message


def test_build_cache_key_changes_when_fallback_detection_changes() -> None:
    rows_without_fallback = pd.DataFrame(
        [
            {
                "response_id": "r01",
                "run_group_id": "run_a",
                "run_id": "run_a__1",
                "fallback_detected": False,
                "answer": "Please rephrase.",
            }
        ]
    )
    rows_with_fallback = rows_without_fallback.copy()
    rows_with_fallback.loc[0, "fallback_detected"] = True

    key_without_fallback = answer_clustering._build_cache_key(
        "arch_a",
        "p1_basic",
        "Question?",
        "gpt-4o-mini",
        rows_without_fallback,
    )
    key_with_fallback = answer_clustering._build_cache_key(
        "arch_a",
        "p1_basic",
        "Question?",
        "gpt-4o-mini",
        rows_with_fallback,
    )

    assert key_without_fallback != key_with_fallback


def test_get_openai_client_loads_api_key_from_project_dotenv(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=test-from-dotenv\n", encoding="utf-8")

    captured: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(answer_clustering, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(answer_clustering, "OpenAI", FakeOpenAI)

    client = answer_clustering._get_openai_client()

    assert captured["api_key"] == "test-from-dotenv"
    assert client is not None


def test_build_review_assignments_seeds_human_review_columns() -> None:
    assignments = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_id": "r01",
                "response_index": 1,
                "run_group_id": "run_a",
                "run_id": "run_a__1",
                "answer": "Alpha",
                "cluster_id": "c1",
                "cluster_label": "Alpha cluster",
                "cluster_summary": "Alpha answer",
            }
        ]
    )

    review = build_review_assignments(assignments)

    assert review.iloc[0]["proposed_cluster_id"] == "C1"
    assert review.iloc[0]["proposed_cluster_label"] == "Alpha cluster"
    assert review.iloc[0]["proposed_cluster_reason"] == "Alpha answer"
    assert review.iloc[0]["final_cluster_id"] == "C1"
    assert review.iloc[0]["review_notes"] == ""
    assert bool(review.iloc[0]["reviewed"]) is False


def test_build_review_cluster_reference_keeps_only_reviewer_needed_context() -> None:
    cluster_summary = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "cluster_id": "c1",
                "cluster_label": "Alpha cluster",
                "cluster_summary": "Alpha answer",
                "response_count": 2,
                "response_share": 1.0,
                "response_indexes": "1, 2",
                "representative_answer": "Alpha",
            }
        ]
    )

    reference = build_review_cluster_reference(cluster_summary)

    assert reference.columns.tolist() == [
        "arch_id",
        "prompt_id",
        "prompt",
        "proposed_cluster_id",
        "proposed_cluster_label",
        "proposed_cluster_reason",
        "response_count",
        "response_share",
        "response_indexes",
        "representative_answer",
    ]
    assert reference.iloc[0]["proposed_cluster_id"] == "C1"
    assert reference.iloc[0]["proposed_cluster_label"] == "Alpha cluster"


def test_build_summaries_from_assignments_uses_reviewed_clusters() -> None:
    review = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_index": 1,
                "answer": "Alpha",
                "proposed_cluster_label": "Alpha",
                "proposed_cluster_reason": "Alpha-like answers",
                "final_cluster_id": "C1",
                "reviewed": True,
                "review_notes": "",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_index": 2,
                "answer": "Beta",
                "proposed_cluster_label": "Beta",
                "proposed_cluster_reason": "Beta-like answers",
                "final_cluster_id": "C2",
                "reviewed": True,
                "review_notes": "Moved after review",
            },
        ]
    )

    overall_summary, prompt_summary, cluster_summary = build_summaries_from_assignments(
        review,
        final_cluster_id_col="final_cluster_id",
        proposed_cluster_label_col="proposed_cluster_label",
        proposed_cluster_reason_col="proposed_cluster_reason",
        reviewed_flag_col="reviewed",
        review_notes_col="review_notes",
        result_source="human_review",
    )

    assert overall_summary.iloc[0]["prompt_count"] == 1
    assert prompt_summary.iloc[0]["cluster_count"] == 2
    assert cluster_summary["cluster_label"].tolist() == ["Alpha", "Beta"]
    assert cluster_summary["cluster_id"].tolist() == ["C1", "C2"]
    assert "Moved after review" in cluster_summary.iloc[1]["review_notes"]


def test_build_summaries_from_assignments_excludes_fb_from_consistency_metrics() -> None:
    review = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_index": 1,
                "answer": "Fallback",
                "proposed_cluster_label": "FB",
                "proposed_cluster_reason": "Fallback",
                "final_cluster_id": "FB",
                "reviewed": True,
                "review_notes": "",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_index": 2,
                "answer": "Concrete answer",
                "proposed_cluster_label": "Concrete",
                "proposed_cluster_reason": "Concrete",
                "final_cluster_id": "C1",
                "reviewed": True,
                "review_notes": "",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_index": 3,
                "answer": "Concrete answer",
                "proposed_cluster_label": "Concrete",
                "proposed_cluster_reason": "Concrete",
                "final_cluster_id": "C1",
                "reviewed": True,
                "review_notes": "",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p2_basic",
                "prompt": "Question 2?",
                "response_index": 1,
                "answer": "Fallback",
                "proposed_cluster_label": "FB",
                "proposed_cluster_reason": "Fallback",
                "final_cluster_id": "FB",
                "reviewed": True,
                "review_notes": "",
            },
        ]
    )

    overall_summary, prompt_summary, cluster_summary = build_summaries_from_assignments(
        review,
        final_cluster_id_col="final_cluster_id",
        proposed_cluster_label_col="proposed_cluster_label",
        proposed_cluster_reason_col="proposed_cluster_reason",
        reviewed_flag_col="reviewed",
        review_notes_col="review_notes",
        result_source="human_review",
    )

    p1 = prompt_summary[prompt_summary["prompt_id"] == "p1_basic"].iloc[0]
    assert p1["fallback_response_count"] == 1
    assert p1["fallback_rate"] == pytest.approx(1 / 3)
    assert p1["substantive_response_count"] == 2
    assert p1["cluster_count"] == 1
    assert p1["majority_cluster_id"] == "C1"
    assert p1["majority_cluster_share"] == pytest.approx(1.0)
    assert bool(p1["is_perfect_consensus"]) is True

    p2 = prompt_summary[prompt_summary["prompt_id"] == "p2_basic"].iloc[0]
    assert p2["fallback_rate"] == pytest.approx(1.0)
    assert p2["substantive_response_count"] == 0
    assert p2["cluster_count"] == 0
    assert p2["majority_cluster_id"] == ""
    assert pd.isna(p2["majority_cluster_share"])
    assert bool(p2["is_perfect_consensus"]) is False

    overall = overall_summary.iloc[0]
    assert overall["fallback_response_count"] == 2
    assert overall["fallback_rate"] == pytest.approx(0.5)
    assert overall["consistency_prompt_count"] == 1
    assert overall["mean_majority_cluster_share"] == pytest.approx(1.0)
    assert overall["mean_cluster_count"] == pytest.approx(0.5)
    assert overall["perfect_consensus_rate"] == pytest.approx(1.0)

    assert (
        cluster_summary[["cluster_id", "is_fallback_cluster"]].to_dict(orient="records")
        == [
            {"cluster_id": "C1", "is_fallback_cluster": False},
            {"cluster_id": "FB", "is_fallback_cluster": True},
            {"cluster_id": "FB", "is_fallback_cluster": True},
        ]
    )


def test_build_summaries_from_assignments_uses_first_non_empty_prompt_across_clusters() -> None:
    review = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "",
                "response_index": 1,
                "answer": "Alpha one",
                "proposed_cluster_label": "Alpha",
                "proposed_cluster_reason": "Alpha cluster",
                "final_cluster_id": "C1",
                "reviewed": True,
                "review_notes": "",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "",
                "response_index": 2,
                "answer": "Alpha two",
                "proposed_cluster_label": "Alpha",
                "proposed_cluster_reason": "Alpha cluster",
                "final_cluster_id": "C1",
                "reviewed": True,
                "review_notes": "",
            },
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_index": 3,
                "answer": "Beta one",
                "proposed_cluster_label": "Beta",
                "proposed_cluster_reason": "Beta cluster",
                "final_cluster_id": "C2",
                "reviewed": True,
                "review_notes": "",
            },
        ]
    )

    _, prompt_summary, _ = build_summaries_from_assignments(
        review,
        final_cluster_id_col="final_cluster_id",
        proposed_cluster_label_col="proposed_cluster_label",
        proposed_cluster_reason_col="proposed_cluster_reason",
        reviewed_flag_col="reviewed",
        review_notes_col="review_notes",
        result_source="human_review",
    )

    assert prompt_summary.iloc[0]["prompt"] == "Question?"


def test_validate_review_assignments_rejects_pending_rows() -> None:
    review = pd.DataFrame(
        [
            {
                "arch_id": "arch_a",
                "prompt_id": "p1_basic",
                "prompt": "Question?",
                "response_index": 1,
                "answer": "Alpha",
                "final_cluster_id": "C1",
                "reviewed": False,
            }
        ]
    )

    try:
        validate_review_assignments(review, allow_pending=False)
    except SystemExit as exc:
        assert "reviewed=FALSE" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected pending review validation to fail")


def test_generate_reviewed_plots_writes_expected_files(tmp_path) -> None:
    pytest.importorskip("matplotlib")

    overall_summary = pd.DataFrame(
        [
            {
                "arch_id": "agentic_architecture",
                "mean_majority_cluster_share": 0.90,
                "perfect_consensus_rate": 0.80,
                "mean_cluster_count": 1.3,
                "fallback_rate": 0.10,
            },
            {
                "arch_id": "graph_based_architecture",
                "mean_majority_cluster_share": 0.75,
                "perfect_consensus_rate": 0.40,
                "mean_cluster_count": 1.9,
                "fallback_rate": 0.30,
            },
        ]
    )
    prompt_summary = pd.DataFrame(
        [
            {
                "arch_id": "agentic_architecture",
                "prompt_id": "p1_basic",
                "majority_cluster_share": 1.0,
                "cluster_count": 1,
                "fallback_rate": 0.0,
            },
            {
                "arch_id": "graph_based_architecture",
                "prompt_id": "p1_basic",
                "majority_cluster_share": 0.8,
                "cluster_count": 2,
                "fallback_rate": 0.2,
            },
            {
                "arch_id": "agentic_architecture",
                "prompt_id": "p6_intermediate",
                "majority_cluster_share": 0.9,
                "cluster_count": 1,
                "fallback_rate": 0.1,
            },
            {
                "arch_id": "graph_based_architecture",
                "prompt_id": "p6_intermediate",
                "majority_cluster_share": 0.6,
                "cluster_count": 3,
                "fallback_rate": 0.4,
            },
            {
                "arch_id": "agentic_architecture",
                "prompt_id": "p11_complex",
                "majority_cluster_share": 0.85,
                "cluster_count": 2,
                "fallback_rate": 0.2,
            },
            {
                "arch_id": "graph_based_architecture",
                "prompt_id": "p11_complex",
                "majority_cluster_share": 0.5,
                "cluster_count": 4,
                "fallback_rate": 0.3,
            },
        ]
    )

    written_paths = generate_plots(
        tmp_path,
        overall_summary,
        prompt_summary,
        plot_format="png",
        dpi=90,
    )

    assert {path.name for path in written_paths} == {
        "RQ3_clustering_reviewed_overall_summary.png",
        "RQ3_clustering_reviewed_prompt_majority_share.png",
        "RQ3_clustering_reviewed_prompt_cluster_count.png",
        "RQ3_clustering_reviewed_prompt_fallback_rate.png",
        "RQ3_clustering_reviewed_majority_share_heatmap.png",
        "RQ3_clustering_reviewed_difficulty_summary.png",
        "RQ3_clustering_reviewed_difficulty_fallback_rate.png",
    }
