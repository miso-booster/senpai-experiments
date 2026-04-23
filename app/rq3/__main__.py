import argparse
from pathlib import Path

try:
    from .excel import save_outputs
    from .plots import generate_graph_plots, generate_plots
    from .tool_consistency import (
        DEFAULT_GRAPH_ARCHITECTURE,
        build_rq3_results,
        default_rq3_out_dir,
        default_rq3_runs_dir,
    )
except ImportError:  # Supports `python app/rq3/__main__.py`
    from excel import save_outputs
    from plots import generate_graph_plots, generate_plots
    from tool_consistency import (
        DEFAULT_GRAPH_ARCHITECTURE,
        build_rq3_results,
        default_rq3_out_dir,
        default_rq3_runs_dir,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full RQ3 pipeline (generate workbook + tool/graph plots)."
    )
    parser.add_argument(
        "--model-label",
        help=(
            "Optional model label used to resolve model-specific run folders and "
            "default RQ3 output directories."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        help=(
            "Directory containing repeated run folders "
            "(default: out/runs/advanced_prompt_arch_comparison or "
            "out/runs/<model-label>/advanced_prompt_arch_comparison)"
        ),
    )
    parser.add_argument(
        "--trace-glob",
        default="*/tracing_*.xlsx",
        help="Glob relative to runs-dir used to discover tracing workbooks (default: */tracing_*.xlsx)",
    )
    parser.add_argument(
        "--out-dir",
        help=(
            "Output directory for workbook and plots "
            "(default: out/RQ3_tool_consistency_and_node_usage_consistency or "
            "out/RQ3_tool_consistency_and_node_usage_consistency/<model-label>)"
        ),
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
    runs_dir = Path(args.runs_dir) if args.runs_dir else default_rq3_runs_dir(args.model_label)
    out_dir = Path(args.out_dir) if args.out_dir else default_rq3_out_dir(args.model_label)

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
