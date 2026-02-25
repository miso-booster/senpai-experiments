import argparse
from pathlib import Path

try:
    from app.rq3_excel import save_outputs
    from app.rq3_plots import generate_plots
    from app.rq3_tool_consistency import (
        DEFAULT_OUT_DIR,
        DEFAULT_RUNS_DIR,
        build_overall_summary,
        build_prompt_consistency_summary,
        build_run_level_table,
        build_tool_presence_table,
        discover_tracing_workbooks,
        extract_prompt_run_sequences,
        load_tracing_workbook,
    )
except ModuleNotFoundError:  # Supports `python app/rq3.py`
    from rq3_excel import save_outputs
    from rq3_plots import generate_plots
    from rq3_tool_consistency import (
        DEFAULT_OUT_DIR,
        DEFAULT_RUNS_DIR,
        build_overall_summary,
        build_prompt_consistency_summary,
        build_run_level_table,
        build_tool_presence_table,
        discover_tracing_workbooks,
        extract_prompt_run_sequences,
        load_tracing_workbook,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full RQ3 pipeline (generate workbook + plots)."
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Directory containing repeated run folders (default: {DEFAULT_RUNS_DIR})",
    )
    parser.add_argument(
        "--trace-glob",
        default="*/tracing_*.xlsx",
        help="Glob relative to runs-dir used to discover tracing workbooks (default: */tracing_*.xlsx)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory for workbook and plots (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--sheet",
        help="Optional sheet name in each tracing workbook (default: first sheet)",
    )
    parser.add_argument(
        "--export-csvs",
        action="store_true",
        help="Also export CSV files in addition to the workbook",
    )
    parser.add_argument(
        "--plot-format",
        default="png",
        choices=("png", "svg", "pdf"),
        help="Plot file format (default: png)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=160,
        help="Plot DPI for raster formats (default: 160)",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Generate the workbook only and skip plot generation",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)

    tracing_paths = discover_tracing_workbooks(runs_dir, args.trace_glob)
    all_records = []
    for tracing_path in tracing_paths:
        df = load_tracing_workbook(tracing_path, args.sheet)
        if df.empty:
            continue
        all_records.extend(extract_prompt_run_sequences(df))

    if not all_records:
        raise SystemExit("No tool rows (`run_type == tool`) found in the discovered tracing workbooks.")

    run_level = build_run_level_table(all_records)
    prompt_summary = build_prompt_consistency_summary(run_level)
    tool_presence = build_tool_presence_table(run_level)
    overall_summary = build_overall_summary(prompt_summary, run_level, tool_presence)

    workbook_path = save_outputs(
        out_dir,
        overall_summary,
        prompt_summary,
        run_level,
        tool_presence,
        export_csvs=args.export_csvs,
    )
    print(f"Wrote workbook: {workbook_path}")

    if not args.no_plots:
        generate_plots(
            out_dir,
            prompt_summary,
            run_level,
            tool_presence,
            plot_format=args.plot_format,
            dpi=args.dpi,
        )
        print(f"Wrote plots to: {out_dir}")


if __name__ == "__main__":
    main()
