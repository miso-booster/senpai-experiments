from pathlib import Path

import pandas as pd


def _build_metric_sheet(
    row_summary: pd.DataFrame,
    *,
    metric_prefix: str,
    value_name_prefix: str,
    unit_suffix: str = "",
) -> pd.DataFrame:
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
    export_csvs: bool,
    detailed_sheets: bool,
) -> None:
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

    response_time_summary = _build_metric_sheet(
        row_summary,
        metric_prefix="latency_s",
        value_name_prefix="response_time",
        unit_suffix="_s",
    )
    input_tokens_summary = _build_metric_sheet(
        row_summary,
        metric_prefix="total_input_tokens",
        value_name_prefix="input_tokens",
    )
    llm_calls_summary = _build_metric_sheet(
        row_summary,
        metric_prefix="llm_call_count",
        value_name_prefix="llm_calls",
    )

    with pd.ExcelWriter(out_dir / "RQ2_architecture_metrics.xlsx", engine="openpyxl") as writer:
        response_time_summary.to_excel(writer, index=False, sheet_name="response_time")
        input_tokens_summary.to_excel(writer, index=False, sheet_name="input_tokens")
        llm_calls_summary.to_excel(writer, index=False, sheet_name="llm_calls")
        if not fallback_summary.empty:
            fallback_summary.to_excel(writer, index=False, sheet_name="fallback")
        if not yaml_validity_summary.empty:
            yaml_validity_summary.to_excel(writer, index=False, sheet_name="yaml_validity")
        if detailed_sheets:
            row_summary.to_excel(writer, index=False, sheet_name="per_response_summary")
            exec_summary.to_excel(writer, index=False, sheet_name="across_executions_summary")
            per_exec_arch.to_excel(writer, index=False, sheet_name="per_execution_arch")
            run_inventory.to_excel(writer, index=False, sheet_name="run_inventory")
            filtered_rows.to_excel(writer, index=False, sheet_name="raw_rows_filtered")
