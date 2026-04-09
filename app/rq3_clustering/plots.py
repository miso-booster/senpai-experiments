import re
from pathlib import Path

import pandas as pd

try:
    from .utils import prompt_sort_key
except ImportError:  # Supports direct execution
    from utils import prompt_sort_key


def _prompt_difficulty(prompt_id: object) -> str:
    text = "" if prompt_id is None else str(prompt_id).strip().lower()
    match = re.fullmatch(r"p\d+_(basic|intermediate|complex)", text)
    return match.group(1) if match else "unknown"


def _arch_label(arch_id: object) -> str:
    text = "" if arch_id is None else str(arch_id).strip()
    mapping = {
        "agentic_architecture": "Agentic",
        "graph_based_architecture": "Graph-based",
        "one_node_architecture": "Monolothic",
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
        matplotlib.rcParams["hatch.linewidth"] = 1.4
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
    arch_hatches = {
        "Agentic": "////",
        "Graph-based": "\\\\\\\\",
        "Monolothic": "----",
    }
    arch_fills = {
        "Agentic": "#4C78A8",
        "Graph-based": "#F58518",
        "Monolothic": "#54A24B",
    }

    def _save(fig, filename: str) -> None:
        fig.tight_layout()
        path = out_dir / f"{filename}.{plot_format}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)
        written_paths.append(path)

    legend_kwargs = {
        "handlelength": 2.6,
        "handleheight": 1.4,
        "borderpad": 0.8,
        "labelspacing": 0.6,
    }

    overall = overall_summary.copy()
    overall["arch_label"] = overall["arch_id"].map(_arch_label)
    overall = overall.sort_values("arch_label", kind="stable").reset_index(drop=True)

    x = np.arange(len(overall))
    labels = overall["arch_label"].tolist()

    metrics = [
        (
            "mean_majority_cluster_share",
            "Mean Majority Share",
            "Mean majority share",
            (0, 1.05),
            "RQ3_clustering_reviewed_overall_mean_majority_share",
        ),
        (
            "perfect_consensus_rate",
            "Perfect Consensus Rate",
            "Perfect consensus rate",
            (0, 1.05),
            "RQ3_clustering_reviewed_overall_perfect_consensus_rate",
        ),
        (
            "mean_cluster_count",
            "Mean Cluster Count",
            "Mean cluster count",
            None,
            "RQ3_clustering_reviewed_overall_mean_cluster_count",
        ),
        (
            "fallback_rate",
            "Fallback Rate",
            "Fallback rate",
            (0, 1.05),
            "RQ3_clustering_reviewed_overall_fallback_rate",
        ),
    ]
    for column, title, ylabel, ylim, filename in metrics:
        fig, ax = plt.subplots(figsize=(5.2, 4.6))
        values = pd.to_numeric(overall[column], errors="coerce").fillna(0).to_numpy()
        ax.bar(
            x,
            values,
            color=[arch_fills.get(label, "#bdbdbd") for label in labels],
            edgecolor="black",
            linewidth=1.2,
        )
        ax.set_xticks(x, labels, rotation=15, ha="right")
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=0.3)
        if ylim is not None:
            ax.set_ylim(*ylim)
        for idx, value in enumerate(values):
            ax.text(idx, value + 0.02 if ylim else value + 0.03, f"{value:.2f}", ha="center", va="bottom", fontsize=8)
        _save(fig, filename)

    prompt = prompt_summary.copy()
    prompt["arch_label"] = prompt["arch_id"].map(_arch_label)
    prompt["difficulty"] = prompt["prompt_id"].map(_prompt_difficulty)
    for column in ["majority_cluster_share", "cluster_count", "fallback_rate"]:
        prompt[column] = pd.to_numeric(prompt[column], errors="coerce")
    prompt["_prompt_order"] = prompt["prompt_id"].map(prompt_sort_key)
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
    fig, ax = plt.subplots(figsize=(max(10, len(prompt_order) * 0.75), 4.8))
    for idx, arch_label in enumerate(arch_order):
        values = pd.to_numeric(majority_pivot[arch_label], errors="coerce").fillna(0).to_numpy()
        offset = (idx - (len(arch_order) - 1) / 2) * width
        bars = ax.bar(
            x + offset,
            values,
            width=width,
            label=arch_label,
            color=arch_fills.get(arch_label, "#bdbdbd"),
            edgecolor="black",
            linewidth=1.1,
        )
        for bar in bars:
            bar.set_hatch(arch_hatches.get(arch_label, "///"))
    ax.set_xticks(x, prompt_order)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Majority cluster share")
    ax.set_title("RQ3 Reviewed Consistency by Prompt")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(**legend_kwargs)
    _save(fig, "RQ3_clustering_reviewed_prompt_majority_share")

    fig, ax = plt.subplots(figsize=(max(10, len(prompt_order) * 0.75), 4.8))
    for idx, arch_label in enumerate(arch_order):
        values = pd.to_numeric(cluster_count_pivot[arch_label], errors="coerce").fillna(0).to_numpy()
        offset = (idx - (len(arch_order) - 1) / 2) * width
        bars = ax.bar(
            x + offset,
            values,
            width=width,
            label=arch_label,
            color=arch_fills.get(arch_label, "#bdbdbd"),
            edgecolor="black",
            linewidth=1.1,
        )
        for bar in bars:
            bar.set_hatch(arch_hatches.get(arch_label, "///"))
    ax.set_xticks(x, prompt_order)
    ax.set_ylabel("Reviewed cluster count")
    ax.set_title("RQ3 Reviewed Cluster Count by Prompt")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(**legend_kwargs)
    _save(fig, "RQ3_clustering_reviewed_prompt_cluster_count")

    fallback_pivot = (
        prompt.pivot_table(
            index="prompt_id",
            columns="arch_label",
            values="fallback_rate",
            aggfunc="mean",
        )
        .reindex(index=prompt_order, columns=arch_order)
        .fillna(0)
    )

    fig, ax = plt.subplots(figsize=(max(10, len(prompt_order) * 0.75), 4.8))
    for idx, arch_label in enumerate(arch_order):
        values = pd.to_numeric(fallback_pivot[arch_label], errors="coerce").fillna(0).to_numpy()
        offset = (idx - (len(arch_order) - 1) / 2) * width
        bars = ax.bar(
            x + offset,
            values,
            width=width,
            label=arch_label,
            color=arch_fills.get(arch_label, "#bdbdbd"),
            edgecolor="black",
            linewidth=1.1,
        )
        for bar in bars:
            bar.set_hatch(arch_hatches.get(arch_label, "///"))
    ax.set_xticks(x, prompt_order)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Fallback rate")
    ax.set_title("RQ3 Reviewed Fallback Rate by Prompt")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(**legend_kwargs)
    _save(fig, "RQ3_clustering_reviewed_prompt_fallback_rate")

    fig, ax = plt.subplots(
        figsize=(max(8, len(prompt_order) * 0.9), max(3.5, len(arch_order) * 0.8 + 1.2))
    )
    heat = majority_pivot.T.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    im = ax.imshow(heat.to_numpy(dtype=float), vmin=0, vmax=1, cmap="Reds", aspect="auto")
    ax.set_xticks(range(len(heat.columns)), labels=[str(value) for value in heat.columns], rotation=0)
    ax.set_yticks(range(len(heat.index)), labels=[str(value) for value in heat.index])
    ax.tick_params(axis="both", labelsize=11)
    ax.set_title("RQ3 Reviewed Majority Share Heatmap", fontsize=14)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Majority share", fontsize=11)
    cbar.ax.tick_params(labelsize=10)
    for row_idx in range(heat.shape[0]):
        for col_idx in range(heat.shape[1]):
            value = float(heat.iloc[row_idx, col_idx])
            text_color = "white" if value >= 0.55 else "black"
            ax.text(col_idx, row_idx, f"{value:.2f}", ha="center", va="center", fontsize=14, color=text_color)
    _save(fig, "RQ3_clustering_reviewed_majority_share_heatmap")

    by_difficulty = (
        prompt.groupby(["difficulty", "arch_label"], dropna=False)
        .agg(
            mean_majority_cluster_share=("majority_cluster_share", "mean"),
            mean_cluster_count=("cluster_count", "mean"),
            fallback_rate=("fallback_rate", "mean"),
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
            bars = ax.bar(
                x + offset,
                values,
                width=width,
                label=arch_label,
                color=arch_fills.get(arch_label, "#bdbdbd"),
                edgecolor="black",
                linewidth=1.1,
            )
            for bar in bars:
                bar.set_hatch(arch_hatches.get(arch_label, "///"))
        ax.set_xticks(x, difficulty_order)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
        if ylim is not None:
            ax.set_ylim(*ylim)
    axes[1].legend(**legend_kwargs)
    _save(fig, "RQ3_clustering_reviewed_difficulty_summary")

    fig, ax = plt.subplots(figsize=(7.0, 4.8))
    x = np.arange(len(difficulty_order))
    width = 0.8 / max(len(arch_order), 1)
    for idx, arch_label in enumerate(arch_order):
        subset = by_difficulty[by_difficulty["arch_label"] == arch_label].set_index("difficulty")
        values = [
            float(pd.to_numeric(subset.loc[diff, "fallback_rate"], errors="coerce"))
            if diff in subset.index
            else 0.0
            for diff in difficulty_order
        ]
        offset = (idx - (len(arch_order) - 1) / 2) * width
        bars = ax.bar(
            x + offset,
            values,
            width=width,
            label=arch_label,
            color=arch_fills.get(arch_label, "#bdbdbd"),
            edgecolor="black",
            linewidth=1.1,
        )
        for bar in bars:
            bar.set_hatch(arch_hatches.get(arch_label, "///"))
    ax.set_xticks(x, difficulty_order)
    ax.set_ylabel("Fallback rate")
    ax.set_title("Fallback Rate by Difficulty")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(**legend_kwargs)
    _save(fig, "RQ3_clustering_reviewed_difficulty_fallback_rate")

    return written_paths
