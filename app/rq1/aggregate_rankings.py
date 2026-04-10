import argparse
import csv
import math
import os
import pathlib
import random
import tempfile
from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from app.setup_configuration import OUT_DIR, RUNS_DIR
from app.rq1.utils import sanitize_run_dir

DEFAULT_RQ1_RUNS_DIR = RUNS_DIR / "architecture_comparison"
DEFAULT_RQ1_OUT_ROOT = OUT_DIR / "RQ1"
DEFAULT_BOOTSTRAP_ITERATIONS = 10_000
DEFAULT_BOOTSTRAP_SEED = 20260409

CONFIDENCE_WEIGHTS = {
    "H": 1.0,
    "M": 2.0 / 3.0,
    "L": 1.0 / 3.0,
}

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


@dataclass(frozen=True)
class PromptRating:
    subject_id: str
    confidence: str
    confidence_weight: float
    ranks_by_arch: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ranks_by_arch",
            MappingProxyType(dict(self.ranks_by_arch)),
        )


def _load_key(path: pathlib.Path) -> Dict[Tuple[str, str], Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        key_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for row in reader:
            pid = (row.get("prompt_id") or "").strip()
            label = (row.get("label") or "").strip().upper()
            if not pid or not label:
                continue
            key_map[(pid, label)] = row
    return key_map


def _build_prompt_label_map(
    key_map: Dict[Tuple[str, str], Dict[str, str]],
) -> Dict[str, Dict[str, Dict[str, str]]]:
    prompt_label_map: Dict[str, Dict[str, Dict[str, str]]] = {}
    for (prompt_id, label), row in key_map.items():
        prompt_label_map.setdefault(prompt_id, {})[label] = row
    return prompt_label_map


def _rank_columns(fieldnames: Sequence[str]) -> List[str]:
    cols = [name for name in fieldnames if name.lower().startswith("rank")]

    def _rank_key(name: str) -> int:
        suffix = "".join(ch for ch in name if ch.isdigit())
        return int(suffix) if suffix else 0

    return sorted(cols, key=_rank_key)


def _resolve_run_dir(runs_dir: pathlib.Path, run_id: str | None) -> pathlib.Path:
    if not runs_dir.exists():
        raise SystemExit(f"runs-dir not found: {runs_dir}")
    if not runs_dir.is_dir():
        raise SystemExit(f"runs-dir is not a directory: {runs_dir}")

    if run_id:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise SystemExit(f"run_id not found in {runs_dir}: {run_id}")
        if not run_dir.is_dir():
            raise SystemExit(f"run_id path is not a directory: {run_dir}")
        return run_dir

    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    if not run_dirs:
        raise SystemExit(f"No run directories found in: {runs_dir}")
    selected = run_dirs[0]
    print(f"Using first run in {runs_dir}: {selected.name}")
    return selected


def _resolve_answers_dir(args: argparse.Namespace) -> pathlib.Path:
    if args.answers_dir:
        return pathlib.Path(args.answers_dir)
    run_dir = _resolve_run_dir(pathlib.Path(args.runs_dir), args.run_id)
    return DEFAULT_RQ1_OUT_ROOT / run_dir.name


def _confidence_to_weight(
    confidence: str,
    *,
    answers_path: pathlib.Path,
    prompt_id: str,
) -> float:
    normalized = (confidence or "").strip().upper()
    if normalized not in CONFIDENCE_WEIGHTS:
        valid = ", ".join(sorted(CONFIDENCE_WEIGHTS))
        raise SystemExit(
            f"Unexpected confidence '{confidence}' for prompt '{prompt_id}' in "
            f"{answers_path.name}. Expected one of: {valid}"
        )
    return CONFIDENCE_WEIGHTS[normalized]


def _extract_ranked_labels(
    row: Dict[str, str],
    rank_cols: Sequence[str],
    *,
    answers_path: pathlib.Path,
    prompt_id: str,
    prompt_key_rows: Dict[str, Dict[str, str]],
) -> List[str]:
    ordered_labels: List[str] = []
    for col in rank_cols:
        label = (row.get(col) or "").strip().upper()
        if label:
            ordered_labels.append(label)

    expected_labels = sorted(prompt_key_rows)
    if len(ordered_labels) != len(expected_labels):
        raise SystemExit(
            f"Prompt '{prompt_id}' in {answers_path.name} has {len(ordered_labels)} ranked "
            f"labels, expected {len(expected_labels)}."
        )
    if len(set(ordered_labels)) != len(ordered_labels):
        raise SystemExit(
            f"Prompt '{prompt_id}' in {answers_path.name} repeats one or more labels."
        )
    unknown = sorted(set(ordered_labels) - set(expected_labels))
    if unknown:
        raise SystemExit(
            f"Prompt '{prompt_id}' in {answers_path.name} contains unknown labels: "
            f"{', '.join(unknown)}"
        )
    missing = sorted(set(expected_labels) - set(ordered_labels))
    if missing:
        raise SystemExit(
            f"Prompt '{prompt_id}' in {answers_path.name} is missing labels: "
            f"{', '.join(missing)}"
        )
    return ordered_labels


def _weighted_prompt_rank(prompt_ratings: Sequence[PromptRating]) -> Dict[str, float]:
    weighted_sum_by_arch: Dict[str, float] = {}
    weight_total_by_arch: Dict[str, float] = {}

    for rating in prompt_ratings:
        weight = rating.confidence_weight
        for arch_id, rank_value in rating.ranks_by_arch.items():
            weighted_sum_by_arch[arch_id] = weighted_sum_by_arch.get(arch_id, 0.0) + (
                weight * rank_value
            )
            weight_total_by_arch[arch_id] = weight_total_by_arch.get(arch_id, 0.0) + weight

    weighted_ranks: Dict[str, float] = {}
    for arch_id, weighted_sum in weighted_sum_by_arch.items():
        total_weight = weight_total_by_arch.get(arch_id, 0.0)
        if total_weight <= 0:
            raise SystemExit(
                f"Prompt-level weighted rank for architecture '{arch_id}' has zero total weight."
            )
        weighted_ranks[arch_id] = weighted_sum / total_weight
    return weighted_ranks


def _weighted_pairwise_prompt_winner(
    prompt_ratings: Sequence[PromptRating],
    arch_a: str,
    arch_b: str,
) -> int | None:
    weight_a = 0.0
    weight_b = 0.0
    observed = False

    for rating in prompt_ratings:
        rank_a = rating.ranks_by_arch.get(arch_a)
        rank_b = rating.ranks_by_arch.get(arch_b)
        if rank_a is None or rank_b is None:
            continue
        observed = True
        if rank_a < rank_b:
            weight_a += rating.confidence_weight
        elif rank_b < rank_a:
            weight_b += rating.confidence_weight

    if not observed:
        return None
    if weight_a > weight_b:
        return 1
    if weight_b > weight_a:
        return -1
    return 0


def _mean(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    return sum(values) / len(values)


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]

    lower_value = ordered[lower]
    upper_value = ordered[upper]
    fraction = index - lower
    return lower_value + (upper_value - lower_value) * fraction


def _bootstrap_ci(values: Sequence[float]) -> Tuple[float, float]:
    filtered = [value for value in values if not math.isnan(value)]
    if not filtered:
        return float("nan"), float("nan")
    return _percentile(filtered, 0.025), _percentile(filtered, 0.975)


def _format_float(value: float) -> str:
    if math.isnan(value):
        return ""
    return f"{value:.6f}"


def _ordered_arches(arch_ids: Iterable[str]) -> List[str]:
    return sorted({arch_id for arch_id in arch_ids if arch_id})


def _display_arch_labels(architectures: Sequence[str]) -> List[str]:
    return [ARCH_DISPLAY_LABELS.get(arch, arch.replace("_", " ")) for arch in architectures]


def _write_combined_rankings(
    out_path: pathlib.Path,
    all_rows: Sequence[Dict[str, str]],
) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "subject_id",
                "prompt_id",
                "rank_position",
                "label",
                "arch_id",
                "confidence",
                "confidence_weight",
                "run_id",
                "run_group_id",
                "run_dir",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(all_rows)


def _write_avg_prompt_rank_metrics(
    out_path: pathlib.Path,
    arch_list: Sequence[str],
    prompt_weighted_ranks: Dict[str, Dict[str, float]],
    bootstrap_arch_metrics: Dict[str, List[float]],
) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "arch_id",
                "avg_prompt_rank",
                "ci_lower_95",
                "ci_upper_95",
            ],
            delimiter=";",
        )
        writer.writeheader()
        for arch_id in arch_list:
            values = [
                prompt_weighted_ranks[prompt_id][arch_id]
                for prompt_id in sorted(prompt_weighted_ranks)
                if arch_id in prompt_weighted_ranks[prompt_id]
            ]
            ci_lower, ci_upper = _bootstrap_ci(bootstrap_arch_metrics.get(arch_id, []))
            writer.writerow(
                {
                    "arch_id": arch_id,
                    "avg_prompt_rank": _format_float(_mean(values)),
                    "ci_lower_95": _format_float(ci_lower),
                    "ci_upper_95": _format_float(ci_upper),
                }
            )


