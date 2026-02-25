import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    from app.setup_configuration import OUT_DIR, RUNS_DIR
except Exception:  # Supports `python app/rq3_tool_consistency.py` without package imports
    _ROOT = Path(__file__).resolve().parent.parent
    OUT_DIR = _ROOT / "out"
    RUNS_DIR = OUT_DIR / "runs"

try:
    from app.rq3_excel import save_outputs
except ModuleNotFoundError:  # Supports `python app/rq3_tool_consistency.py`
    from rq3_excel import save_outputs


DEFAULT_RUNS_DIR = RUNS_DIR / "tool_consistency"
DEFAULT_OUT_DIR = OUT_DIR / "RQ3_tool_consistency"

HEX_SUFFIX_RE = re.compile(r"__(?:[0-9a-f]{8,})$", re.IGNORECASE)
PROMPT_ID_RE = re.compile(r"__(p\d+)_", re.IGNORECASE)
PROMPT_META_RE = re.compile(
    r"__"
    r"(?P<prompt_id>p\d+)_"
    r"(?P<difficulty>basic|intermediate|complex)__"
    r"(?P<project>[^_]+(?:_[^_]+)*)__"
    r"(?P<target>profile|rule)",
    re.IGNORECASE,
)


def _prompt_id_num(value: object) -> int:
    text = "" if value is None else str(value).strip().lower()
    m = re.fullmatch(r"p(\d+)", text)
    return int(m.group(1)) if m else 10**9


@dataclass(frozen=True)
class PromptRunTools:
    run_folder: str
    tracing_xlsx: str
    conversation_id: str
    prompt_key: str
    prompt_id: str
    difficulty: str
    target: str
    tool_sequence: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "RQ3: Measure tool-selection consistency across repeated runs using "
            "LangSmith tracing workbooks (tracing_*.xlsx)."
        )
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Directory containing repeated run folders (default: {DEFAULT_RUNS_DIR})",
    )
    parser.add_argument(
        "--trace-glob",
        default="*/tracing_*.xlsx",
        help="Glob relative to runs-dir used to discover tracing workbooks (default: */tracing_*.xlsx)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory for RQ3 tables/workbook (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--sheet",
        help="Optional sheet name in each tracing workbook (default: first sheet)",
    )
    parser.add_argument(
        "--export-csvs",
        action="store_true",
        help="Also export CSV files in addition to the Excel workbook",
    )
    return parser.parse_args()


def discover_tracing_workbooks(runs_dir: Path, trace_glob: str) -> list[Path]:
    if not runs_dir.exists():
        raise SystemExit(f"runs-dir not found: {runs_dir}")
    if not runs_dir.is_dir():
        raise SystemExit(f"runs-dir is not a directory: {runs_dir}")
    paths = sorted(p for p in runs_dir.glob(trace_glob) if p.is_file())
    if not paths:
        raise SystemExit(f"No tracing workbooks found in {runs_dir} with glob {trace_glob!r}")
    return paths


def _choose_sheet(path: Path, sheet_name: str | None) -> str:
    if sheet_name:
        return sheet_name
    xl = pd.ExcelFile(path)
    if not xl.sheet_names:
        raise ValueError("Workbook has no sheets")
    return xl.sheet_names[0]


def _clean_string_series(series: pd.Series) -> pd.Series:
    out = series.astype("string").str.strip()
    return out.mask(out == "", pd.NA)


def _normalize_prompt_key(conversation_id: str) -> str:
    return HEX_SUFFIX_RE.sub("", conversation_id)


def _extract_prompt_meta(conversation_id: str) -> tuple[str, str, str]:
    norm = _normalize_prompt_key(conversation_id)
    m = PROMPT_META_RE.search(norm)
    if m:
        return (
            (m.group("prompt_id") or "").lower(),
            (m.group("difficulty") or "").lower(),
            (m.group("target") or "").lower(),
        )
    m2 = PROMPT_ID_RE.search(norm)
    prompt_id = (m2.group(1) if m2 else norm).lower()
    return prompt_id, "", ""


