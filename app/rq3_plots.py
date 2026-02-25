import argparse
from pathlib import Path
import re

import pandas as pd


def _prompt_id_num(value: object) -> int:
    text = "" if value is None else str(value).strip().lower()
    m = re.fullmatch(r"p(\d+)", text)
    return int(m.group(1)) if m else 10**9


def generate_plots(
    out_dir: Path,
    prompt_summary: pd.DataFrame,
    run_level: pd.DataFrame,
    tool_presence: pd.DataFrame,
    *,
    plot_format: str,
    dpi: int,
) -> None:
    """Generate RQ3 plots (safe no-op if matplotlib is unavailable)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.patches import Patch
    except ImportError:
        print("[WARN] matplotlib is not installed; skipping plot generation.")
        return

    if prompt_summary.empty:
        print("[WARN] No prompt summary rows available; skipping RQ3 plots.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    def _save(fig, filename: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / f"{filename}.{plot_format}", dpi=dpi, bbox_inches="tight")
        plt.close(fig)

    ps = (
        prompt_summary.assign(_prompt_id_num=prompt_summary["prompt_id"].map(_prompt_id_num))
        .sort_values(["_prompt_id_num", "prompt_id", "prompt_key"], kind="stable")
        .drop(columns=["_prompt_id_num"], errors="ignore")
        .reset_index(drop=True)
    )
    prompt_order = ps["prompt_id"].astype(str).tolist()
    x = np.arange(len(prompt_order))

    # Plot 1: per-prompt consistency (exact match metrics)
    fig, ax = plt.subplots(figsize=(max(9, len(ps) * 0.9), 4.8))
    width = 0.25
    bars = [
        ("Exact sequence", "exact_sequence_consistency", -width, "#1f77b4"),
        ("Exact set", "exact_set_consistency", 0.0, "#ff7f0e"),
        ("Exact multiset", "exact_multiset_consistency", width, "#2ca02c"),
    ]
    for label, col, offset, color in bars:
        vals = pd.to_numeric(ps[col], errors="coerce").fillna(0).to_numpy()
        ax.bar(x + offset, vals, width=width, label=label, color=color, alpha=0.9)
    ax.set_xticks(x, prompt_order)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Consistency")
    ax.set_title("RQ3 Tool Selection Consistency by Prompt")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    _save(fig, "RQ3_prompt_consistency")

    # Plot 2: per-prompt pairwise similarity + tool-call variability
    fig, axes = plt.subplots(1, 2, figsize=(max(12, len(ps) * 1.2), 4.8))
    ax1, ax2 = axes

    set_j = pd.to_numeric(ps["pairwise_set_jaccard_mean"], errors="coerce").fillna(0).to_numpy()
    bag_j = pd.to_numeric(ps["pairwise_multiset_jaccard_mean"], errors="coerce").fillna(0).to_numpy()
    ax1.bar(x - width / 2, set_j, width=width, label="Set Jaccard", color="#9467bd")
    ax1.bar(x + width / 2, bag_j, width=width, label="Multiset Jaccard", color="#8c564b")
    ax1.set_xticks(x, prompt_order)
    ax1.set_ylim(0, 1.05)
    ax1.set_ylabel("Mean pairwise similarity")
    ax1.set_title("Pairwise Similarity Across Runs")
    ax1.grid(axis="y", alpha=0.3)
    ax1.legend()

    means = pd.to_numeric(ps["tool_calls_mean"], errors="coerce").to_numpy()
    stds = pd.to_numeric(ps["tool_calls_std"], errors="coerce").fillna(0).to_numpy()
    ax2.bar(x, means, yerr=stds, capsize=4, color="#17becf", alpha=0.85)
    ax2.set_xticks(x, prompt_order)
    ax2.set_ylabel("Tool calls per run")
    ax2.set_title("Tool Call Count Variability by Prompt")
    ax2.grid(axis="y", alpha=0.3)
    _save(fig, "RQ3_similarity_and_toolcount")

    # Plot 3: tool presence heatmap (prompt x tool)
    if not tool_presence.empty:
        tp = tool_presence.copy()
        tp["presence_rate_across_runs"] = pd.to_numeric(tp["presence_rate_across_runs"], errors="coerce")
        heat = tp.pivot_table(
            index="prompt_id",
            columns="tool_name",
            values="presence_rate_across_runs",
            aggfunc="mean",
        )
        heat = heat.reindex(index=[pid for pid in prompt_order if pid in heat.index])
        if not heat.empty:
            fig, ax = plt.subplots(figsize=(max(8, heat.shape[1] * 1.1), max(4, heat.shape[0] * 0.6 + 1.5)))
            im = ax.imshow(heat.fillna(0).to_numpy(), vmin=0, vmax=1, cmap="YlGnBu", aspect="auto")
            ax.set_xticks(range(len(heat.columns)), labels=[str(c) for c in heat.columns], rotation=30, ha="right")
            ax.set_yticks(range(len(heat.index)), labels=[str(i) for i in heat.index])
            ax.set_title("Tool Presence Rate Across Runs (per Prompt)")
            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label("Presence rate")
            for i in range(heat.shape[0]):
                for j in range(heat.shape[1]):
                    val = heat.iloc[i, j]
                    if pd.notna(val):
                        ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8, color="black")
            _save(fig, "RQ3_tool_presence_heatmap")

    # Plot 4: variability across prompts using boxplots (overall and by difficulty)
    variability_metrics = [
        ("exact_sequence_consistency", "Exact seq"),
        ("exact_set_consistency", "Exact set"),
        ("exact_multiset_consistency", "Exact multiset"),
        ("pairwise_set_jaccard_mean", "Set Jaccard"),
        ("pairwise_multiset_jaccard_mean", "Multiset Jaccard"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))

    # Left panel: overall distributions across prompts (one box per metric)
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
    palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b"]
    for patch, color in zip(box["boxes"], palette):
        patch.set_facecolor(color)
        patch.set_alpha(0.65)
    ax.set_xticks(np.arange(1, len(metric_labels) + 1), metric_labels, rotation=20, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("Metric Distributions Across Prompts")
    ax.grid(axis="y", alpha=0.3)

    # Right panel: grouped boxplots by difficulty for all metrics
    ax = axes[1]
    difficulty_order = ["basic", "intermediate", "complex"]
    group_centers = np.arange(len(variability_metrics), dtype=float)
    width = 0.22
    diff_colors = {"basic": "#1f77b4", "intermediate": "#ff7f0e", "complex": "#2ca02c"}
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
            patch.set_facecolor(diff_colors[diff])
            patch.set_alpha(0.55)
        legend_handles.append(Patch(facecolor=diff_colors[diff], edgecolor="black", alpha=0.55, label=diff))

    ax.set_xticks(group_centers, metric_labels, rotation=20, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("Metric Distributions by Difficulty")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(handles=legend_handles, fontsize=8)

    _save(fig, "RQ3_consistency_variability_summary")

    # Plot 5: mean +/- std version (kept as an alternative to boxplots)
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.8))

    # Left panel: overall mean +/- std across prompts
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
    ax.bar(
        x_all,
        means,
        yerr=np.vstack([lower, upper]),
        capsize=5,
        color=palette[: len(overall_stats)],
        alpha=0.9,
    )
    ax.set_xticks(x_all, overall_stats["label"].tolist(), rotation=20, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Mean score across prompts")
    ax.set_title("Average and Variability (All Prompts)")
    ax.grid(axis="y", alpha=0.3)

    # Right panel: by difficulty mean +/- std for all metrics
    ax = axes[1]
    difficulty_order = ["basic", "intermediate", "complex"]
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
        ax.bar(
            x_diff + (i - 2.0) * width,
            mean_vals,
            width=width,
            yerr=np.vstack([lower, upper]),
            capsize=3,
            label=label,
            color=palette[i],
            alpha=0.9,
        )
    ax.set_xticks(x_diff, difficulty_order)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Mean score")
    ax.set_title("Average and Variability by Difficulty")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8)

    _save(fig, "RQ3_consistency_variability_mean_std")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate RQ3 plots from an RQ3 Excel workbook.")
    parser.add_argument(
        "--workbook",
        default="out/RQ3_tool_consistency/RQ3_tool_consistency.xlsx",
        help="Path to RQ3 workbook (default: out/RQ3_tool_consistency/RQ3_tool_consistency.xlsx)",
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
    print(f"Wrote plots to: {out_dir}")


if __name__ == "__main__":
    main()