def _write_pairwise_metrics(
    out_path: pathlib.Path,
    arch_list: Sequence[str],
    prompt_pairwise_winners: Dict[Tuple[str, str], Dict[str, int]],
    bootstrap_pair_metrics: Dict[Tuple[str, str], List[float]],
) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "arch_a",
                "arch_b",
                "wins_a_over_b",
                "wins_b_over_a",
                "ties",
                "non_tied_total",
                "win_rate_a_over_b",
                "ci_lower_95",
                "ci_upper_95",
            ],
            delimiter=";",
        )
        writer.writeheader()
        for arch_a, arch_b in combinations(arch_list, 2):
            outcomes = prompt_pairwise_winners.get((arch_a, arch_b), {})
            wins_a = sum(1 for result in outcomes.values() if result == 1)
            wins_b = sum(1 for result in outcomes.values() if result == -1)
            ties = sum(1 for result in outcomes.values() if result == 0)
            non_tied_total = wins_a + wins_b
            win_rate = (wins_a / non_tied_total) if non_tied_total else float("nan")
            ci_lower, ci_upper = _bootstrap_ci(
                bootstrap_pair_metrics.get((arch_a, arch_b), [])
            )
            writer.writerow(
                {
                    "arch_a": arch_a,
                    "arch_b": arch_b,
                    "wins_a_over_b": wins_a,
                    "wins_b_over_a": wins_b,
                    "ties": ties,
                    "non_tied_total": non_tied_total,
                    "win_rate_a_over_b": _format_float(win_rate),
                    "ci_lower_95": _format_float(ci_lower),
                    "ci_upper_95": _format_float(ci_upper),
                }
            )


