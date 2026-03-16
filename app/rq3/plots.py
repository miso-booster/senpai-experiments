import argparse
from pathlib import Path
import re

import pandas as pd


METRIC_FILL_COLORS = {
    "Exact seq": "#1f77b4",
    "Exact sequence": "#1f77b4",
    "Exact set": "#ff7f0e",
    "Exact multiset": "#2ca02c",
    "Set Jaccard": "#9467bd",
    "Multiset Jaccard": "#8c564b",
    "Count": "#17becf",
}

METRIC_HATCHES = {
    "Exact seq": "////",
    "Exact sequence": "////",
    "Exact set": "\\\\\\\\",
    "Exact multiset": "----",
    "Set Jaccard": "xxxx",
    "Multiset Jaccard": "....",
    "Count": "//////",
}

DIFFICULTY_FILL_COLORS = {
    "basic": "#1f77b4",
    "intermediate": "#ff7f0e",
    "complex": "#2ca02c",
}

DIFFICULTY_HATCHES = {
    "basic": "////",
    "intermediate": "\\\\\\\\",
    "complex": "----",
}


def _prompt_id_num(value: object) -> int:
    text = "" if value is None else str(value).strip().lower()
    m = re.fullmatch(r"p(\d+)", text)
    return int(m.group(1)) if m else 10**9


