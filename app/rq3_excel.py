from pathlib import Path

import pandas as pd


def save_outputs(
    out_dir: Path,
    overall_summary: pd.DataFrame,
    prompt_summary: pd.DataFrame,
    run_level: pd.DataFrame,
    tool_presence: pd.DataFrame,
    export_csvs: bool,
) -> Path:
    """Write the RQ3 workbook and optional CSV exports."""
    out_dir.mkdir(parents=True, exist_ok=True)

    if export_csvs:
        overall_summary.to_csv(out_dir / "rq3_overall_summary.csv", index=False)
        prompt_summary.to_csv(out_dir / "rq3_prompt_consistency_summary.csv", index=False)
        run_level.to_csv(out_dir / "rq3_tool_sequences_per_run.csv", index=False)
        tool_presence.to_csv(out_dir / "rq3_tool_presence_by_prompt.csv", index=False)

    workbook_path = out_dir / "RQ3_tool_consistency.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        overall_summary.to_excel(writer, index=False, sheet_name="overall_summary")
        prompt_summary.to_excel(writer, index=False, sheet_name="prompt_consistency")
        run_level.to_excel(writer, index=False, sheet_name="tool_sequences_per_run")
        tool_presence.to_excel(writer, index=False, sheet_name="tool_presence")

    return workbook_path