def load_tracing_workbook(path: Path, sheet_name: str | None) -> pd.DataFrame:
    chosen_sheet = _choose_sheet(path, sheet_name)
    df = pd.read_excel(path, sheet_name=chosen_sheet)
    if df.empty:
        return df

    df = df.copy()
    df["source_tracing_xlsx"] = str(path)
    df["source_run_folder"] = path.parent.name

    for col in ("conversation_id", "run_type", "name", "start_time"):
        if col in df.columns:
            df[col] = _clean_string_series(df[col])

    if "run_type" not in df.columns or "name" not in df.columns or "conversation_id" not in df.columns:
        missing = [c for c in ("conversation_id", "run_type", "name") if c not in df.columns]
        raise ValueError(f"Missing required columns in {path.name}: {', '.join(missing)}")

    if "start_time" in df.columns:
        df["_start_time_dt"] = pd.to_datetime(df["start_time"], errors="coerce")
    else:
        df["_start_time_dt"] = pd.NaT

    if "execution_order" in df.columns:
        df["_execution_order_num"] = pd.to_numeric(df["execution_order"], errors="coerce")
    else:
        df["_execution_order_num"] = math.nan

    df["_row_pos"] = range(len(df))
    return df


def _sequence_signature(seq: Iterable[str]) -> str:
    return " > ".join(seq)


def _set_signature(seq: Iterable[str]) -> str:
    return " | ".join(sorted(set(seq)))


def _multiset_signature(seq: Iterable[str]) -> str:
    c = Counter(seq)
    return " | ".join(f"{tool}x{c[tool]}" for tool in sorted(c))


def extract_prompt_run_sequences(df: pd.DataFrame) -> list[PromptRunTools]:
    tool_rows = df[df["run_type"].astype("string").str.lower() == "tool"].copy()
    if tool_rows.empty:
        return []

    sort_cols = []
    if "_start_time_dt" in tool_rows.columns:
        sort_cols.append("_start_time_dt")
    if "_execution_order_num" in tool_rows.columns:
        sort_cols.append("_execution_order_num")
    sort_cols.append("_row_pos")
    tool_rows = tool_rows.sort_values(sort_cols, na_position="last")

    records: list[PromptRunTools] = []
    for conversation_id, group in tool_rows.groupby("conversation_id", sort=False, dropna=True):
        if pd.isna(conversation_id):
            continue
        conv = str(conversation_id)
        prompt_key = _normalize_prompt_key(conv)
        prompt_id, difficulty, target = _extract_prompt_meta(conv)
        seq = tuple(group["name"].dropna().astype(str).tolist())
        records.append(
            PromptRunTools(
                run_folder=str(group["source_run_folder"].iloc[0]),
                tracing_xlsx=str(group["source_tracing_xlsx"].iloc[0]),
                conversation_id=conv,
                prompt_key=prompt_key,
                prompt_id=prompt_id,
                difficulty=difficulty,
                target=target,
                tool_sequence=seq,
            )
        )
    return records


def _pairwise_exact_rate(values: list[str]) -> float:
    if len(values) < 2:
        return float("nan")
    pairs = list(combinations(values, 2))
    if not pairs:
        return float("nan")
    matches = sum(1 for a, b in pairs if a == b)
    return matches / len(pairs)


def _pairwise_jaccard_mean(sets: list[set[str]]) -> float:
    if len(sets) < 2:
        return float("nan")
    scores: list[float] = []
    for a, b in combinations(sets, 2):
        union = a | b
        if not union:
            scores.append(1.0)
        else:
            scores.append(len(a & b) / len(union))
    return float(sum(scores) / len(scores)) if scores else float("nan")


def _bag_jaccard(c1: Counter[str], c2: Counter[str]) -> float:
    keys = set(c1) | set(c2)
    if not keys:
        return 1.0
    num = sum(min(c1.get(k, 0), c2.get(k, 0)) for k in keys)
    den = sum(max(c1.get(k, 0), c2.get(k, 0)) for k in keys)
    if den == 0:
        return 1.0
    return num / den


def _pairwise_bag_jaccard_mean(counters: list[Counter[str]]) -> float:
    if len(counters) < 2:
        return float("nan")
    scores = [_bag_jaccard(a, b) for a, b in combinations(counters, 2)]
    return float(sum(scores) / len(scores)) if scores else float("nan")


