from pathlib import Path
from typing import Sequence

import pandas as pd

from app.architecture_styles import ARCH_DISPLAY_LABELS, ARCH_FILL_COLORS

SINGLE_DISTRIBUTION_FIGSIZE = (5.6, 4.9)


def _rate_equals_one(series: pd.Series) -> float:
    """Return the share of observed numeric values that equal 1."""
    numeric = pd.to_numeric(series, errors="coerce")
    observed = numeric.notna().sum()
    if not observed:
        return float("nan")
    return float((numeric == 1).sum() / observed)


def _true_rate(series: pd.Series) -> float:
    """Return the share of observed values that are True."""
    observed = series.notna().sum()
    if not observed:
        return float("nan")
    # `fallback` is normalized upstream to booleans/NA before plotting.
    return float(series.fillna(False).astype(bool).sum() / observed)


def _ordered_arches(df: pd.DataFrame, preferred: Sequence[str] | None) -> list[str]:
    """Return a stable architecture order, honoring an optional preferred list."""
    detected = [a for a in sorted(df["arch_id"].dropna().astype(str).unique()) if a]
    if not preferred:
        return detected
    preferred_clean = [a.strip() for a in preferred if a.strip()]
    valid_preferred = [a for a in preferred_clean if a in detected]
    missing_preferred = sorted({a for a in preferred_clean if a not in detected})
    if missing_preferred:
        print(
            "[WARN] Ignoring architectures not found in plot data: "
            + ", ".join(missing_preferred)
        )
    extras = [a for a in detected if a not in valid_preferred]
    return valid_preferred + extras


def _display_arch_labels(architectures: Sequence[str]) -> list[str]:
    """Return shorter human-readable labels for plots."""
    return [ARCH_DISPLAY_LABELS.get(arch, arch.replace("_", " ")) for arch in architectures]


def _metric_series_by_arch(
    filtered_rows: pd.DataFrame,
    arch_order: Sequence[str],
    metric: str,
) -> list[pd.Series]:
    """Return numeric non-null metric values for each architecture."""
    return [
        pd.to_numeric(
            filtered_rows.loc[filtered_rows["arch_id"] == arch, metric], errors="coerce"
        ).dropna()
        for arch in arch_order
    ]


def _style_boxplot(box, arch_order: Sequence[str], color_map: dict[str, str]) -> None:
    """Apply consistent boxplot colors and borders."""
    for patch, arch in zip(box["boxes"], arch_order):
        patch.set_facecolor(color_map[arch])
        patch.set_alpha(0.65)
        patch.set_edgecolor("black")
        patch.set_linewidth(1.0)


def _style_violin(violin, arch_order: Sequence[str], color_map: dict[str, str]) -> None:
    """Apply consistent violin colors and median styling."""
    for body, arch in zip(violin["bodies"], arch_order):
        body.set_facecolor(color_map[arch])
        body.set_alpha(0.55)
        body.set_edgecolor("black")
        body.set_linewidth(0.8)
    if "cmedians" in violin:
        violin["cmedians"].set_color("#d62728")
        violin["cmedians"].set_linewidth(1.2)


