import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


ARCH_DISPLAY_LABELS = {
    "agentic_architecture": "Agentic",
    "graph_based_architecture": "Graph-based",
    "one_node_architecture": "Monolithic",
}

ARCH_FILL_COLORS = {
    "agentic_architecture": "#4C78A8",
    "graph_based_architecture": "#F58518",
    "one_node_architecture": "#54A24B",
}

PROMPT_BUCKET_LABELS = {
    "basic": "Basic",
    "evil": "Adversarial",
}


def _ordered_arches(df: pd.DataFrame, preferred: Sequence[str] | None) -> list[str]:
    detected = [a for a in sorted(df["arch_id"].dropna().astype(str).unique()) if a]
    if not preferred:
        return detected
    preferred_clean = [a.strip() for a in preferred if a.strip()]
    valid_preferred = [a for a in preferred_clean if a in detected]
    extras = [a for a in detected if a not in valid_preferred]
    return valid_preferred + extras


def _display_arch_labels(architectures: Sequence[str]) -> list[str]:
    return [ARCH_DISPLAY_LABELS.get(arch, arch.replace("_", " ")) for arch in architectures]


def _prompt_id_num(value: object) -> int:
    text = "" if value is None else str(value).strip().lower()
    if "_" in text:
        text = text.split("_", 1)[0]
    if text.startswith("p") and text[1:].isdigit():
        return int(text[1:])
    return 10**9


def _prompt_order(prompt_summary: pd.DataFrame) -> list[str]:
    prompt_ids = [p for p in prompt_summary["prompt_id"].dropna().astype(str).unique() if p]
    return sorted(prompt_ids, key=lambda value: (_prompt_id_num(value), value))


def _display_prompt_label(prompt_id: object) -> str:
    text = "" if prompt_id is None else str(prompt_id).strip()
    if not text:
        return ""
    if "_" not in text:
        return text
    prompt_num, bucket = text.split("_", 1)
    bucket_label = PROMPT_BUCKET_LABELS.get(bucket.lower(), bucket.replace("_", " ").title())
    return f"{prompt_num} ({bucket_label})"


def _heatmap_matrix(
    prompt_summary: pd.DataFrame,
    arch_order: Sequence[str],
    prompt_order: Sequence[str],
    value_col: str,
) -> Any:
    pivot = (
        prompt_summary.pivot(index="arch_id", columns="prompt_id", values=value_col)
        .reindex(index=arch_order, columns=prompt_order)
    )
    return pivot.to_numpy(dtype=float)


def generate_plots(
    out_dir: Path,
    architecture_summary: pd.DataFrame,
    prompt_arch_summary: pd.DataFrame,
    enriched_rows: pd.DataFrame,
    architectures: Sequence[str] | None,
    plot_format: str,
    dpi: int,
) -> None:
    """Generate RQ4 guardrail plots."""
    try:
        mpl_config_dir = Path(tempfile.gettempdir()) / "automated_prompt_interface_mpl"
        mpl_config_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("[WARN] matplotlib is not installed; skipping plot generation.")
        return

    arch_order = _ordered_arches(architecture_summary, architectures)
    if not arch_order:
        print("[WARN] No architectures available for RQ4 plots.")
        return

    obsolete_plot_names = (
        "RQ4_guardrail_summary",
        "RQ4_guardrail_outcome_breakdown",
        "RQ4_guardrail_prompt_correct_rate_heatmap",
        "RQ4_guardrail_prompt_allow_rate_heatmap",
        "RQ4_guardrail_efficiency_mean_std",
        "RQ4_guardrail_decision_distribution",
    )
    for plot_name in obsolete_plot_names:
        old_path = out_dir / f"{plot_name}.{plot_format}"
        if old_path.exists():
            old_path.unlink()

    prompt_order = _prompt_order(prompt_arch_summary)
    prompt_labels = [_display_prompt_label(prompt_id) for prompt_id in prompt_order]
    colors = plt.get_cmap("tab10").colors
    color_map = {
        arch: ARCH_FILL_COLORS.get(arch, colors[i % len(colors)])
        for i, arch in enumerate(arch_order)
    }
    arch_labels = _display_arch_labels(arch_order)

    def _save(fig, filename: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / f"{filename}.{plot_format}", dpi=dpi)
        plt.close(fig)

    # Figure 1: prompt-level block-rate heatmap
    fig, ax = plt.subplots(
        1,
        1,
        figsize=(max(8, len(prompt_order) * 0.9), max(3.5, len(arch_order) * 0.8 + 1.2)),
    )
    block_matrix = _heatmap_matrix(
        prompt_arch_summary,
        arch_order,
        prompt_order,
        "final_block_rate",
    )
    im = ax.imshow(block_matrix, aspect="auto", vmin=0, vmax=1, cmap="Reds")
    ax.set_xticks(range(len(prompt_order)), prompt_labels, rotation=35, ha="right")
    ax.set_yticks(range(len(arch_order)), arch_labels)
    ax.tick_params(axis="both", labelsize=11)
    ax.set_title("RQ4 prompt-level block rate", fontsize=14)
    for i in range(len(arch_order)):
        for j in range(len(prompt_order)):
            value = block_matrix[i][j]
            if pd.notna(value):
                ax.text(
                    j,
                    i,
                    f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="white" if float(value) >= 0.6 else "black",
                )
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Block rate", fontsize=11)
    cbar.ax.tick_params(labelsize=10)
    _save(fig, "RQ4_guardrail_prompt_block_rate_heatmap")

    # Figure 2: total blocked responses per architecture
    fig, ax = plt.subplots(1, 1, figsize=(7.4, 4.8))
    decision_counts = (
        enriched_rows.groupby(["arch_id", "final_decision"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reindex(index=arch_order)
    )
    blocked_counts = decision_counts.get("block", pd.Series(0, index=arch_order))
    ax.bar(
        range(len(arch_order)),
        blocked_counts,
        color=[color_map[a] for a in arch_order],
        edgecolor="black",
        linewidth=1.0,
    )
    for idx, value in enumerate(blocked_counts.tolist()):
        ax.text(idx, value + 3, f"{int(value)}", ha="center", va="bottom", fontsize=11)
    ax.set_xticks(range(len(arch_order)), arch_labels)
    ax.set_title("RQ4 blocked responses by architecture")
    ax.set_ylabel("Blocked responses")
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, max(blocked_counts.max() * 1.12, 1))
    _save(fig, "RQ4_guardrail_blocked_counts")
