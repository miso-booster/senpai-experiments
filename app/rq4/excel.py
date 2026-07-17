from pathlib import Path

import pandas as pd


def _split_pairwise_effect_exports(pairwise_summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split the combined pairwise table into Wilcoxon-only and A12-only exports."""
    if pairwise_summary.empty:
        return pd.DataFrame(), pd.DataFrame()

    a12_columns = [
        "a12_arch_a_over_arch_b",
        "a12_arch_b_over_arch_a",
        "a12_magnitude",
    ]
    base_columns = [col for col in pairwise_summary.columns if col not in a12_columns]
    id_columns = [
        col
        for col in ("model_label", "arch_a", "arch_b", "metric")
        if col in pairwise_summary.columns
    ]
    a12_export_columns = id_columns + [col for col in a12_columns if col in pairwise_summary.columns]

    wilcoxon_df = pairwise_summary[base_columns].copy()
    a12_df = pairwise_summary[a12_export_columns].copy() if a12_export_columns else pd.DataFrame()
    return wilcoxon_df, a12_df


def save_outputs(
    out_dir: Path,
    enriched_rows: pd.DataFrame,
    architecture_summary: pd.DataFrame,
    prompt_arch_summary: pd.DataFrame,
    middleware_summary: pd.DataFrame,
    run_inventory: pd.DataFrame,
    pairwise_wilcoxon_summary: pd.DataFrame,
    prompt_catalog: pd.DataFrame,
    export_csvs: bool,
    detailed_sheets: bool,
) -> None:
    """Write the RQ4 workbook and optional CSV exports."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pairwise_wilcoxon_export, pairwise_a12_export = _split_pairwise_effect_exports(pairwise_wilcoxon_summary)

    if export_csvs:
        enriched_rows.to_csv(out_dir / "rq4_enriched_rows.csv", index=False)
        architecture_summary.to_csv(out_dir / "rq4_architecture_summary.csv", index=False)
        prompt_arch_summary.to_csv(out_dir / "rq4_prompt_arch_summary.csv", index=False)
        run_inventory.to_csv(out_dir / "rq4_run_inventory.csv", index=False)
        prompt_catalog.to_csv(out_dir / "rq4_prompt_catalog.csv", index=False)
        if not middleware_summary.empty:
            middleware_summary.to_csv(out_dir / "rq4_middleware_summary.csv", index=False)
        if not pairwise_wilcoxon_export.empty:
            pairwise_wilcoxon_export.to_csv(out_dir / "rq4_pairwise_wilcoxon.csv", index=False)
        if not pairwise_a12_export.empty:
            pairwise_a12_export.to_csv(out_dir / "rq4_pairwise_a12.csv", index=False)

    with pd.ExcelWriter(out_dir / "RQ4_guardrail_metrics.xlsx", engine="openpyxl") as writer:
        architecture_summary.to_excel(writer, index=False, sheet_name="architecture_summary")
        prompt_arch_summary.to_excel(writer, index=False, sheet_name="prompt_arch_summary")
        prompt_catalog.to_excel(writer, index=False, sheet_name="prompt_catalog")
        run_inventory.to_excel(writer, index=False, sheet_name="run_inventory")
        if not middleware_summary.empty:
            middleware_summary.to_excel(writer, index=False, sheet_name="middleware_summary")
        if not pairwise_wilcoxon_export.empty:
            pairwise_wilcoxon_export.to_excel(writer, index=False, sheet_name="pairwise_wilcoxon")
        if not pairwise_a12_export.empty:
            pairwise_a12_export.to_excel(writer, index=False, sheet_name="pairwise_a12")
        if detailed_sheets:
            enriched_rows.to_excel(writer, index=False, sheet_name="raw_rows_enriched")
