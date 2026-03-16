import re
from pathlib import Path

import pandas as pd


def _prompt_sort_key(value: object) -> tuple[int, str]:
    text = "" if value is None else str(value).strip().lower()
    match = re.fullmatch(r"p(\d+)(?:_(.+))?", text)
    if not match:
        return (10**9, text)
    return (int(match.group(1)), text)


def _prompt_difficulty(prompt_id: object) -> str:
    text = "" if prompt_id is None else str(prompt_id).strip().lower()
    match = re.fullmatch(r"p\d+_(basic|intermediate|complex)", text)
    return match.group(1) if match else "unknown"


def _arch_label(arch_id: object) -> str:
    text = "" if arch_id is None else str(arch_id).strip()
    mapping = {
        "agentic_architecture": "Agentic",
        "graph_based_architecture": "Graph-based",
        "one_node_architecture": "One-node",
    }
    return mapping.get(text, text.replace("_", " ").title())


def generate_plots(
    out_dir: Path,
    overall_summary: pd.DataFrame,
    prompt_summary: pd.DataFrame,
    *,
    plot_format: str,
    dpi: int,
) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("[WARN] matplotlib is not installed; skipping reviewed clustering plots.")
        return []

    if overall_summary.empty or prompt_summary.empty:
        print("[WARN] Reviewed clustering summaries are empty; skipping plot generation.")
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []

    def _save(fig, filename: str) -> None:
        fig.tight_layout()
        path = out_dir / f"{filename}.{plot_format}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        written_paths.append(path)

    overall = overall_summary.copy()
    overall["arch_label"] = overall["arch_id"].map(_arch_label)
    overall = overall.sort_values("arch_label", kind="stable").reset_index(drop=True)

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.6))
    x = np.arange(len(overall))
    labels = overall["arch_label"].tolist()

    metrics = [
        ("mean_majority_cluster_share", "Mean Majority Share", (0, 1.05), "#1f77b4"),
        ("perfect_consensus_rate", "Perfect Consensus Rate", (0, 1.05), "#2ca02c"),
        ("mean_cluster_count", "Mean Cluster Count", None, "#ff7f0e"),
    ]
    for ax, (column, title, ylim, color) in zip(axes, metrics):
        values = pd.to_numeric(overall[column], errors="coerce").fillna(0).to_numpy()
        ax.bar(x, values, color=color, alpha=0.9)
        ax.set_xticks(x, labels, rotation=15, ha="right")
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
        if ylim is not None:
            ax.set_ylim(*ylim)
        for idx, value in enumerate(values):
            ax.text(idx, value + 0.02 if ylim else value + 0.03, f"{value:.2f}", ha="center", va="bottom", fontsize=8)
    _save(fig, "RQ3_clustering_reviewed_overall_summary")

    prompt = prompt_summary.copy()
    prompt["arch_label"] = prompt["arch_id"].map(_arch_label)
    prompt["difficulty"] = prompt["prompt_id"].map(_prompt_difficulty)
    prompt["_prompt_order"] = prompt["prompt_id"].map(_prompt_sort_key)
    prompt = prompt.sort_values(["_prompt_order", "arch_label"], kind="stable").reset_index(drop=True)

    prompt_order = (
        prompt[["prompt_id", "_prompt_order"]]
        .drop_duplicates()
        .sort_values("_prompt_order", kind="stable")["prompt_id"]
        .astype(str)
        .tolist()
    )
    arch_order = (
        prompt[["arch_label"]]
        .drop_duplicates()
        .sort_values("arch_label", kind="stable")["arch_label"]
        .astype(str)
        .tolist()
    )

    majority_pivot = (
        prompt.pivot_table(
            index="prompt_id",
            columns="arch_label",
            values="majority_cluster_share",
            aggfunc="mean",
        )
        .reindex(index=prompt_order, columns=arch_order)
        .fillna(0)
    )
    cluster_count_pivot = (
        prompt.pivot_table(
            index="prompt_id",
            columns="arch_label",
            values="cluster_count",
            aggfunc="mean",
        )
        .reindex(index=prompt_order, columns=arch_order)
        .fillna(0)
    )

    x = np.arange(len(prompt_order))
    width = 0.8 / max(len(arch_order), 1)
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b"]

    fig, ax = plt.subplots(figsize=(max(10, len(prompt_order) * 0.75), 4.8))
    for idx, arch_label in enumerate(arch_order):
        values = pd.to_numeric(majority_pivot[arch_label], errors="coerce").fillna(0).to_numpy()
        offset = (idx - (len(arch_order) - 1) / 2) * width
        ax.bar(x + offset, values, width=width, label=arch_label, color=colors[idx % len(colors)], alpha=0.9)
    ax.set_xticks(x, prompt_order)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Majority cluster share")
    ax.set_title("RQ3 Reviewed Consistency by Prompt")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    _save(fig, "RQ3_clustering_reviewed_prompt_majority_share")

    fig, ax = plt.subplots(figsize=(max(10, len(prompt_order) * 0.75), 4.8))
    for idx, arch_label in enumerate(arch_order):
        values = pd.to_numeric(cluster_count_pivot[arch_label], errors="coerce").fillna(0).to_numpy()
        offset = (idx - (len(arch_order) - 1) / 2) * width
        ax.bar(x + offset, values, width=width, label=arch_label, color=colors[idx % len(colors)], alpha=0.9)
    ax.set_xticks(x, prompt_order)
    ax.set_ylabel("Reviewed cluster count")
    ax.set_title("RQ3 Reviewed Cluster Count by Prompt")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    _save(fig, "RQ3_clustering_reviewed_prompt_cluster_count")

    fig, ax = plt.subplots(
        figsize=(max(8, len(prompt_order) * 0.9), max(3.5, len(arch_order) * 0.8 + 1.2))
    )
    heat = majority_pivot.T
    im = ax.imshow(heat.to_numpy(), vmin=0, vmax=1, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(heat.columns)), labels=[str(value) for value in heat.columns], rotation=0)
    ax.set_yticks(range(len(heat.index)), labels=[str(value) for value in heat.index])
    ax.set_title("RQ3 Reviewed Majority Share Heatmap")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Majority share")
    for row_idx in range(heat.shape[0]):
        for col_idx in range(heat.shape[1]):
            value = float(heat.iloc[row_idx, col_idx])
            text_color = "white" if value >= 0.6 else "black"
            ax.text(col_idx, row_idx, f"{value:.2f}", ha="center", va="center", fontsize=8, color=text_color)
    _save(fig, "RQ3_clustering_reviewed_majority_share_heatmap")

    by_difficulty = (
        prompt.groupby(["difficulty", "arch_label"], dropna=False)
        .agg(
            mean_majority_cluster_share=("majority_cluster_share", "mean"),
            mean_cluster_count=("cluster_count", "mean"),
        )
        .reset_index()
    )
    difficulty_order = [diff for diff in ["basic", "intermediate", "complex", "unknown"] if diff in by_difficulty["difficulty"].tolist()]
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.8))
    for ax, value_column, title, ylabel, ylim in [
        (axes[0], "mean_majority_cluster_share", "Mean Majority Share by Difficulty", "Mean majority share", (0, 1.05)),
        (axes[1], "mean_cluster_count", "Mean Cluster Count by Difficulty", "Mean cluster count", None),
    ]:
        x = np.arange(len(difficulty_order))
        width = 0.8 / max(len(arch_order), 1)
        for idx, arch_label in enumerate(arch_order):
            subset = by_difficulty[by_difficulty["arch_label"] == arch_label].set_index("difficulty")
            values = [
                float(pd.to_numeric(subset.loc[diff, value_column], errors="coerce"))
                if diff in subset.index
                else 0.0
                for diff in difficulty_order
            ]
            offset = (idx - (len(arch_order) - 1) / 2) * width
            ax.bar(
                x + offset,
                values,
                width=width,
                label=arch_label,
                color=colors[idx % len(colors)],
                alpha=0.9,
            )
        ax.set_xticks(x, difficulty_order)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
        if ylim is not None:
            ax.set_ylim(*ylim)
    axes[1].legend()
    _save(fig, "RQ3_clustering_reviewed_difficulty_summary")

    return written_paths
