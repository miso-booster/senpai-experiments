from pathlib import Path
from typing import Sequence

import pandas as pd


def _ordered_arches(df: pd.DataFrame, preferred: Sequence[str] | None) -> list[str]:
    detected = [a for a in sorted(df["arch_id"].dropna().astype(str).unique()) if a]
    if not preferred:
        return detected
    preferred_clean = [a.strip() for a in preferred if a.strip()]
    extras = [a for a in detected if a not in preferred_clean]
    return preferred_clean + extras


def generate_plots(
    out_dir: Path,
    filtered_rows: pd.DataFrame,
    metrics: dict[str, str],
    architectures: Sequence[str] | None,
    plot_format: str,
    dpi: int,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib is not installed; skipping plot generation.")
        return

    arch_order = _ordered_arches(filtered_rows, architectures)
    if not arch_order:
        print("[WARN] No architectures available for plots.")
        return

    colors = plt.get_cmap("tab10").colors
    color_map = {arch: colors[i % len(colors)] for i, arch in enumerate(arch_order)}

    def _save(fig, filename: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / f"{filename}.{plot_format}", dpi=dpi, bbox_inches="tight")
        plt.close(fig)

    # Figure 1: per-response means with std bars
    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4.5))
    axes = [axes] if len(metrics) == 1 else axes
    for ax, (metric, label) in zip(axes, metrics.items()):
        stat = (
            filtered_rows.groupby("arch_id")[metric]
            .agg(mean="mean", std="std")
            .reindex(arch_order)
        )
        ax.bar(
            stat.index,
            stat["mean"].fillna(0),
            yerr=stat["std"].fillna(0),
            capsize=5,
            color=[color_map[a] for a in stat.index],
            alpha=0.9,
        )
        ax.set_title(f"Average per response: {label}")
        ax.set_ylabel(label)
        ax.tick_params(axis="x", rotation=20)
        ax.grid(axis="y", alpha=0.3)
    _save(fig, "RQ2_per_response_mean_std")

    # Figure 2: per-response distributions (boxplots)
    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4.8))
    axes = [axes] if len(metrics) == 1 else axes
    for ax, (metric, label) in zip(axes, metrics.items()):
        data = [
            pd.to_numeric(
                filtered_rows.loc[filtered_rows["arch_id"] == arch, metric], errors="coerce"
            ).dropna()
            for arch in arch_order
        ]
        box = ax.boxplot(
            data,
            labels=arch_order,
            patch_artist=True,
            showfliers=True,
            medianprops={"color": "#d62728", "linewidth": 1.1},
        )
        for patch, arch in zip(box["boxes"], arch_order):
            patch.set_facecolor(color_map[arch])
            patch.set_alpha(0.65)
        ax.set_title(f"Variability across responses: {label}")
        ax.set_ylabel(label)
        ax.tick_params(axis="x", rotation=20)
        ax.grid(axis="y", alpha=0.3)
    _save(fig, "RQ2_per_response_distributions")

    # Figure 3: quality/reliability rates (if available)
    quality_panels: list[tuple[str, pd.Series, str]] = []

    if "fallback" in filtered_rows.columns:
        fallback_rate = (
            filtered_rows.groupby("arch_id")["fallback"]
            .apply(lambda s: (s == True).sum() / s.notna().sum() if s.notna().sum() else float("nan"))  # noqa: E712
            .reindex(arch_order)
        )
        quality_panels.append(("Fallback Rate", fallback_rate, "Rate"))

    if "is_yaml_valid" in filtered_rows.columns:
        yaml_valid_rate = (
            filtered_rows.groupby("arch_id")["is_yaml_valid"]
            .apply(
                lambda s: (
                    (pd.to_numeric(s, errors="coerce") == 1).sum()
                    / pd.to_numeric(s, errors="coerce").notna().sum()
                    if pd.to_numeric(s, errors="coerce").notna().sum()
                    else float("nan")
                )
            )
            .reindex(arch_order)
        )
        quality_panels.append(("YAML Valid Rate", yaml_valid_rate, "Rate"))

    if quality_panels:
        fig, axes = plt.subplots(1, len(quality_panels), figsize=(5.5 * len(quality_panels), 4.5))
        axes = [axes] if len(quality_panels) == 1 else axes
        for ax, (title, series, ylabel) in zip(axes, quality_panels):
            ax.bar(
                series.index,
                series.fillna(0),
                color=[color_map[a] for a in series.index],
                alpha=0.9,
            )
            ax.set_ylim(0, 1)
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            ax.tick_params(axis="x", rotation=20)
            ax.grid(axis="y", alpha=0.3)

            for i, value in enumerate(series):
                if pd.notna(value):
                    ax.text(i, min(value + 0.02, 0.98), f"{value:.2%}", ha="center", va="bottom", fontsize=9)
        _save(fig, "RQ2_quality_rates")