def _generate_plots(
    answers_dir: pathlib.Path,
    arch_list: Sequence[str],
    avg_prompt_rank_metrics_path: pathlib.Path,
    pairwise_metrics_path: pathlib.Path,
    *,
    plot_format: str,
    dpi: int,
) -> None:
    try:
        mpl_config_dir = pathlib.Path(tempfile.gettempdir()) / "automated-prompt-interface-matplotlib"
        mpl_config_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib is not installed; skipping plot generation.")
        return

    colors = plt.get_cmap("tab10").colors
    color_map = {
        arch: ARCH_FILL_COLORS.get(arch, colors[i % len(colors)])
        for i, arch in enumerate(arch_list)
    }

    def _save(fig, stem: str) -> None:
        fig.tight_layout()
        fig.savefig(answers_dir / f"{stem}.{plot_format}", dpi=dpi)
        plt.close(fig)

    avg_rows: List[Dict[str, str]] = []
    with avg_prompt_rank_metrics_path.open("r", encoding="utf-8", newline="") as f:
        avg_rows = list(csv.DictReader(f, delimiter=";"))

    avg_rows_by_arch = {row["arch_id"]: row for row in avg_rows}
    avg_values = [
        float(avg_rows_by_arch[arch]["avg_prompt_rank"])
        for arch in arch_list
        if avg_rows_by_arch.get(arch, {}).get("avg_prompt_rank")
    ]
    if avg_values:
        ordered_rows = sorted(
            (
                {
                    "arch_id": arch,
                    "avg_prompt_rank": float(avg_rows_by_arch[arch]["avg_prompt_rank"]),
                    "ci_lower_95": float(avg_rows_by_arch[arch]["ci_lower_95"]),
                    "ci_upper_95": float(avg_rows_by_arch[arch]["ci_upper_95"]),
                }
                for arch in arch_list
            ),
            key=lambda row: row["avg_prompt_rank"],
        )
        fig, ax = plt.subplots(figsize=(7.8, 4.8))
        positions = list(range(len(ordered_rows)))
        labels = _display_arch_labels([row["arch_id"] for row in ordered_rows])
        heights = []
        lower_errors = []
        upper_errors = []
        bar_colors = []
        for row in ordered_rows:
            arch = row["arch_id"]
            mean_value = row["avg_prompt_rank"]
            ci_lower = row["ci_lower_95"]
            ci_upper = row["ci_upper_95"]
            heights.append(mean_value)
            lower_errors.append(max(mean_value - ci_lower, 0.0))
            upper_errors.append(max(ci_upper - mean_value, 0.0))
            bar_colors.append(color_map[arch])
        ax.bar(
            positions,
            heights,
            yerr=[lower_errors, upper_errors],
            capsize=5,
            color=bar_colors,
            edgecolor="black",
            linewidth=1.0,
        )
        y_min = min(row["ci_lower_95"] for row in ordered_rows)
        y_max = max(row["ci_upper_95"] for row in ordered_rows)
        ax.set_ylim(y_min - 0.05, y_max + 0.10)
        label_y = y_min - 0.015
        for position, mean_value in zip(positions, heights):
            ax.text(position, label_y, f"{mean_value:.2f}", va="top", ha="center", fontsize=10)
        ax.set_xticks(positions, labels)
        ax.set_ylabel("Confidence-weighted average prompt rank")
        ax.set_title("RQ1: Weighted Average Prompt Rank (lower is better)")
        ax.grid(axis="y", alpha=0.3)
        _save(fig, "RQ1_weighted_avg_prompt_rank")
    pair_rows: List[Dict[str, str]] = []
    with pairwise_metrics_path.open("r", encoding="utf-8", newline="") as f:
        pair_rows = list(csv.DictReader(f, delimiter=";"))

    pairwise_plot_rows: List[Dict[str, object]] = []
    for row in pair_rows:
        win_rate_text = row.get("win_rate_a_over_b", "")
        ci_lower_text = row.get("ci_lower_95", "")
        ci_upper_text = row.get("ci_upper_95", "")
        if not win_rate_text or not ci_lower_text or not ci_upper_text:
            continue
        arch_a = row["arch_a"]
        arch_b = row["arch_b"]
        win_rate = float(win_rate_text)
        ci_lower = float(ci_lower_text)
        ci_upper = float(ci_upper_text)
        pairwise_plot_rows.append(
            {
                "label": (
                    f"{ARCH_DISPLAY_LABELS.get(arch_a, arch_a)} vs "
                    f"{ARCH_DISPLAY_LABELS.get(arch_b, arch_b)}"
                ),
                "win_rate": win_rate,
                "lower_error": max(win_rate - ci_lower, 0.0),
                "upper_error": max(ci_upper - win_rate, 0.0),
            }
        )

    if pairwise_plot_rows:
        fig, ax = plt.subplots(figsize=(max(8.2, len(pairwise_plot_rows) * 2.2), 4.8))
        positions = list(range(len(pairwise_plot_rows)))
        values = [row["win_rate"] for row in pairwise_plot_rows]
        lower_errors = [row["lower_error"] for row in pairwise_plot_rows]
        upper_errors = [row["upper_error"] for row in pairwise_plot_rows]
        labels = [str(row["label"]) for row in pairwise_plot_rows]
        ax.bar(
            positions,
            values,
            yerr=[lower_errors, upper_errors],
            capsize=5,
            color="#7A7A7A",
            edgecolor="black",
            linewidth=1.0,
            alpha=0.75,
        )
        ax.axhline(0.5, color="#444444", linestyle="--", linewidth=1.1)
        for position, value, upper_error in zip(positions, values, upper_errors):
            ax.text(
                position,
                min(value + upper_error + 0.03, 0.98),
                f"{value:.2f}",
                va="bottom",
                ha="center",
                fontsize=10,
            )
        ax.set_xticks(positions, labels)
        ax.tick_params(axis="x", rotation=15)
        ax.set_ylim(0.0, 1.0)
        ax.set_ylabel("Confidence-weighted win rate of first architecture in pair")
        ax.set_title("RQ1: Pairwise Win Rates with 95% CI")
        ax.grid(axis="y", alpha=0.3)
        _save(fig, "RQ1_pairwise_summary")


