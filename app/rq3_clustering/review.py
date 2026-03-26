from itertools import combinations
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

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


def compute_a12(x: pd.Series, y: pd.Series) -> float:
    """Compute Vargha-Delaney A12 for two numeric samples."""
    x_vals = pd.to_numeric(x, errors="coerce").dropna().to_numpy(dtype=float)
    y_vals = pd.to_numeric(y, errors="coerce").dropna().to_numpy(dtype=float)
    if len(x_vals) == 0 or len(y_vals) == 0:
        return float("nan")

    diff = x_vals[:, None] - y_vals[None, :]
    wins = float((diff > 0).sum())
    ties = float((diff == 0).sum())
    return (wins + 0.5 * ties) / (len(x_vals) * len(y_vals))


def classify_a12_magnitude(a12: float) -> str:
    """Return an effect-size label for A12."""
    if pd.isna(a12):
        return "n/a"
    dominance = max(float(a12), 1.0 - float(a12))
    if dominance < 0.56:
        return "negligible"
    if dominance < 0.64:
        return "small"
    if dominance < 0.71:
        return "medium"
    return "large"
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
                    else 0.0
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


def build_pairwise_wilcoxon_summary(prompt_summary: pd.DataFrame) -> pd.DataFrame:
    """Run paired Wilcoxon signed-rank tests on prompt-level reviewed metrics."""
    if prompt_summary.empty:
        return pd.DataFrame()

    required = {"arch_id", "prompt_id"}
    if not required.issubset(prompt_summary.columns):
        return pd.DataFrame()

    metric_map = {
        "mean_majority_cluster_share": "majority_cluster_share",
        "perfect_consensus_rate": "is_perfect_consensus",
        "mean_cluster_count": "cluster_count",
        "fallback_rate": "fallback_rate",
    }

    arch_tables: dict[str, pd.DataFrame] = {}
    for arch_id, group in prompt_summary.groupby("arch_id", sort=True):
        numeric_group = group[["prompt_id"] + list(metric_map.values())].copy()
        for column in metric_map.values():
            numeric_group[column] = pd.to_numeric(numeric_group[column], errors="coerce")
        arch_tables[str(arch_id)] = (
            numeric_group.groupby("prompt_id", dropna=False, as_index=False)[list(metric_map.values())]
            .mean()
            .reset_index(drop=True)
        )

    rows: list[dict[str, float | int | str]] = []
    for arch_a, arch_b in combinations(sorted(arch_tables), 2):
        merged = arch_tables[arch_a].merge(
            arch_tables[arch_b],
            on="prompt_id",
            how="inner",
            suffixes=("_a", "_b"),
        )
        for overall_metric, prompt_metric in metric_map.items():
            values = merged[[f"{prompt_metric}_a", f"{prompt_metric}_b"]].dropna().reset_index(drop=True)
            if values.empty:
                rows.append(
                    {
                        "arch_a": arch_a,
                        "arch_b": arch_b,
                        "overall_metric": overall_metric,
                        "prompt_metric": prompt_metric,
                        "n_pairs": 0,
                        "n_nonzero_pairs": 0,
                        "arch_a_mean": float("nan"),
                        "arch_a_median": float("nan"),
                        "arch_b_mean": float("nan"),
                        "arch_b_median": float("nan"),
                        "mean_difference_a_minus_b": float("nan"),
                        "median_difference_a_minus_b": float("nan"),
                        "arch_a_lt_arch_b_count": 0,
                        "arch_a_gt_arch_b_count": 0,
                        "tie_count": 0,
                        "wilcoxon_statistic": float("nan"),
                        "p_value": float("nan"),
                        "a12_arch_a_over_arch_b": float("nan"),
                        "a12_arch_b_over_arch_a": float("nan"),
                        "a12_magnitude": "n/a",
                        "notes": "no matched non-null prompt pairs",
                    }
                )
                continue

            diffs = values[f"{prompt_metric}_a"] - values[f"{prompt_metric}_b"]
            a12 = compute_a12(values[f"{prompt_metric}_a"], values[f"{prompt_metric}_b"])
            note = ""
            if diffs.eq(0).all():
                statistic = 0.0
                p_value = 1.0
                note = "all paired differences are zero"
            else:
                result = wilcoxon(
                    values[f"{prompt_metric}_a"],
                    values[f"{prompt_metric}_b"],
                    alternative="two-sided",
                    zero_method="wilcox",
                    method="auto",
                )
                statistic = float(result.statistic)
                p_value = float(result.pvalue)

            rows.append(
                {
                    "arch_a": arch_a,
                    "arch_b": arch_b,
                    "overall_metric": overall_metric,
                    "prompt_metric": prompt_metric,
                    "n_pairs": int(len(values)),
                    "n_nonzero_pairs": int((diffs != 0).sum()),
                    "arch_a_mean": float(values[f"{prompt_metric}_a"].mean()),
                    "arch_a_median": float(values[f"{prompt_metric}_a"].median()),
                    "arch_b_mean": float(values[f"{prompt_metric}_b"].mean()),
                    "arch_b_median": float(values[f"{prompt_metric}_b"].median()),
                    "mean_difference_a_minus_b": float(diffs.mean()),
                    "median_difference_a_minus_b": float(diffs.median()),
                    "arch_a_lt_arch_b_count": int((diffs < 0).sum()),
                    "arch_a_gt_arch_b_count": int((diffs > 0).sum()),
                    "tie_count": int((diffs == 0).sum()),
                    "wilcoxon_statistic": statistic,
                    "p_value": p_value,
                    "a12_arch_a_over_arch_b": float(a12),
                    "a12_arch_b_over_arch_a": float(1.0 - a12) if not pd.isna(a12) else float("nan"),
                    "a12_magnitude": classify_a12_magnitude(a12),
                    "notes": note,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["significant_p_lt_0_05"] = pd.to_numeric(out["p_value"], errors="coerce") < 0.05
    return out.sort_values(["overall_metric", "arch_a", "arch_b"]).reset_index(drop=True)
