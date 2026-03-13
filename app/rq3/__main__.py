import argparse
from pathlib import Path

try:
    from .excel import save_outputs
    from .plots import generate_graph_plots, generate_plots
    from .tool_consistency import (
        DEFAULT_GRAPH_ARCHITECTURE,
        DEFAULT_OUT_DIR,
        DEFAULT_RUNS_DIR,
        build_rq3_results,
    )
except ImportError:  # Supports `python app/rq3/__main__.py`
    from excel import save_outputs
    from plots import generate_graph_plots, generate_plots
    from tool_consistency import (
        DEFAULT_GRAPH_ARCHITECTURE,
        DEFAULT_OUT_DIR,
        DEFAULT_RUNS_DIR,
        build_rq3_results,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full RQ3 pipeline (generate workbook + tool/graph plots)."
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
        "--graph-architecture-prefix",
        default=DEFAULT_GRAPH_ARCHITECTURE,
        help=(
            "Conversation ID prefix used to identify the graph architecture "
            f"(default: {DEFAULT_GRAPH_ARCHITECTURE})"
        ),
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

    results = build_rq3_results(
        runs_dir,
        args.trace_glob,
        args.sheet,
        graph_architecture_prefix=args.graph_architecture_prefix,
    )

    workbook_path = save_outputs(
        out_dir,
        results.tool.overall_summary,
        results.tool.prompt_summary,
        results.tool.run_level,
        results.tool.presence,
        graph_overall_summary=results.graph.overall_summary,
        graph_prompt_summary=results.graph.prompt_summary,
        graph_run_level=results.graph.run_level,
        graph_presence=results.graph.presence,
        export_csvs=args.export_csvs,
    )
    print(f"Wrote workbook: {workbook_path}")

    if not args.no_plots:
        generate_plots(
            out_dir,
            results.tool.prompt_summary,
            results.tool.run_level,
            results.tool.presence,
            plot_format=args.plot_format,
            dpi=args.dpi,
        )
        generate_graph_plots(
            out_dir,
            results.graph.prompt_summary,
            results.graph.run_level,
            results.graph.presence,
            plot_format=args.plot_format,
            dpi=args.dpi,
        )
        print(f"Wrote plots to: {out_dir}")


if __name__ == "__main__":
    main()