def _bootstrap_metrics(
    prompt_ids: Sequence[str],
    arch_list: Sequence[str],
    prompt_weighted_ranks: Dict[str, Dict[str, float]],
    prompt_pairwise_winners: Dict[Tuple[str, str], Dict[str, int]],
    *,
    iterations: int,
    seed: int,
) -> Tuple[Dict[str, List[float]], Dict[Tuple[str, str], List[float]]]:
    rng = random.Random(seed)
    bootstrap_arch_metrics: Dict[str, List[float]] = {arch_id: [] for arch_id in arch_list}
    bootstrap_pair_metrics: Dict[Tuple[str, str], List[float]] = {
        (arch_a, arch_b): [] for arch_a, arch_b in combinations(arch_list, 2)
    }

    sample_size = len(prompt_ids)
    if sample_size == 0:
        return bootstrap_arch_metrics, bootstrap_pair_metrics

    for _ in range(iterations):
        sampled_prompt_ids = [prompt_ids[rng.randrange(sample_size)] for _ in range(sample_size)]

        for arch_id in arch_list:
            values = [
                prompt_weighted_ranks[prompt_id][arch_id]
                for prompt_id in sampled_prompt_ids
                if arch_id in prompt_weighted_ranks[prompt_id]
            ]
            bootstrap_arch_metrics[arch_id].append(_mean(values))

        for arch_a, arch_b in combinations(arch_list, 2):
            wins_a = 0
            wins_b = 0
            for prompt_id in sampled_prompt_ids:
                result = prompt_pairwise_winners.get((arch_a, arch_b), {}).get(prompt_id)
                if result == 1:
                    wins_a += 1
                elif result == -1:
                    wins_b += 1
            non_tied_total = wins_a + wins_b
            bootstrap_pair_metrics[(arch_a, arch_b)].append(
                (wins_a / non_tied_total) if non_tied_total else float("nan")
            )

    return bootstrap_arch_metrics, bootstrap_pair_metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate subject answers into long-form rankings and confidence-weighted RQ1 metrics."
        )
    )
    parser.add_argument(
        "--answers-dir",
        help=(
            "Directory containing answers_*.csv files. If omitted, uses "
            "out/RQ1/<run_id> for the selected/first run."
        ),
    )
    parser.add_argument(
        "--run-id",
        "--run-group-id",
        dest="run_id",
        help=(
            "Run folder id inside the runs directory "
            "(alias: --run-group-id). Used when --answers-dir is omitted."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RQ1_RUNS_DIR),
        help=(
            "Directory containing run folders "
            f"(default: {DEFAULT_RQ1_RUNS_DIR})"
        ),
    )
    parser.add_argument(
        "--key",
        help="Key CSV to use for all answers files (default: <answers-dir>/key.csv)",
    )
    parser.add_argument(
        "--out",
        help="Output CSV path (default: <answers-dir>/combined_rankings.csv)",
    )
    parser.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=DEFAULT_BOOTSTRAP_ITERATIONS,
        help=(
            "Number of prompt bootstrap iterations for confidence intervals "
            f"(default: {DEFAULT_BOOTSTRAP_ITERATIONS})"
        ),
    )
    parser.add_argument(
        "--bootstrap-seed",
        type=int,
        default=DEFAULT_BOOTSTRAP_SEED,
        help=(
            "Random seed used for bootstrap resampling "
            f"(default: {DEFAULT_BOOTSTRAP_SEED})"
        ),
    )
    parser.add_argument(
        "--plot-format",
        default="png",
        help="Plot file format for generated RQ1 figures (default: png)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="DPI for generated plots (default: 200)",
    )
    args = parser.parse_args()

    answers_dir = _resolve_answers_dir(args)
    if not answers_dir.exists():
        raise SystemExit(f"answers-dir not found: {answers_dir}")

    answers_files = sorted(answers_dir.glob("answers_*.csv"))
    if not answers_files:
        raise SystemExit(f"No answers_*.csv files found in: {answers_dir}")
    if args.bootstrap_iterations <= 0:
        raise SystemExit("--bootstrap-iterations must be a positive integer")

    out_path = pathlib.Path(args.out) if args.out else answers_dir / "combined_rankings.csv"
    key_path = pathlib.Path(args.key) if args.key else (answers_dir / "key.csv")
    if not key_path.exists():
        raise SystemExit(f"Missing key: {key_path}")

    key_map = _load_key(key_path)
    prompt_label_map = _build_prompt_label_map(key_map)

    all_rows: List[Dict[str, str]] = []
    prompt_ratings: Dict[str, List[PromptRating]] = {}
    arch_ids = set()

    for answers_path in answers_files:
        subject_id = answers_path.stem.replace("answers_", "", 1)
        seen_prompts_for_subject = set()
        with answers_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            if not reader.fieldnames:
                continue
            rank_cols = _rank_columns(reader.fieldnames)
            if not rank_cols:
                raise SystemExit(f"No rank columns found in {answers_path.name}")
            if "confidence" not in reader.fieldnames:
                raise SystemExit(f"Missing confidence column in {answers_path.name}")

            for row in reader:
                prompt_id = (row.get("prompt_id") or "").strip()
                if not prompt_id:
                    continue
                if prompt_id in seen_prompts_for_subject:
                    raise SystemExit(
                        f"Duplicate prompt '{prompt_id}' found in {answers_path.name}"
                    )
                seen_prompts_for_subject.add(prompt_id)
                prompt_key_rows = prompt_label_map.get(prompt_id)
                if not prompt_key_rows:
                    raise SystemExit(
                        f"Prompt '{prompt_id}' in {answers_path.name} is missing from key.csv"
                    )

                ordered_labels = _extract_ranked_labels(
                    row,
                    rank_cols,
                    answers_path=answers_path,
                    prompt_id=prompt_id,
                    prompt_key_rows=prompt_key_rows,
                )
                confidence = (row.get("confidence") or "").strip().upper()
                confidence_weight = _confidence_to_weight(
                    confidence,
                    answers_path=answers_path,
                    prompt_id=prompt_id,
                )

                ranks_by_arch: Dict[str, int] = {}
                for rank_position, label in enumerate(ordered_labels, start=1):
                    key_row = prompt_key_rows[label]
                    arch_id = key_row.get("arch_id", "").strip()
                    if not arch_id:
                        raise SystemExit(
                            f"Missing arch_id for prompt '{prompt_id}', label '{label}' in key.csv"
                        )
                    arch_ids.add(arch_id)
                    ranks_by_arch[arch_id] = rank_position
                    all_rows.append(
                        {
                            "subject_id": subject_id,
                            "prompt_id": prompt_id,
                            "rank_position": str(rank_position),
                            "label": label,
                            "arch_id": arch_id,
                            "confidence": confidence,
                            "confidence_weight": _format_float(confidence_weight),
                            "run_id": key_row.get("run_id", ""),
                            "run_group_id": key_row.get("run_group_id", ""),
                            "run_dir": sanitize_run_dir(key_row.get("run_dir", "")),
                        }
                    )

                prompt_ratings.setdefault(prompt_id, []).append(
                    PromptRating(
                        subject_id=subject_id,
                        confidence=confidence,
                        confidence_weight=confidence_weight,
                        ranks_by_arch=ranks_by_arch,
                    )
                )

    arch_list = _ordered_arches(arch_ids)
    prompt_ids = sorted(prompt_ratings)
    if not arch_list:
        raise SystemExit("No architectures were found in the answers data.")
    if not prompt_ids:
        raise SystemExit("No prompts were found in the answers data.")

    prompt_weighted_ranks = {
        prompt_id: _weighted_prompt_rank(prompt_ratings[prompt_id])
        for prompt_id in prompt_ids
    }
    prompt_pairwise_winners: Dict[Tuple[str, str], Dict[str, int]] = {}
    for arch_a, arch_b in combinations(arch_list, 2):
        pair_outcomes: Dict[str, int] = {}
        for prompt_id in prompt_ids:
            outcome = _weighted_pairwise_prompt_winner(
                prompt_ratings[prompt_id], arch_a, arch_b
            )
            if outcome is not None:
                pair_outcomes[prompt_id] = outcome
        prompt_pairwise_winners[(arch_a, arch_b)] = pair_outcomes

    bootstrap_arch_metrics, bootstrap_pair_metrics = _bootstrap_metrics(
        prompt_ids,
        arch_list,
        prompt_weighted_ranks,
        prompt_pairwise_winners,
        iterations=args.bootstrap_iterations,
        seed=args.bootstrap_seed,
    )

    avg_prompt_rank_metrics_path = answers_dir / "metrics_avg_prompt_rank.csv"
    pairwise_metrics_path = answers_dir / "metrics_pairwise.csv"

    _write_combined_rankings(out_path, all_rows)
    _write_avg_prompt_rank_metrics(
        avg_prompt_rank_metrics_path,
        arch_list,
        prompt_weighted_ranks,
        bootstrap_arch_metrics,
    )
    _write_pairwise_metrics(
        pairwise_metrics_path,
        arch_list,
        prompt_pairwise_winners,
        bootstrap_pair_metrics,
    )
    _generate_plots(
        answers_dir,
        arch_list,
        avg_prompt_rank_metrics_path,
        pairwise_metrics_path,
        plot_format=args.plot_format,
        dpi=args.dpi,
    )

    print(f"Wrote combined rankings: {out_path}")
    print(f"Wrote metrics: {avg_prompt_rank_metrics_path}")
    print(f"Wrote metrics: {pairwise_metrics_path}")


if __name__ == "__main__":
    main()
