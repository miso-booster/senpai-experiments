from pathlib import Path

import pandas as pd


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

    if export_csvs:
        enriched_rows.to_csv(out_dir / "rq4_enriched_rows.csv", index=False)
        architecture_summary.to_csv(out_dir / "rq4_architecture_summary.csv", index=False)
        prompt_arch_summary.to_csv(out_dir / "rq4_prompt_arch_summary.csv", index=False)
        run_inventory.to_csv(out_dir / "rq4_run_inventory.csv", index=False)
        prompt_catalog.to_csv(out_dir / "rq4_prompt_catalog.csv", index=False)
        if not middleware_summary.empty:
            middleware_summary.to_csv(out_dir / "rq4_middleware_summary.csv", index=False)
        if not pairwise_wilcoxon_summary.empty:
            pairwise_wilcoxon_summary.to_csv(out_dir / "rq4_pairwise_wilcoxon.csv", index=False)

    with pd.ExcelWriter(out_dir / "RQ4_guardrail_metrics.xlsx", engine="openpyxl") as writer:
        architecture_summary.to_excel(writer, index=False, sheet_name="architecture_summary")
        prompt_arch_summary.to_excel(writer, index=False, sheet_name="prompt_arch_summary")
        prompt_catalog.to_excel(writer, index=False, sheet_name="prompt_catalog")
        run_inventory.to_excel(writer, index=False, sheet_name="run_inventory")
        if not middleware_summary.empty:
            middleware_summary.to_excel(writer, index=False, sheet_name="middleware_summary")
        if not pairwise_wilcoxon_summary.empty:
            pairwise_wilcoxon_summary.to_excel(writer, index=False, sheet_name="pairwise_wilcoxon")
        if detailed_sheets:
            enriched_rows.to_excel(writer, index=False, sheet_name="raw_rows_enriched")
