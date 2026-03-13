from pathlib import Path

import pandas as pd


def save_outputs(
    out_dir: Path,
    overall_summary: pd.DataFrame,
    prompt_summary: pd.DataFrame,
    run_level: pd.DataFrame,
    tool_presence: pd.DataFrame,
    *,
    graph_overall_summary: pd.DataFrame | None = None,
    graph_prompt_summary: pd.DataFrame | None = None,
    graph_run_level: pd.DataFrame | None = None,
    graph_presence: pd.DataFrame | None = None,
    export_csvs: bool,
) -> Path:
    """Write the RQ3 workbook and optional CSV exports."""
    out_dir.mkdir(parents=True, exist_ok=True)

    graph_overall_summary = graph_overall_summary if graph_overall_summary is not None else pd.DataFrame()
    graph_prompt_summary = graph_prompt_summary if graph_prompt_summary is not None else pd.DataFrame()
    graph_run_level = graph_run_level if graph_run_level is not None else pd.DataFrame()
    graph_presence = graph_presence if graph_presence is not None else pd.DataFrame()

    if export_csvs:
        overall_summary.to_csv(out_dir / "rq3_tool_consistency_overall_summary.csv", index=False)
        prompt_summary.to_csv(out_dir / "rq3_tool_consistency_prompt_summary.csv", index=False)
        run_level.to_csv(out_dir / "rq3_tool_consistency_per_run.csv", index=False)
        tool_presence.to_csv(out_dir / "rq3_tool_consistency_presence.csv", index=False)

        graph_overall_summary.to_csv(out_dir / "rq3_graph_consistency_overall_summary.csv", index=False)
        graph_prompt_summary.to_csv(out_dir / "rq3_graph_consistency_prompt_summary.csv", index=False)
        graph_run_level.to_csv(out_dir / "rq3_graph_consistency_per_run.csv", index=False)
        graph_presence.to_csv(out_dir / "rq3_graph_consistency_presence.csv", index=False)

    workbook_path = out_dir / "RQ3_tool_consistency_and_graph_consistency.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        overall_summary.to_excel(writer, index=False, sheet_name="overall_summary")
        prompt_summary.to_excel(writer, index=False, sheet_name="prompt_consistency")
        run_level.to_excel(writer, index=False, sheet_name="tool_sequences_per_run")
        tool_presence.to_excel(writer, index=False, sheet_name="tool_presence")

        graph_overall_summary.to_excel(writer, index=False, sheet_name="graph_overall_summary")
        graph_prompt_summary.to_excel(writer, index=False, sheet_name="graph_prompt_consistency")
        graph_run_level.to_excel(writer, index=False, sheet_name="graph_node_sequences")
        graph_presence.to_excel(writer, index=False, sheet_name="graph_node_presence")

    return workbook_path
