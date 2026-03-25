from typing import Iterable

import pandas as pd

try:
    from .utils import prompt_sort_key, to_bool
except ImportError:  # Supports direct execution
    from utils import prompt_sort_key, to_bool


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _first_non_empty(values: Iterable[object]) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""
def build_review_assignments(cluster_assignments: pd.DataFrame) -> pd.DataFrame:
    if cluster_assignments.empty:
        return pd.DataFrame()

    review = cluster_assignments.copy()
    review["proposed_cluster_id"] = review["cluster_id"].astype("string").str.upper()
    review["proposed_cluster_label"] = review["cluster_label"]
    review["proposed_cluster_reason"] = review["cluster_summary"]
    review["final_cluster_id"] = review["proposed_cluster_id"]
    review["reviewed"] = False
    review["review_notes"] = ""

    preferred_columns = [
        "arch_id",
        "prompt_id",
        "prompt",
        "response_index",
        "answer",
        "proposed_cluster_id",
        "proposed_cluster_label",
        "proposed_cluster_reason",
        "final_cluster_id",
        "reviewed",
        "review_notes",
    ]
    review = review[preferred_columns].copy()
    review = review.sort_values(
        ["arch_id", "prompt_id", "response_index"],
        key=lambda s: s.map(prompt_sort_key) if s.name == "prompt_id" else s,
        kind="stable",
    ).reset_index(drop=True)
    return review