def generate_plots(
    out_dir: Path,
    filtered_rows: pd.DataFrame,
    metrics: dict[str, str],
    architectures: Sequence[str] | None,
    plot_format: str,
    dpi: int,
) -> None:
    """Generate RQ2 comparison plots from filtered per-response rows.

    Creates:
    - mean/std bar charts for the primary RQ2 metrics
    - boxplots for per-response variability
    - quality rate bars (fallback, YAML validity) when those columns exist
    - a dedicated code-lines boxplot when `answer_code_lines` is available
    - an additional code-lines violin plot to better show distribution shape
    """
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
    color_map = {
        arch: ARCH_FILL_COLORS.get(arch, colors[i % len(colors)])
        for i, arch in enumerate(arch_order)
    }
    arch_labels = _display_arch_labels(arch_order)

    def _save(fig, filename: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / f"{filename}.{plot_format}", dpi=dpi)
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
        labels = list(stat.index)
        x_all = list(range(len(labels)))
        valid_mean = stat["mean"].notna()
        x_valid = [x_all[i] for i, ok in enumerate(valid_mean.tolist()) if ok]
        if x_valid:
            ax.bar(
                x_valid,
                stat.loc[valid_mean, "mean"],
                yerr=stat.loc[valid_mean, "std"].fillna(0),
                capsize=5,
                color=[color_map[labels[i]] for i in x_valid],
                edgecolor="black",
                linewidth=1.1,
            )
        ax.set_xticks(x_all, _display_arch_labels(labels))
        ax.set_title(f"Average per response: {label}")
        ax.set_ylabel(label)
        ax.tick_params(axis="x", rotation=15)
        ax.grid(axis="y", alpha=0.3)
    _save(fig, "RQ2_per_response_mean_std")

    # Figure 2: per-response distributions (boxplots)
    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 4.8))
    axes = [axes] if len(metrics) == 1 else axes
    for ax, (metric, label) in zip(axes, metrics.items()):
        data = _metric_series_by_arch(filtered_rows, arch_order, metric)
        box = ax.boxplot(
            data,
            labels=arch_labels,
            patch_artist=True,
            showfliers=True,
            medianprops={"color": "#d62728", "linewidth": 1.1},
        )
        _style_boxplot(box, arch_order, color_map)
        ax.set_title(f"Variability across responses: {label}")
        ax.set_ylabel(label)
        ax.tick_params(axis="x", rotation=12)
        ax.grid(axis="y", alpha=0.3)
    _save(fig, "RQ2_per_response_distributions")

    # Figure 2b: per-metric distribution plots with larger readable panels
    for metric, label in metrics.items():
        data = _metric_series_by_arch(filtered_rows, arch_order, metric)
        if not any(len(series) for series in data):
            continue
        fig, ax = plt.subplots(1, 1, figsize=SINGLE_DISTRIBUTION_FIGSIZE)
        box = ax.boxplot(
            data,
            labels=arch_labels,
            patch_artist=True,
            showfliers=True,
            widths=0.45,
            medianprops={"color": "#d62728", "linewidth": 1.2},
        )
        _style_boxplot(box, arch_order, color_map)
        ax.set_title(label, fontsize=14)
        ax.set_ylabel(label, fontsize=12)
        ax.tick_params(axis="x", rotation=10, labelsize=12)
        ax.tick_params(axis="y", labelsize=11)
        ax.grid(axis="y", alpha=0.3)
        _save(fig, f"RQ2_per_response_distribution_{metric}")

        if metric == "answer_code_lines":
            continue

        try:
            fig, ax = plt.subplots(1, 1, figsize=SINGLE_DISTRIBUTION_FIGSIZE)
            positions = list(range(1, len(arch_order) + 1))
            violin = ax.violinplot(
                data,
                positions=positions,
                showmeans=False,
                showmedians=True,
                showextrema=True,
            )
            _style_violin(violin, arch_order, color_map)
            ax.set_xticks(positions, arch_labels)
            ax.set_title(label, fontsize=14)
            ax.set_ylabel(label, fontsize=12)
            ax.tick_params(axis="x", rotation=10, labelsize=12)
            ax.tick_params(axis="y", labelsize=11)
            ax.grid(axis="y", alpha=0.3)
            _save(fig, f"RQ2_per_response_violin_distribution_{metric}")
        except Exception as exc:  # pragma: no cover - defensive plotting fallback
            print(f"[WARN] Could not generate violin plot for {metric}: {exc}")

    # Figure 3: quality/reliability rates (if available)
    quality_panels: list[tuple[str, pd.Series, str]] = []

    if "fallback" in filtered_rows.columns:
        fallback_rate = (
            filtered_rows.groupby("arch_id")["fallback"]
            .apply(_true_rate)
            .reindex(arch_order)
        )
        quality_panels.append(("Fallback Rate", fallback_rate, "Rate"))

    if "is_yaml_valid" in filtered_rows.columns:
        yaml_valid_rate = (
            filtered_rows.groupby("arch_id")["is_yaml_valid"]
            .apply(_rate_equals_one)
            .reindex(arch_order)
        )
        quality_panels.append(("YAML Valid Rate", yaml_valid_rate, "Rate"))

    if quality_panels:
        fig, axes = plt.subplots(1, len(quality_panels), figsize=(5.5 * len(quality_panels), 4.5))
        axes = [axes] if len(quality_panels) == 1 else axes
        for ax, (title, series, ylabel) in zip(axes, quality_panels):
            ax.bar(
                range(len(series.index)),
                series.fillna(0),
                color=[color_map[a] for a in series.index],
                edgecolor="black",
                linewidth=1.1,
            )
            ax.set_ylim(0, 1)
            ax.set_title(title)
            ax.set_ylabel(ylabel)
            ax.set_xticks(range(len(series.index)), _display_arch_labels(series.index.tolist()))
            ax.tick_params(axis="x", rotation=15)
            ax.grid(axis="y", alpha=0.3)

            for i, value in enumerate(series):
                if pd.notna(value):
                    ax.text(i, min(value + 0.02, 0.98), f"{value:.2%}", ha="center", va="bottom", fontsize=9)
        _save(fig, "RQ2_quality_rates")

    # Figure 4: dedicated code-lines metric plot (requested auxiliary metric)
    if "answer_code_lines" in filtered_rows.columns:
        series_by_arch = _metric_series_by_arch(filtered_rows, arch_order, "answer_code_lines")
        if any(len(s) for s in series_by_arch):
            fig, ax = plt.subplots(1, 1, figsize=SINGLE_DISTRIBUTION_FIGSIZE)
            box = ax.boxplot(
                series_by_arch,
                labels=arch_labels,
                patch_artist=True,
                showfliers=True,
                medianprops={"color": "#d62728", "linewidth": 1.2},
            )
            _style_boxplot(box, arch_order, color_map)
            ax.set_title("Lines of Code per Response")
            ax.set_ylabel("Code lines")
            ax.tick_params(axis="x", rotation=15)
            ax.grid(axis="y", alpha=0.3)
            _save(fig, "RQ2_answer_code_lines_distribution")

            # Figure 5: code-lines distribution as violin plot
            try:
                fig, ax = plt.subplots(1, 1, figsize=SINGLE_DISTRIBUTION_FIGSIZE)
                positions = list(range(1, len(arch_order) + 1))
                violin = ax.violinplot(
                    series_by_arch,
                    positions=positions,
                    showmeans=False,
                    showmedians=True,
                    showextrema=True,
                )
                _style_violin(violin, arch_order, color_map)
                ax.set_xticks(positions, arch_labels)
                ax.set_title("Lines of Code per Response")
                ax.set_ylabel("Code lines")
                ax.tick_params(axis="x", rotation=15)
                ax.grid(axis="y", alpha=0.3)
                _save(fig, "RQ2_answer_code_lines_violin_distribution")
            except Exception as exc:  # pragma: no cover - defensive plotting fallback
                print(f"[WARN] Could not generate LOC violin plot: {exc}")
