from pathlib import Path
from typing import Sequence

import pandas as pd

from app.architecture_styles import ARCH_DISPLAY_LABELS, ARCH_FILL_COLORS

SINGLE_DISTRIBUTION_FIGSIZE = (5.6, 4.9)

MODEL_DISPLAY_LABELS = {
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4-1-mini": "gpt-4.1-mini",
    "gpt-5-codex": "gpt-5-codex",
    "gemini-3-1-pro-preview": "gemini-3.1-pro-preview",
}

MODEL_ORDER = (
    "gpt-4o-mini",
    "gpt-4-1-mini",
    "gpt-5-codex",
    "gemini-3-1-pro-preview",
)


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


def _ordered_models(df: pd.DataFrame) -> list[str]:
    if "model_label" not in df.columns:
        return []
    detected = [m for m in df["model_label"].dropna().astype(str).unique() if m]
    ordered = [model for model in MODEL_ORDER if model in detected]
    extras = sorted(model for model in detected if model not in ordered)
    return ordered + extras


def _display_model_label(model: str) -> str:
    return MODEL_DISPLAY_LABELS.get(model, model)


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


def generate_model_comparison_plots(
    out_dir: Path,
    filtered_rows: pd.DataFrame,
    metrics: dict[str, str],
    architectures: Sequence[str] | None,
    plot_format: str,
    dpi: int,
) -> None:
    """Generate RQ2 plots that compare all models in a single figure per metric family."""
    if "model_label" not in filtered_rows.columns:
        print("[WARN] model_label column not found; skipping RQ2 model comparison plots.")
        return

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("[WARN] matplotlib is not installed; skipping model comparison plot generation.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    model_order = _ordered_models(filtered_rows)
    arch_order = _ordered_arches(filtered_rows, architectures)
    if not model_order or not arch_order:
        print("[WARN] No models or architectures available for RQ2 model comparison plots.")
        return

    colors = plt.get_cmap("tab10").colors
    color_map = {
        arch: ARCH_FILL_COLORS.get(arch, colors[i % len(colors)])
        for i, arch in enumerate(arch_order)
    }
    arch_labels = _display_arch_labels(arch_order)
    model_labels = [_display_model_label(model) for model in model_order]

    def _save(fig, filename: str) -> None:
        fig.tight_layout(rect=(0, 0.08, 1, 1))
        fig.savefig(out_dir / f"{filename}.{plot_format}", dpi=dpi, bbox_inches="tight")
        plt.close(fig)

    def _place_legend(ax, *, ncols: int | None = None) -> None:
        ax.legend(
            frameon=False,
            fontsize=9,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.22),
            ncols=ncols or min(len(arch_order), 3),
        )

    def _grouped_metric_stat(metric: str) -> pd.DataFrame:
        return (
            filtered_rows.groupby(["model_label", "arch_id"])[metric]
            .agg(mean="mean", std="std")
            .reindex(pd.MultiIndex.from_product([model_order, arch_order], names=["model_label", "arch_id"]))
        )

    def _draw_grouped_bars(ax, values_by_arch: dict[str, list[float]], errors_by_arch: dict[str, list[float]], title: str, ylabel: str, *, ylim: tuple[float, float] | None = None) -> None:
        group_x = np.arange(len(model_order), dtype=float)
        bar_width = min(0.22, 0.78 / max(len(arch_order), 1))
        offsets = (np.arange(len(arch_order)) - (len(arch_order) - 1) / 2) * bar_width
        all_values = [
            float(value)
            for values in values_by_arch.values()
            for value in values
            if pd.notna(value)
        ]
        max_value = max(all_values) if all_values else 0.0
        for arch_idx, arch in enumerate(arch_order):
            values = values_by_arch[arch]
            errors = errors_by_arch.get(arch, [0] * len(values))
            bars = ax.bar(
                group_x + offsets[arch_idx],
                values,
                yerr=errors,
                width=bar_width,
                capsize=4 if any(pd.notna(errors)) else 0,
                color=color_map[arch],
                edgecolor="black",
                linewidth=0.8,
                label=ARCH_DISPLAY_LABELS.get(arch, arch.replace("_", " ")),
            )
            for bar, value in zip(bars, values):
                if pd.isna(value):
                    continue
                label = f"{value:.2f}" if not ylim else f"{value:.0%}"
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(max_value * 0.015, 0.01),
                    label,
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xticks(group_x, model_labels, rotation=15, ha="right")
        if ylim:
            lower, upper = ylim
            ax.set_ylim(lower, upper + max((upper - lower) * 0.12, 0.08))
        ax.grid(axis="y", alpha=0.3)

    # Figure 1: per-response means with std bars, grouped by model.
    fig, axes = plt.subplots(1, len(metrics), figsize=(5.2 * len(metrics), 4.8))
    axes = [axes] if len(metrics) == 1 else axes
    for ax, (metric, label) in zip(axes, metrics.items()):
        stat = _grouped_metric_stat(metric)
        values_by_arch: dict[str, list[float]] = {}
        errors_by_arch: dict[str, list[float]] = {}
        for arch in arch_order:
            arch_stat = stat.xs(arch, level="arch_id")
            values_by_arch[arch] = pd.to_numeric(arch_stat["mean"], errors="coerce").fillna(0).tolist()
            errors_by_arch[arch] = pd.to_numeric(arch_stat["std"], errors="coerce").fillna(0).tolist()
        _draw_grouped_bars(ax, values_by_arch, errors_by_arch, f"Average per response: {label}", label)
    _place_legend(axes[-1])
    _save(fig, "RQ2_per_response_mean_std")

    # Figure 2: per-response distributions as grouped boxplots.
    fig, axes = plt.subplots(1, len(metrics), figsize=(5.2 * len(metrics), 4.9))
    axes = [axes] if len(metrics) == 1 else axes
    for ax, (metric, label) in zip(axes, metrics.items()):
        _draw_grouped_boxplot(ax, filtered_rows, model_order, arch_order, color_map, metric, label)
    axes[-1].legend(
        _legend_handles(plt, arch_order, color_map),
        arch_labels,
        frameon=False,
        fontsize=9,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        ncols=min(len(arch_order), 3),
    )
    _save(fig, "RQ2_per_response_distributions")

    # Figure 2b: larger per-metric distribution panels.
    for metric, label in metrics.items():
        fig, ax = plt.subplots(1, 1, figsize=(max(6.8, len(model_order) * 1.6), 4.9))
        _draw_grouped_boxplot(ax, filtered_rows, model_order, arch_order, color_map, metric, label)
        ax.legend(
            _legend_handles(plt, arch_order, color_map),
            arch_labels,
            frameon=False,
            fontsize=9,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.22),
            ncols=min(len(arch_order), 3),
        )
        _save(fig, f"RQ2_per_response_distribution_{metric}")

    # Figure 3: quality/reliability rates, grouped by model.
    quality_panels: list[tuple[str, pd.Series, str]] = []
    if "fallback" in filtered_rows.columns:
        fallback_rate = filtered_rows.groupby(["model_label", "arch_id"])["fallback"].apply(_true_rate)
        quality_panels.append(("Fallback Rate", fallback_rate, "Rate"))
    if "is_yaml_valid" in filtered_rows.columns:
        yaml_valid_rate = filtered_rows.groupby(["model_label", "arch_id"])["is_yaml_valid"].apply(_rate_equals_one)
        quality_panels.append(("YAML Valid Rate", yaml_valid_rate, "Rate"))

    if quality_panels:
        fig, axes = plt.subplots(1, len(quality_panels), figsize=(5.4 * len(quality_panels), 4.8))
        axes = [axes] if len(quality_panels) == 1 else axes
        full_index = pd.MultiIndex.from_product([model_order, arch_order], names=["model_label", "arch_id"])
        for ax, (title, series, ylabel) in zip(axes, quality_panels):
            reindexed = series.reindex(full_index)
            values_by_arch = {}
            errors_by_arch = {}
            for arch in arch_order:
                arch_values = reindexed.xs(arch, level="arch_id")
                values_by_arch[arch] = pd.to_numeric(arch_values, errors="coerce").fillna(0).tolist()
                errors_by_arch[arch] = [0] * len(model_order)
            _draw_grouped_bars(ax, values_by_arch, errors_by_arch, title, ylabel, ylim=(0, 1))
        _place_legend(axes[-1])
        _save(fig, "RQ2_quality_rates")

        for title, series, ylabel in quality_panels:
            fig, ax = plt.subplots(1, 1, figsize=(max(6.8, len(model_order) * 1.6), 4.8))
            reindexed = series.reindex(full_index)
            values_by_arch = {}
            errors_by_arch = {}
            for arch in arch_order:
                arch_values = reindexed.xs(arch, level="arch_id")
                values_by_arch[arch] = pd.to_numeric(arch_values, errors="coerce").fillna(0).tolist()
                errors_by_arch[arch] = [0] * len(model_order)
            _draw_grouped_bars(ax, values_by_arch, errors_by_arch, title, ylabel, ylim=(0, 1))
            _place_legend(ax)
            filename = (
                "RQ2_quality_fallback_rate"
                if title == "Fallback Rate"
                else "RQ2_quality_yaml_valid_rate"
            )
            _save(fig, filename)

    # Figure 4/5 aliases for code lines, matching the individual output set.
    if "answer_code_lines" in filtered_rows.columns:
        fig, ax = plt.subplots(1, 1, figsize=(max(6.8, len(model_order) * 1.6), 4.9))
        _draw_grouped_boxplot(
            ax,
            filtered_rows,
            model_order,
            arch_order,
            color_map,
            "answer_code_lines",
            "Code lines",
            title="Lines of Code per Response",
        )
        ax.legend(
            _legend_handles(plt, arch_order, color_map),
            arch_labels,
            frameon=False,
            fontsize=9,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.22),
            ncols=min(len(arch_order), 3),
        )
        _save(fig, "RQ2_answer_code_lines_distribution")