def build_run_level_table(records: list[PromptRunTools]) -> pd.DataFrame:
    rows = []
    for r in records:
        seq = list(r.tool_sequence)
        counter = Counter(seq)
        rows.append(
            {
                "run_folder": r.run_folder,
                "tracing_xlsx": r.tracing_xlsx,
                "conversation_id": r.conversation_id,
                "prompt_key": r.prompt_key,
                "prompt_id": r.prompt_id,
                "difficulty": r.difficulty,
                "target": r.target,
                "n_tool_calls": len(seq),
                "n_unique_tools": len(set(seq)),
                "tool_sequence_json": json.dumps(seq),
                "tool_sequence_sig": _sequence_signature(seq),
                "tool_set_sig": _set_signature(seq),
                "tool_multiset_sig": _multiset_signature(seq),
                "tool_counts_json": json.dumps(dict(sorted(counter.items()))),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_prompt_id_num"] = out["prompt_id"].map(_prompt_id_num)
    sort_cols = [c for c in ("_prompt_id_num", "prompt_id", "prompt_key", "run_folder") if c in out.columns]
    out = out.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return out.drop(columns=["_prompt_id_num"], errors="ignore")


def _mode_count_and_value(series: pd.Series) -> tuple[int, str]:
    counts = series.value_counts(dropna=False)
    if counts.empty:
        return 0, ""
    top_value = counts.index[0]
    top_count = int(counts.iloc[0])
    return top_count, "" if pd.isna(top_value) else str(top_value)


def build_prompt_consistency_summary(run_level: pd.DataFrame) -> pd.DataFrame:
    if run_level.empty:
        return pd.DataFrame()

    rows = []
    grouped = run_level.groupby(["prompt_key"], sort=True, dropna=False)
    for prompt_key, g in grouped:
        g = g.sort_values(["run_folder"], kind="stable")
        n_runs = len(g)
        seq_values = g["tool_sequence_sig"].fillna("").astype(str).tolist()
        set_values = g["tool_set_sig"].fillna("").astype(str).tolist()
        multiset_values = g["tool_multiset_sig"].fillna("").astype(str).tolist()
        seq_lists = [json.loads(s) for s in g["tool_sequence_json"].astype(str)]
        sets = [set(seq) for seq in seq_lists]
        counters = [Counter(seq) for seq in seq_lists]

        seq_mode_count, seq_mode_value = _mode_count_and_value(g["tool_sequence_sig"])
        set_mode_count, set_mode_value = _mode_count_and_value(g["tool_set_sig"])
        multiset_mode_count, multiset_mode_value = _mode_count_and_value(g["tool_multiset_sig"])

        # All runs for a prompt should share these metadata values once normalized.
        prompt_id = g["prompt_id"].dropna().astype(str).iloc[0] if g["prompt_id"].notna().any() else ""
        difficulty = g["difficulty"].dropna().astype(str).iloc[0] if g["difficulty"].notna().any() else ""
        target = g["target"].dropna().astype(str).iloc[0] if g["target"].notna().any() else ""

        n_tool_calls = pd.to_numeric(g["n_tool_calls"], errors="coerce")

        rows.append(
            {
                "prompt_key": prompt_key,
                "prompt_id": prompt_id,
                "difficulty": difficulty,
                "target": target,
                "n_runs_observed": n_runs,
                "n_distinct_sequences": g["tool_sequence_sig"].nunique(dropna=False),
                "n_distinct_tool_sets": g["tool_set_sig"].nunique(dropna=False),
                "n_distinct_tool_multisets": g["tool_multiset_sig"].nunique(dropna=False),
                "exact_sequence_mode_count": seq_mode_count,
                "exact_sequence_consistency": (seq_mode_count / n_runs) if n_runs else float("nan"),
                "exact_sequence_mode": seq_mode_value,
                "exact_set_mode_count": set_mode_count,
                "exact_set_consistency": (set_mode_count / n_runs) if n_runs else float("nan"),
                "exact_set_mode": set_mode_value,
                "exact_multiset_mode_count": multiset_mode_count,
                "exact_multiset_consistency": (multiset_mode_count / n_runs) if n_runs else float("nan"),
                "exact_multiset_mode": multiset_mode_value,
                "pairwise_exact_sequence_rate": _pairwise_exact_rate(seq_values),
                "pairwise_exact_set_rate": _pairwise_exact_rate(set_values),
                "pairwise_exact_multiset_rate": _pairwise_exact_rate(multiset_values),
                "pairwise_set_jaccard_mean": _pairwise_jaccard_mean(sets),
                "pairwise_multiset_jaccard_mean": _pairwise_bag_jaccard_mean(counters),
                "tool_calls_mean": n_tool_calls.mean(skipna=True),
                "tool_calls_std": n_tool_calls.std(skipna=True, ddof=1),
                "tool_calls_min": n_tool_calls.min(skipna=True),
                "tool_calls_max": n_tool_calls.max(skipna=True),
            }
        )

    out = pd.DataFrame(rows)
    out["_prompt_id_num"] = out["prompt_id"].map(_prompt_id_num)
    sort_cols = [c for c in ("_prompt_id_num", "prompt_id", "prompt_key") if c in out.columns]
    out = out.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return out.drop(columns=["_prompt_id_num"], errors="ignore")


def build_tool_presence_table(run_level: pd.DataFrame) -> pd.DataFrame:
    if run_level.empty:
        return pd.DataFrame()

    expanded_rows = []
    for _, row in run_level.iterrows():
        seq = json.loads(str(row["tool_sequence_json"]))
        c = Counter(seq)
        for tool in sorted(set(seq)):
            expanded_rows.append(
                {
                    "prompt_key": row["prompt_key"],
                    "prompt_id": row["prompt_id"],
                    "difficulty": row.get("difficulty", ""),
                    "target": row.get("target", ""),
                    "run_folder": row["run_folder"],
                    "tool_name": tool,
                    "present": 1,
                    "count_in_run": c[tool],
                }
            )

    expanded = pd.DataFrame(expanded_rows)
    if expanded.empty:
        return pd.DataFrame()

    group_cols = ["prompt_key", "prompt_id", "difficulty", "target", "tool_name"]
    summary = (
        expanded.groupby(group_cols, dropna=False)
        .agg(
            n_runs_with_tool=("present", "sum"),
            mean_count_when_present=("count_in_run", "mean"),
            max_count_in_run=("count_in_run", "max"),
        )
        .reset_index()
    )

    runs_per_prompt = (
        run_level.groupby(["prompt_key"], dropna=False)["run_folder"]
        .nunique()
        .rename("n_runs_observed")
        .reset_index()
    )
    summary = summary.merge(runs_per_prompt, on="prompt_key", how="left")
    summary["presence_rate_across_runs"] = summary["n_runs_with_tool"] / summary["n_runs_observed"]

    summary["_prompt_id_num"] = summary["prompt_id"].map(_prompt_id_num)
    sort_cols = ["_prompt_id_num", "prompt_id", "tool_name", "prompt_key"]
    summary = summary.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return summary.drop(columns=["_prompt_id_num"], errors="ignore")


def build_overall_summary(prompt_summary: pd.DataFrame, run_level: pd.DataFrame, tool_presence: pd.DataFrame) -> pd.DataFrame:
    if prompt_summary.empty:
        return pd.DataFrame()

    def _weighted_mean(series: pd.Series, weights: pd.Series) -> float:
        valid = series.notna() & weights.notna()
        if not valid.any():
            return float("nan")
        s = series[valid].astype(float)
        w = weights[valid].astype(float)
        denom = w.sum()
        if denom == 0:
            return float("nan")
        return float((s * w).sum() / denom)

    n_prompts = int(prompt_summary["prompt_key"].nunique())
    n_prompt_runs = int(len(run_level))
    n_runs_unique = int(run_level["run_folder"].nunique()) if not run_level.empty else 0

    row = {
        "n_runs": n_runs_unique,
        "n_prompts": n_prompts,
        "n_prompt_runs": n_prompt_runs,
        "mean_exact_sequence_consistency": prompt_summary["exact_sequence_consistency"].mean(skipna=True),
        "mean_exact_set_consistency": prompt_summary["exact_set_consistency"].mean(skipna=True),
        "mean_exact_multiset_consistency": prompt_summary["exact_multiset_consistency"].mean(skipna=True),
        "mean_pairwise_set_jaccard": prompt_summary["pairwise_set_jaccard_mean"].mean(skipna=True),
        "mean_pairwise_multiset_jaccard": prompt_summary["pairwise_multiset_jaccard_mean"].mean(skipna=True),
        "weighted_mean_exact_sequence_consistency": _weighted_mean(
            prompt_summary["exact_sequence_consistency"], prompt_summary["n_runs_observed"]
        ),
        "weighted_mean_exact_set_consistency": _weighted_mean(
            prompt_summary["exact_set_consistency"], prompt_summary["n_runs_observed"]
        ),
        "weighted_mean_exact_multiset_consistency": _weighted_mean(
            prompt_summary["exact_multiset_consistency"], prompt_summary["n_runs_observed"]
        ),
        "mean_tool_calls_per_prompt_run": pd.to_numeric(run_level["n_tool_calls"], errors="coerce").mean(skipna=True),
        "std_tool_calls_per_prompt_run": pd.to_numeric(run_level["n_tool_calls"], errors="coerce").std(skipna=True, ddof=1),
        "n_distinct_tools_used_total": int(tool_presence["tool_name"].nunique()) if not tool_presence.empty else 0,
    }
    return pd.DataFrame([row])


def _format_float(value: float | int | None, ndigits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "nan"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{ndigits}f}"


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

    prompt_order = (
        prompt_summary.sort_values(["prompt_id", "prompt_key"], kind="stable")["prompt_id"].astype(str).tolist()
    )
    x = np.arange(len(prompt_order))

    # Plot 1: per-prompt consistency (exact match metrics)
    ps = prompt_summary.sort_values(["prompt_id", "prompt_key"], kind="stable").reset_index(drop=True)
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
            ax.set_xticks(np.arange(len(heat.columns)), labels=[str(c) for c in heat.columns], rotation=30, ha="right")
            ax.set_yticks(np.arange(len(heat.index)), labels=[str(i) for i in heat.index])
            ax.set_title("Tool Presence Rate Across Runs (per Prompt)")
            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label("Presence rate")

            for i in range(heat.shape[0]):
                for j in range(heat.shape[1]):
                    val = heat.iloc[i, j]
                    if pd.notna(val):
                        ax.text(j, i, f"{val:.1f}", ha="center", va="center", fontsize=8, color="black")
            _save(fig, "RQ3_tool_presence_heatmap")


def main() -> None:
    args = parse_args()

    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)
    tracing_paths = discover_tracing_workbooks(runs_dir, args.trace_glob)

    all_records: list[PromptRunTools] = []
    for tracing_path in tracing_paths:
        df = load_tracing_workbook(tracing_path, args.sheet)
        if df.empty:
            continue
        all_records.extend(extract_prompt_run_sequences(df))

    if not all_records:
        raise SystemExit("No tool rows (`run_type == tool`) found in the discovered tracing workbooks.")

    run_level = build_run_level_table(all_records)
    prompt_summary = build_prompt_consistency_summary(run_level)
    tool_presence = build_tool_presence_table(run_level)
    overall_summary = build_overall_summary(prompt_summary, run_level, tool_presence)

    out_dir.mkdir(parents=True, exist_ok=True)

    workbook_path = save_outputs(
        out_dir,
        overall_summary,
        prompt_summary,
        run_level,
        tool_presence,
        export_csvs=args.export_csvs,
    )

    # Console summary for quick inspection.
    print(f"Discovered tracing workbooks: {len(tracing_paths)}")
    print(f"Prompt-runs with tool calls: {len(run_level)}")
    print(f"Unique prompts: {run_level['prompt_key'].nunique()}")
    if not overall_summary.empty:
        r = overall_summary.iloc[0]
        print("Overall consistency:")
        print(f"  Exact sequence (mean): {_format_float(r.get('mean_exact_sequence_consistency'))}")
        print(f"  Exact tool set (mean): {_format_float(r.get('mean_exact_set_consistency'))}")
        print(f"  Exact tool multiset (mean): {_format_float(r.get('mean_exact_multiset_consistency'))}")
        print(f"  Pairwise set Jaccard (mean): {_format_float(r.get('mean_pairwise_set_jaccard'))}")
        print(f"  Pairwise multiset Jaccard (mean): {_format_float(r.get('mean_pairwise_multiset_jaccard'))}")

    # Show prompts sorted by worst exact sequence consistency.
    if not prompt_summary.empty:
        cols = [
            "prompt_id",
            "difficulty",
            "target",
            "n_runs_observed",
            "exact_sequence_consistency",
            "exact_set_consistency",
            "exact_multiset_consistency",
            "pairwise_set_jaccard_mean",
            "tool_calls_mean",
        ]
        preview = (
            prompt_summary.assign(_prompt_id_num=prompt_summary["prompt_id"].map(_prompt_id_num))
            .sort_values(["exact_sequence_consistency", "_prompt_id_num"], ascending=[True, True], kind="stable")[cols]
        )
        print("\nPer-prompt summary (lowest sequence consistency first):")
        print(preview.to_string(index=False))

    print(f"\nWrote: {workbook_path}")
    if args.export_csvs:
        print(f"Wrote CSVs under: {out_dir}")


if __name__ == "__main__":
    main()