def build_review_cluster_reference(cluster_summary: pd.DataFrame) -> pd.DataFrame:
    if cluster_summary.empty:
        return pd.DataFrame()

    reference = cluster_summary.copy()
    reference["proposed_cluster_id"] = reference["cluster_id"].astype("string").str.upper()
    reference["proposed_cluster_label"] = reference["cluster_label"]
    reference["proposed_cluster_reason"] = reference["cluster_summary"]
    preferred_columns = [
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
    reference = reference[[column for column in preferred_columns if column in reference.columns]].copy()
    reference = reference.sort_values(
        ["arch_id", "prompt_id", "response_count"],
        key=lambda s: s.map(prompt_sort_key) if s.name == "prompt_id" else s,
        ascending=[True, True, False],
        kind="stable",
    ).reset_index(drop=True)
    return reference


def build_summaries_from_assignments(
    assignments: pd.DataFrame,
    *,
    final_cluster_id_col: str,
    proposed_cluster_label_col: str | None,
    proposed_cluster_reason_col: str | None,
    reviewed_flag_col: str | None,
    review_notes_col: str | None,
    result_source: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if assignments.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    required = {
        "arch_id",
        "prompt_id",
        "prompt",
        "response_index",
        "answer",
        final_cluster_id_col,
    }
    missing = sorted(column for column in required if column not in assignments.columns)
    if missing:
        raise ValueError(f"Missing required columns for summarization: {', '.join(missing)}")

    normalized = assignments.copy()
    normalized["final_cluster_id"] = (
        normalized[final_cluster_id_col].astype("string").fillna("").str.strip().str.upper()
    )
    normalized = normalized[normalized["final_cluster_id"] != ""].copy()
    if normalized.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    if proposed_cluster_label_col and proposed_cluster_label_col in normalized.columns:
        normalized["proposed_cluster_label"] = (
            normalized[proposed_cluster_label_col].astype("string").fillna("").str.strip()
        )
    else:
        normalized["proposed_cluster_label"] = ""

    if proposed_cluster_reason_col and proposed_cluster_reason_col in normalized.columns:
        normalized["proposed_cluster_reason"] = (
            normalized[proposed_cluster_reason_col].astype("string").fillna("").str.strip()
        )
    else:
        normalized["proposed_cluster_reason"] = ""

    if reviewed_flag_col and reviewed_flag_col in normalized.columns:
        normalized["reviewed"] = normalized[reviewed_flag_col].map(to_bool)
    else:
        normalized["reviewed"] = False

    if review_notes_col and review_notes_col in normalized.columns:
        normalized["review_notes"] = normalized[review_notes_col].astype("string").fillna("").str.strip()
    else:
        normalized["review_notes"] = ""

    prompt_totals = (
        normalized.groupby(["arch_id", "prompt_id"], dropna=False)["response_index"]
        .size()
        .to_dict()
    )

    cluster_rows: list[dict[str, object]] = []
    prompt_rows: list[dict[str, object]] = []

    grouped = sorted(
        normalized.groupby(["arch_id", "prompt_id", "final_cluster_id"], dropna=False),
        key=lambda item: (str(item[0][0]), prompt_sort_key(item[0][1]), str(item[0][2])),
    )
    cluster_records_by_prompt: dict[tuple[str, str], list[dict[str, object]]] = {}

    for (arch_id, prompt_id, final_cluster_id), group in grouped:
        prompt_text = _first_non_empty(group["prompt"].tolist())
        total_responses = prompt_totals[(arch_id, prompt_id)]
        ordered = group.sort_values(["response_index"], kind="stable")
        response_indexes = [int(value) for value in ordered["response_index"].tolist()]
        review_notes = " | ".join(note for note in ordered["review_notes"].astype(str).tolist() if note)
        unique_labels = [label for label in ordered["proposed_cluster_label"].dropna().astype(str).unique().tolist() if label]
        unique_reasons = [reason for reason in ordered["proposed_cluster_reason"].dropna().astype(str).unique().tolist() if reason]
        cluster_label = unique_labels[0] if len(unique_labels) == 1 else str(final_cluster_id)
        cluster_reason = unique_reasons[0] if len(unique_reasons) == 1 else ""

        record = {
            "arch_id": arch_id,
            "prompt_id": prompt_id,
            "prompt": prompt_text,
            "cluster_id": _clean_text(final_cluster_id),
            "is_fallback_cluster": _clean_text(final_cluster_id).upper() == "FB",
            "cluster_label": cluster_label,
            "cluster_summary": cluster_reason,
            "response_count": len(ordered),
            "response_share": len(ordered) / total_responses,
            "response_indexes": ", ".join(str(value) for value in response_indexes),
            "representative_response_index": response_indexes[0],
            "representative_answer": _clean_text(ordered.iloc[0]["answer"]),
            "reviewed_count": int(ordered["reviewed"].sum()),
            "review_notes": review_notes,
            "result_source": result_source,
        }
        cluster_rows.append(record)
        cluster_records_by_prompt.setdefault((arch_id, prompt_id), []).append(record)

    for (arch_id, prompt_id), records in sorted(
        cluster_records_by_prompt.items(),
        key=lambda item: (str(item[0][0]), prompt_sort_key(item[0][1])),
    ):
        records.sort(key=lambda row: (-int(row["response_count"]), str(row["cluster_id"])))
        prompt_text = _first_non_empty(row["prompt"] for row in records)
        non_fallback_records = [row for row in records if not bool(row["is_fallback_cluster"])]
        fallback_response_count = sum(
            int(row["response_count"]) for row in records if bool(row["is_fallback_cluster"])
        )
        total_responses = prompt_totals[(arch_id, prompt_id)]
        substantive_response_count = total_responses - fallback_response_count
        majority = non_fallback_records[0] if non_fallback_records else None
        prompt_rows.append(
            {
                "arch_id": arch_id,
                "prompt_id": prompt_id,
                "prompt": prompt_text,
                "total_responses": total_responses,
                "fallback_response_count": fallback_response_count,
                "fallback_rate": (
                    fallback_response_count / total_responses if total_responses else 0.0
                ),
                "substantive_response_count": substantive_response_count,
                "cluster_count": len(non_fallback_records),
                "majority_cluster_id": majority["cluster_id"] if majority else "",
                "majority_cluster_label": majority["cluster_label"] if majority else "",
                "majority_cluster_size": int(majority["response_count"]) if majority else 0,
                "majority_cluster_share": (
                    int(majority["response_count"]) / substantive_response_count
                    if majority and substantive_response_count > 0
                    else pd.NA
                ),
                "is_perfect_consensus": (
                    len(non_fallback_records) == 1 and substantive_response_count > 0
                ),
                "has_substantive_answers": substantive_response_count > 0,
                "cluster_breakdown": " | ".join(
                    f"{row['cluster_id']}={row['response_count']} ({row['cluster_label']})"
                    for row in records
                ),
                "substantive_cluster_breakdown": " | ".join(
                    f"{row['cluster_id']}={row['response_count']} ({row['cluster_label']})"
                    for row in non_fallback_records
                ),
                "reviewed_response_count": int(
                    normalized[
                        (normalized["arch_id"] == arch_id) & (normalized["prompt_id"] == prompt_id)
                    ]["reviewed"].sum()
                ),
                "result_source": result_source,
            }
        )

    prompt_summary = pd.DataFrame(prompt_rows)
    cluster_summary = pd.DataFrame(cluster_rows)

    overall_summary = (
        prompt_summary.groupby("arch_id", dropna=False)
        .agg(
            prompt_count=("prompt_id", "nunique"),
            total_responses=("total_responses", "sum"),
            fallback_response_count=("fallback_response_count", "sum"),
            substantive_response_count=("substantive_response_count", "sum"),
            consistency_prompt_count=("has_substantive_answers", "sum"),
            mean_majority_cluster_share=("majority_cluster_share", "mean"),
            median_majority_cluster_share=("majority_cluster_share", "median"),
            mean_cluster_count=("cluster_count", "mean"),
            perfect_consensus_prompts=("is_perfect_consensus", "sum"),
            reviewed_response_count=("reviewed_response_count", "sum"),
        )
        .reset_index()
        .sort_values("arch_id", kind="stable")
        .reset_index(drop=True)
    )
    overall_summary["fallback_rate"] = (
        overall_summary["fallback_response_count"] / overall_summary["total_responses"]
    )
    overall_summary["perfect_consensus_rate"] = (
        overall_summary["perfect_consensus_prompts"]
        / overall_summary["consistency_prompt_count"].where(
            overall_summary["consistency_prompt_count"] > 0,
            pd.NA,
        )
    )
    overall_summary["result_source"] = result_source

    return overall_summary, prompt_summary, cluster_summary