def _generate_sequence_plots(
    out_dir: Path,
    prompt_summary: pd.DataFrame,
    presence: pd.DataFrame,
    *,
    plot_format: str,
    dpi: int,
    item_name_column: str,
    count_mean_col: str,
    count_std_col: str,
    count_axis_label: str,
    title_prefix: str,
    prompt_title: str,
    similarity_title: str,
    count_title: str,
    presence_title: str,
    prompt_filename: str,
    similarity_filename: str,
    presence_filename: str,
    variability_summary_filename: str,
    variability_mean_std_filename: str,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        matplotlib.rcParams["hatch.linewidth"] = 1.4
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.patches import Patch
    except ImportError:
        print("[WARN] matplotlib is not installed; skipping plot generation.")
        return

    if prompt_summary.empty:
        print(f"[WARN] No prompt summary rows available; skipping plot generation for {prompt_filename}.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    def _save(fig, filename: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / f"{filename}.{plot_format}", dpi=dpi, bbox_inches="tight")
        plt.close(fig)

    legend_kwargs = {
        "handlelength": 2.6,
        "handleheight": 1.4,
        "borderpad": 0.8,
        "labelspacing": 0.6,
    }

    ps = (
        prompt_summary.assign(_prompt_id_num=prompt_summary["prompt_id"].map(_prompt_id_num))
        .sort_values(["_prompt_id_num", "prompt_id", "prompt_key"], kind="stable")
        .drop(columns=["_prompt_id_num"], errors="ignore")
        .reset_index(drop=True)
    )
    prompt_order = ps["prompt_id"].astype(str).tolist()
    x = np.arange(len(prompt_order))

    fig, ax = plt.subplots(figsize=(max(9, len(ps) * 0.9), 4.8))
    width = 0.25
    bars = [
        ("Exact sequence", "exact_sequence_consistency", -width),
        ("Exact set", "exact_set_consistency", 0.0),
        ("Exact multiset", "exact_multiset_consistency", width),
    ]
    for label, col, offset in bars:
        vals = pd.to_numeric(ps[col], errors="coerce").fillna(0).to_numpy()
        series_bars = ax.bar(
            x + offset,
            vals,
            width=width,
            label=label,
            color=METRIC_FILL_COLORS[label],
            edgecolor="black",
            linewidth=1.1,
        )
        for bar in series_bars:
            bar.set_hatch(METRIC_HATCHES[label])
    ax.set_xticks(x, prompt_order)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Consistency")
    ax.set_title(prompt_title)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(**legend_kwargs)
    _save(fig, prompt_filename)

    fig, axes = plt.subplots(1, 2, figsize=(max(12, len(ps) * 1.2), 4.8))
    ax1, ax2 = axes

    set_j = pd.to_numeric(ps["pairwise_set_jaccard_mean"], errors="coerce").fillna(0).to_numpy()
    bag_j = pd.to_numeric(ps["pairwise_multiset_jaccard_mean"], errors="coerce").fillna(0).to_numpy()
    set_bars = ax1.bar(
        x - width / 2,
        set_j,
        width=width,
        label="Set Jaccard",
        color=METRIC_FILL_COLORS["Set Jaccard"],
        edgecolor="black",
        linewidth=1.1,
    )
    bag_bars = ax1.bar(
        x + width / 2,
        bag_j,
        width=width,
        label="Multiset Jaccard",
        color=METRIC_FILL_COLORS["Multiset Jaccard"],
        edgecolor="black",
        linewidth=1.1,
    )
    for bar in set_bars:
        bar.set_hatch(METRIC_HATCHES["Set Jaccard"])
    for bar in bag_bars:
        bar.set_hatch(METRIC_HATCHES["Multiset Jaccard"])
    ax1.set_xticks(x, prompt_order)
    ax1.set_ylim(0, 1.05)
    ax1.set_ylabel("Mean pairwise similarity")
    ax1.set_title(similarity_title)
    ax1.grid(axis="y", alpha=0.3)
    ax1.legend(**legend_kwargs)

    means = pd.to_numeric(ps[count_mean_col], errors="coerce").to_numpy()
    stds = pd.to_numeric(ps[count_std_col], errors="coerce").fillna(0).to_numpy()
    count_bars = ax2.bar(
        x,
        means,
        yerr=stds,
        capsize=4,
        color=METRIC_FILL_COLORS["Count"],
        edgecolor="black",
        linewidth=1.1,
    )
    for bar in count_bars:
        bar.set_hatch(METRIC_HATCHES["Count"])
    ax2.set_xticks(x, prompt_order)
    ax2.set_ylabel(count_axis_label)
    ax2.set_title(count_title)
    ax2.grid(axis="y", alpha=0.3)
    _save(fig, similarity_filename)

    if not presence.empty:
        presence_df = presence.copy()
        presence_df["presence_rate_across_runs"] = pd.to_numeric(
            presence_df["presence_rate_across_runs"], errors="coerce"
        )
        heat = presence_df.pivot_table(
            index=item_name_column,
            columns="prompt_id",
            values="presence_rate_across_runs",
            aggfunc="mean",
        )
        heat = heat.reindex(columns=[pid for pid in prompt_order if pid in heat.columns])
        if not heat.empty:
            fig, ax = plt.subplots(figsize=(max(8, heat.shape[1] * 1.1), max(4, heat.shape[0] * 0.6 + 1.5)))
            im = ax.imshow(heat.fillna(0).to_numpy(), vmin=0, vmax=1, cmap="Reds", aspect="auto")
            ax.set_xticks(range(len(heat.columns)), labels=[str(c) for c in heat.columns], rotation=0)
            ax.set_yticks(range(len(heat.index)), labels=[str(i) for i in heat.index])
            ax.tick_params(axis="both", labelsize=11)
            ax.set_title(presence_title, fontsize=14)
            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label("Presence rate", fontsize=11)
            cbar.ax.tick_params(labelsize=10)
            for i in range(heat.shape[0]):
                for j in range(heat.shape[1]):
                    val = heat.iloc[i, j]
                    if pd.notna(val):
                        text_color = "white" if float(val) >= 0.6 else "black"
                        ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=14, color=text_color)
            _save(fig, presence_filename)

    variability_metrics = [
        ("exact_sequence_consistency", "Exact seq"),
        ("exact_set_consistency", "Exact set"),
        ("exact_multiset_consistency", "Exact multiset"),
        ("pairwise_set_jaccard_mean", "Set Jaccard"),
        ("pairwise_multiset_jaccard_mean", "Multiset Jaccard"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))

    ax = axes[0]
    metric_labels = [label for _, label in variability_metrics]
    overall_data = [
        pd.to_numeric(ps[col], errors="coerce").dropna().tolist()
        for col, _ in variability_metrics
    ]
    box = ax.boxplot(
        overall_data,
        tick_labels=metric_labels,
        patch_artist=True,
        showfliers=True,
        medianprops={"color": "#d62728", "linewidth": 1.1},
    )
    for patch, label in zip(box["boxes"], metric_labels):
        patch.set_facecolor(METRIC_FILL_COLORS[label])
        patch.set_alpha(0.65)
        patch.set_edgecolor("black")
        patch.set_linewidth(1.0)
        patch.set_hatch(METRIC_HATCHES[label])
    ax.set_xticks(np.arange(1, len(metric_labels) + 1), metric_labels, rotation=20, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title(f"{title_prefix} Metric Distributions Across Prompts")
    ax.grid(axis="y", alpha=0.3)

    ax = axes[1]
    difficulty_order = ["basic", "intermediate", "complex"]
    group_centers = np.arange(len(variability_metrics), dtype=float)
    width = 0.22
    diff_offsets = {"basic": -width, "intermediate": 0.0, "complex": width}

    legend_handles = []
    for diff in difficulty_order:
        datasets = []
        positions = []
        for i, (metric, _) in enumerate(variability_metrics):
            vals = pd.to_numeric(ps.loc[ps["difficulty"] == diff, metric], errors="coerce").dropna().tolist()
            datasets.append(vals)
            positions.append(group_centers[i] + diff_offsets[diff])
        b = ax.boxplot(
            datasets,
            positions=positions,
            widths=width * 0.9,
            patch_artist=True,
            showfliers=True,
            medianprops={"color": "#d62728", "linewidth": 1.0},
            manage_ticks=False,
        )
        for patch in b["boxes"]:
            patch.set_facecolor(DIFFICULTY_FILL_COLORS[diff])
            patch.set_alpha(0.55)
            patch.set_edgecolor("black")
            patch.set_linewidth(1.0)
            patch.set_hatch(DIFFICULTY_HATCHES[diff])
        legend_handles.append(
            Patch(
                facecolor=DIFFICULTY_FILL_COLORS[diff],
                edgecolor="black",
                hatch=DIFFICULTY_HATCHES[diff],
                alpha=0.55,
                label=diff,
            )
        )

    ax.set_xticks(group_centers, metric_labels, rotation=20, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title(f"{title_prefix} Metric Distributions by Difficulty")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(handles=legend_handles, fontsize=8, **legend_kwargs)
    _save(fig, variability_summary_filename)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))

    ax = axes[0]
    overall_stats = (
        ps[[m for m, _ in variability_metrics]]
        .apply(pd.to_numeric, errors="coerce")
        .agg(["mean", "std"])
        .T
        .reset_index()
        .rename(columns={"index": "metric"})
    )
    label_map = {m: label for m, label in variability_metrics}
    overall_stats["label"] = overall_stats["metric"].map(label_map)
    x_all = np.arange(len(overall_stats))
    means = pd.to_numeric(overall_stats["mean"], errors="coerce").fillna(0).to_numpy()
    stds = pd.to_numeric(overall_stats["std"], errors="coerce").fillna(0).to_numpy()
    lower = np.minimum(stds, means)
    upper = np.minimum(stds, 1 - means)
    summary_bars = ax.bar(
        x_all,
        means,
        yerr=np.vstack([lower, upper]),
        capsize=5,
        color=[METRIC_FILL_COLORS[label] for label in overall_stats["label"]],
        edgecolor="black",
        linewidth=1.1,
    )
    for bar, label in zip(summary_bars, overall_stats["label"]):
        bar.set_hatch(METRIC_HATCHES[label])
    ax.set_xticks(x_all, overall_stats["label"].tolist(), rotation=20, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Mean score across prompts")
    ax.set_title(f"{title_prefix} Average and Variability (All Prompts)")
    ax.grid(axis="y", alpha=0.3)

    ax = axes[1]
    by_diff_stats = (
        ps.groupby("difficulty", dropna=False)[[m for m, _ in variability_metrics]]
        .agg(["mean", "std"])
        .reindex(difficulty_order)
    )
    x_diff = np.arange(len(difficulty_order))
    width = 0.15
    for i, (metric, label) in enumerate(variability_metrics):
        mean_vals = pd.to_numeric(by_diff_stats[(metric, "mean")], errors="coerce").fillna(0).to_numpy()
        std_vals = pd.to_numeric(by_diff_stats[(metric, "std")], errors="coerce").fillna(0).to_numpy()
        lower = np.minimum(std_vals, mean_vals)
        upper = np.minimum(std_vals, 1 - mean_vals)
        bars = ax.bar(
            x_diff + (i - 2.0) * width,
            mean_vals,
            width=width,
            yerr=np.vstack([lower, upper]),
            capsize=3,
            label=label,
            color=METRIC_FILL_COLORS[label],
            edgecolor="black",
            linewidth=1.0,
        )
        for bar in bars:
            bar.set_hatch(METRIC_HATCHES[label])
    ax.set_xticks(x_diff, difficulty_order)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Mean score")
    ax.set_title(f"{title_prefix} Average and Variability by Difficulty")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8, **legend_kwargs)
    _save(fig, variability_mean_std_filename)


def generate_plots(
    out_dir: Path,
    prompt_summary: pd.DataFrame,
    run_level: pd.DataFrame,
    tool_presence: pd.DataFrame,
    *,
    plot_format: str,
    dpi: int,
) -> None:
    _ = run_level  # kept for backwards-compatible signature
    _generate_sequence_plots(
        out_dir,
        prompt_summary,
        tool_presence,
        plot_format=plot_format,
        dpi=dpi,
        item_name_column="tool_name",
        count_mean_col="tool_calls_mean",
        count_std_col="tool_calls_std",
        count_axis_label="Tool calls per run",
        title_prefix="Tool Consistency",
        prompt_title="RQ3 Tool Selection Consistency by Prompt",
        similarity_title="Pairwise Similarity Across Runs",
        count_title="Tool Call Count Variability by Prompt",
        presence_title="Tool Presence Rate Across Runs (Prompt x Tool)",
        prompt_filename="RQ3_tool_consistency",
        similarity_filename="RQ3_tool_consistency_similarity_and_toolcount",
        presence_filename="RQ3_tool_consistency_presence_heatmap",
        variability_summary_filename="RQ3_tool_consistency_variability_summary",
        variability_mean_std_filename="RQ3_tool_consistency_variability_mean_std",
    )


def generate_graph_plots(
    out_dir: Path,
    prompt_summary: pd.DataFrame,
    run_level: pd.DataFrame,
    graph_presence: pd.DataFrame,
    *,
    plot_format: str,
    dpi: int,
) -> None:
    _ = run_level
    _generate_sequence_plots(
        out_dir,
        prompt_summary,
        graph_presence,
        plot_format=plot_format,
        dpi=dpi,
        item_name_column="graph_node_name",
        count_mean_col="graph_nodes_mean",
        count_std_col="graph_nodes_std",
        count_axis_label="Graph nodes per run",
        title_prefix="Node Usage Consistency",
        prompt_title="RQ3 Node Usage Consistency by Prompt",
        similarity_title="Pairwise Node Usage Similarity Across Runs",
        count_title="Node Usage Count Variability by Prompt",
        presence_title="Node Usage Presence Rate Across Runs (Prompt x Node)",
        prompt_filename="RQ3_node_usage_consistency",
        similarity_filename="RQ3_node_usage_consistency_similarity_and_nodecount",
        presence_filename="RQ3_node_usage_consistency_presence_heatmap",
        variability_summary_filename="RQ3_node_usage_consistency_variability_summary",
        variability_mean_std_filename="RQ3_node_usage_consistency_variability_mean_std",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate RQ3 plots from an RQ3 Excel workbook.")
    parser.add_argument(
        "--workbook",
        default="out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_and_node_usage_consistency.xlsx",
        help=(
            "Path to the RQ3 workbook "
            "(default: out/RQ3_tool_consistency_and_node_usage_consistency/RQ3_tool_consistency_and_node_usage_consistency.xlsx)"
        ),
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory for plots (default: workbook parent)",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workbook = Path(args.workbook)
    if not workbook.exists():
        raise SystemExit(f"Workbook not found: {workbook}")

    out_dir = Path(args.out_dir) if args.out_dir else workbook.parent

    prompt_summary = pd.read_excel(workbook, sheet_name="prompt_consistency")
    run_level = pd.read_excel(workbook, sheet_name="tool_sequences_per_run")
    tool_presence = pd.read_excel(workbook, sheet_name="tool_presence")

    generate_plots(
        out_dir,
        prompt_summary,
        run_level,
        tool_presence,
        plot_format=args.plot_format,
        dpi=args.dpi,
    )

    xl = pd.ExcelFile(workbook)
    graph_sheets = {"node_usage_prompt_consistency", "node_usage_sequences_per_run", "node_usage_presence"}
    if graph_sheets.issubset(set(xl.sheet_names)):
        graph_prompt_summary = pd.read_excel(workbook, sheet_name="node_usage_prompt_consistency")
        graph_run_level = pd.read_excel(workbook, sheet_name="node_usage_sequences_per_run")
        graph_presence = pd.read_excel(workbook, sheet_name="node_usage_presence")
        generate_graph_plots(
            out_dir,
            graph_prompt_summary,
            graph_run_level,
            graph_presence,
            plot_format=args.plot_format,
            dpi=args.dpi,
        )

    print(f"Wrote plots to: {out_dir}")


if __name__ == "__main__":
    main()
