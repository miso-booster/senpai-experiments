import re
from typing import Iterable

import pandas as pd


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


def _prompt_sort_key(value: object) -> tuple[int, str]:
    text = "" if value is None else str(value).strip().lower()
    match = re.fullmatch(r"p(\d+)(?:_(.+))?", text)
    if not match:
        return (10**9, text)
    return (int(match.group(1)), text)


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y", "x"}


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
        key=lambda s: s.map(_prompt_sort_key) if s.name == "prompt_id" else s,
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
        key=lambda s: s.map(_prompt_sort_key) if s.name == "prompt_id" else s,
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
        normalized["reviewed"] = normalized[reviewed_flag_col].map(_to_bool)
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
        key=lambda item: (str(item[0][0]), _prompt_sort_key(item[0][1]), str(item[0][2])),
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
        key=lambda item: (str(item[0][0]), _prompt_sort_key(item[0][1])),
    ):
        records.sort(key=lambda row: (-int(row["response_count"]), str(row["cluster_id"])))

        majority = records[0]
        prompt_rows.append(
            {
                "arch_id": arch_id,
                "prompt_id": prompt_id,
                "prompt": majority["prompt"],
                "total_responses": prompt_totals[(arch_id, prompt_id)],
                "cluster_count": len(records),
                "majority_cluster_id": majority["cluster_id"],
                "majority_cluster_label": majority["cluster_label"],
                "majority_cluster_size": majority["response_count"],
                "majority_cluster_share": majority["response_share"],
                "is_perfect_consensus": len(records) == 1,
                "cluster_breakdown": " | ".join(
                    f"{row['cluster_id']}={row['response_count']} ({row['cluster_label']})"
                    for row in records
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
    overall_summary["perfect_consensus_rate"] = (
        overall_summary["perfect_consensus_prompts"] / overall_summary["prompt_count"]
    )
    overall_summary["result_source"] = result_source

    return overall_summary, prompt_summary, cluster_summary
