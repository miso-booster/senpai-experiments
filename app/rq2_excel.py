from pathlib import Path

import pandas as pd


def _has_metric_family(row_summary: pd.DataFrame, metric_prefix: str) -> bool:
    """Return True when row_summary contains columns for the given metric family."""
    prefix = f"{metric_prefix}__"
    return any(col.startswith(prefix) for col in row_summary.columns)


def _build_metric_sheet(
    row_summary: pd.DataFrame,
    *,
    metric_prefix: str,
    value_name_prefix: str,
    unit_suffix: str = "",
) -> pd.DataFrame:
    """Create a compact architecture-level sheet for one RQ2 metric family."""
    rows = []
    for _, r in row_summary.iterrows():
        rows.append(
            {
                "arch_id": r.get("arch_id"),
                "n_responses": r.get("n_rows"),
                "n_runs": r.get("n_executions"),
                f"{value_name_prefix}_avg{unit_suffix}": r.get(f"{metric_prefix}__mean"),
                f"{value_name_prefix}_std{unit_suffix}": r.get(f"{metric_prefix}__std"),
                f"{value_name_prefix}_p25{unit_suffix}": r.get(f"{metric_prefix}__p25"),
                f"{value_name_prefix}_median{unit_suffix}": r.get(f"{metric_prefix}__median"),
                f"{value_name_prefix}_p75{unit_suffix}": r.get(f"{metric_prefix}__p75"),
            }
        )
    return pd.DataFrame(rows)


def save_outputs(
    out_dir: Path,
    all_rows: pd.DataFrame,
    filtered_rows: pd.DataFrame,
    row_summary: pd.DataFrame,
    per_exec_arch: pd.DataFrame,
    exec_summary: pd.DataFrame,
    run_inventory: pd.DataFrame,
    fallback_summary: pd.DataFrame,
    yaml_validity_summary: pd.DataFrame,
    missing_metrics: list[str],
    export_csvs: bool,
    detailed_sheets: bool,
) -> None:
    """Write the RQ2 workbook and optional CSV exports.

    Parameters
    ----------
    out_dir:
        Destination directory for workbook, plots, and optional CSV files.
    all_rows, filtered_rows:
        Raw concatenated rows and the subset used for metrics/plots.
    row_summary, per_exec_arch, exec_summary, run_inventory:
        Precomputed summaries produced by the aggregation pipeline.
    fallback_summary, yaml_validity_summary:
        Optional quality/reliability summaries; empty dataframes are skipped.
    missing_metrics:
        Metric column names expected by RQ2 but not present in the input data.
    export_csvs:
        When True, also export CSV versions of the summary tables.
    detailed_sheets:
        When True, include additional detailed sheets beyond the compact defaults.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if export_csvs:
        all_rows.to_csv(out_dir / "combined_rows_all.csv", index=False)
        filtered_rows.to_csv(out_dir / "combined_rows_filtered.csv", index=False)
        row_summary.to_csv(out_dir / "summary_per_response.csv", index=False)
        per_exec_arch.to_csv(out_dir / "summary_per_execution_architecture.csv", index=False)
        exec_summary.to_csv(out_dir / "summary_across_executions.csv", index=False)
        run_inventory.to_csv(out_dir / "run_inventory.csv", index=False)
        if not fallback_summary.empty:
            fallback_summary.to_csv(out_dir / "summary_fallback.csv", index=False)
        if not yaml_validity_summary.empty:
            yaml_validity_summary.to_csv(out_dir / "summary_yaml_validity.csv", index=False)
        if missing_metrics:
            pd.DataFrame({"missing_metric": missing_metrics}).to_csv(
                out_dir / "missing_metrics.csv", index=False
            )

    metric_sheets: list[tuple[str, pd.DataFrame]] = []
    if _has_metric_family(row_summary, "latency_s"):
        metric_sheets.append(
            (
                "response_time",
                _build_metric_sheet(
                    row_summary,
                    metric_prefix="latency_s",
                    value_name_prefix="response_time",
                    unit_suffix="_s",
                ),
            )
        )
    if _has_metric_family(row_summary, "total_input_tokens"):
        metric_sheets.append(
            (
                "input_tokens",
                _build_metric_sheet(
                    row_summary,
                    metric_prefix="total_input_tokens",
                    value_name_prefix="input_tokens",
                ),
            )
        )
    if _has_metric_family(row_summary, "llm_call_count"):
        metric_sheets.append(
            (
                "llm_calls",
                _build_metric_sheet(
                    row_summary,
                    metric_prefix="llm_call_count",
                    value_name_prefix="llm_calls",
                ),
            )
        )

    with pd.ExcelWriter(out_dir / "RQ2_architecture_metrics.xlsx", engine="openpyxl") as writer:
        for sheet_name, df in metric_sheets:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
        if not fallback_summary.empty:
            fallback_summary.to_excel(writer, index=False, sheet_name="fallback")
        if not yaml_validity_summary.empty:
            yaml_validity_summary.to_excel(writer, index=False, sheet_name="yaml_validity")
        if missing_metrics:
            pd.DataFrame(
                {
                    "missing_metric": missing_metrics,
                    "note": [
                        "Sheet not generated because this column was not present in the aggregated inputs."
                    ]
                    * len(missing_metrics),
                }
            ).to_excel(writer, index=False, sheet_name="missing_metrics")
        if detailed_sheets:
            row_summary.to_excel(writer, index=False, sheet_name="per_response_summary")
            exec_summary.to_excel(writer, index=False, sheet_name="across_executions_summary")
            per_exec_arch.to_excel(writer, index=False, sheet_name="per_execution_arch")
            run_inventory.to_excel(writer, index=False, sheet_name="run_inventory")
            filtered_rows.to_excel(writer, index=False, sheet_name="raw_rows_filtered")