def _draw_grouped_boxplot(
    ax,
    filtered_rows: pd.DataFrame,
    model_order: Sequence[str],
    arch_order: Sequence[str],
    color_map: dict[str, str],
    metric: str,
    label: str,
    title: str | None = None,
) -> None:
    import numpy as np

    group_x = np.arange(len(model_order), dtype=float)
    box_width = min(0.18, 0.68 / max(len(arch_order), 1))
    offsets = (np.arange(len(arch_order)) - (len(arch_order) - 1) / 2) * box_width
    data: list[pd.Series] = []
    positions: list[float] = []
    box_arches: list[str] = []
    for model_idx, model in enumerate(model_order):
        for arch_idx, arch in enumerate(arch_order):
            values = pd.to_numeric(
                filtered_rows.loc[
                    (filtered_rows["model_label"].astype(str) == model)
                    & (filtered_rows["arch_id"].astype(str) == arch),
                    metric,
                ],
                errors="coerce",
            ).dropna()
            if values.empty:
                values = pd.Series([float("nan")])
            data.append(values)
            positions.append(float(group_x[model_idx] + offsets[arch_idx]))
            box_arches.append(arch)
    box = ax.boxplot(
        data,
        positions=positions,
        widths=box_width * 0.82,
        patch_artist=True,
        showfliers=True,
        medianprops={"color": "#d62728", "linewidth": 1.0},
    )
    for patch, arch in zip(box["boxes"], box_arches):
        patch.set_facecolor(color_map[arch])
        patch.set_alpha(0.65)
        patch.set_edgecolor("black")
        patch.set_linewidth(0.8)
    ax.set_xticks(group_x, [_display_model_label(model) for model in model_order], rotation=15, ha="right")
    ax.set_title(title or f"Variability across responses: {label}")
    ax.set_ylabel(label)
    ax.grid(axis="y", alpha=0.3)


def _legend_handles(plt, arch_order: Sequence[str], color_map: dict[str, str]):
    return [
        plt.Line2D(
            [0],
            [0],
            marker="s",
            linestyle="",
            markersize=9,
            markerfacecolor=color_map[arch],
            markeredgecolor="black",
        )
        for arch in arch_order
    ]
