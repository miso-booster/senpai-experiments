import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from app.setup_configuration import OUT_DIR, RUNS_DIR
except Exception:  # Supports `python app/rq3/tool_consistency.py` without package imports
    _ROOT = Path(__file__).resolve().parents[2]
    OUT_DIR = _ROOT / "out"
    RUNS_DIR = OUT_DIR / "runs"

try:
    from .excel import save_outputs
except ImportError:  # Supports `python app/rq3/tool_consistency.py`
    from excel import save_outputs


DEFAULT_RUNS_DIR = RUNS_DIR / "advanced_prompt_arch_comparison"
DEFAULT_OUT_DIR = OUT_DIR / "RQ3_tool_consistency_and_node_usage_consistency"
DEFAULT_GRAPH_ARCHITECTURE = "graph_based_architecture"

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
class PromptRunItems:
    run_folder: str
    tracing_xlsx: str
    conversation_id: str
    architecture: str
    prompt_key: str
    prompt_id: str
    difficulty: str
    target: str
    item_sequence: tuple[str, ...]


@dataclass(frozen=True)
class ConsistencyTables:
    overall_summary: pd.DataFrame
    prompt_summary: pd.DataFrame
    run_level: pd.DataFrame
    presence: pd.DataFrame


@dataclass(frozen=True)
class RQ3Results:
    tracing_paths: tuple[Path, ...]
    tool: ConsistencyTables
    graph: ConsistencyTables


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "RQ3: Measure tool-selection consistency and graph-node consistency "
            "across repeated runs using LangSmith tracing workbooks (tracing_*.xlsx)."
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
        "--graph-architecture-prefix",
        default=DEFAULT_GRAPH_ARCHITECTURE,
        help=(
            "Conversation ID prefix used to identify the graph architecture "
            f"(default: {DEFAULT_GRAPH_ARCHITECTURE})"
        ),
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


def _extract_architecture(conversation_id: str) -> str:
    head, _, _tail = conversation_id.partition("__")
    return head.strip().lower()


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


def _parse_metadata_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text.startswith("{"):
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _coerce_sort_number(value: object) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return float("inf")
    return num if math.isfinite(num) else float("inf")


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


def _sequence_signature(seq: list[str] | tuple[str, ...]) -> str:
    return " > ".join(seq)


def _set_signature(seq: list[str] | tuple[str, ...]) -> str:
    return " | ".join(sorted(set(seq)))


def _multiset_signature(seq: list[str] | tuple[str, ...]) -> str:
    c = Counter(seq)
    return " | ".join(f"{tool}x{c[tool]}" for tool in sorted(c))


def extract_prompt_run_sequences(df: pd.DataFrame) -> list[PromptRunItems]:
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

    records: list[PromptRunItems] = []
    for conversation_id, group in tool_rows.groupby("conversation_id", sort=False, dropna=True):
        if pd.isna(conversation_id):
            continue
        conv = str(conversation_id)
        prompt_key = _normalize_prompt_key(conv)
        prompt_id, difficulty, target = _extract_prompt_meta(conv)
        seq = tuple(group["name"].dropna().astype(str).tolist())
        if not seq:
            continue
        records.append(
            PromptRunItems(
                run_folder=str(group["source_run_folder"].iloc[0]),
                tracing_xlsx=str(group["source_tracing_xlsx"].iloc[0]),
                conversation_id=conv,
                architecture=_extract_architecture(conv),
                prompt_key=prompt_key,
                prompt_id=prompt_id,
                difficulty=difficulty,
                target=target,
                item_sequence=seq,
            )
        )
    return records


def extract_graph_prompt_run_sequences(
    df: pd.DataFrame,
    graph_architecture_prefix: str = DEFAULT_GRAPH_ARCHITECTURE,
) -> list[PromptRunItems]:
    if df.empty:
        return []

    conv_series = df["conversation_id"].astype("string").fillna("")
    arch_prefix = f"{graph_architecture_prefix}__"
    graph_rows = df[conv_series.str.startswith(arch_prefix)].copy()
    if graph_rows.empty:
        return []

    records: list[PromptRunItems] = []
    for conversation_id, group in graph_rows.groupby("conversation_id", sort=False, dropna=True):
        if pd.isna(conversation_id):
            continue
        conv = str(conversation_id)
        node_rows: list[tuple[float, pd.Timestamp, int, str]] = []
        chain_group = group[group["run_type"].astype("string").str.lower() == "chain"]
        for _, row in chain_group.iterrows():
            metadata = _parse_metadata_object(row.get("metadata"))
            node = metadata.get("langgraph_node")
            if not node:
                continue
            if _coerce_sort_number(metadata.get("ls_run_depth")) != 1:
                continue
            start_time = row.get("_start_time_dt")
            if pd.isna(start_time):
                start_time = pd.Timestamp.max
            node_rows.append(
                (
                    _coerce_sort_number(metadata.get("langgraph_step")),
                    start_time,
                    int(row.get("_row_pos", 0)),
                    str(node),
                )
            )

        if not node_rows:
            continue

        node_rows.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        seq = tuple(node for _, _, _, node in node_rows)
        prompt_key = _normalize_prompt_key(conv)
        prompt_id, difficulty, target = _extract_prompt_meta(conv)
        records.append(
            PromptRunItems(
                run_folder=str(group["source_run_folder"].iloc[0]),
                tracing_xlsx=str(group["source_tracing_xlsx"].iloc[0]),
                conversation_id=conv,
                architecture=_extract_architecture(conv),
                prompt_key=prompt_key,
                prompt_id=prompt_id,
                difficulty=difficulty,
                target=target,
                item_sequence=seq,
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


def _mode_count_and_value(series: pd.Series) -> tuple[int, str]:
    counts = series.value_counts(dropna=False)
    if counts.empty:
        return 0, ""
    top_value = counts.index[0]
    top_count = int(counts.iloc[0])
    return top_count, "" if pd.isna(top_value) else str(top_value)


def _build_run_level_table(
    records: list[PromptRunItems],
    *,
    item_prefix: str,
    item_plural: str,
    count_column: str,
) -> pd.DataFrame:
    rows = []
    for r in records:
        seq = list(r.item_sequence)
        counter = Counter(seq)
        rows.append(
            {
                "architecture": r.architecture,
                "run_folder": r.run_folder,
                "tracing_xlsx": r.tracing_xlsx,
                "conversation_id": r.conversation_id,
                "prompt_key": r.prompt_key,
                "prompt_id": r.prompt_id,
                "difficulty": r.difficulty,
                "target": r.target,
                count_column: len(seq),
                f"n_unique_{item_plural}": len(set(seq)),
                f"{item_prefix}_sequence_json": json.dumps(seq),
                f"{item_prefix}_sequence_sig": _sequence_signature(seq),
                f"{item_prefix}_set_sig": _set_signature(seq),
                f"{item_prefix}_multiset_sig": _multiset_signature(seq),
                f"{item_prefix}_counts_json": json.dumps(dict(sorted(counter.items()))),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_prompt_id_num"] = out["prompt_id"].map(_prompt_id_num)
    sort_cols = [c for c in ("architecture", "_prompt_id_num", "prompt_id", "prompt_key", "run_folder") if c in out.columns]
    out = out.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return out.drop(columns=["_prompt_id_num"], errors="ignore")


def build_run_level_table(records: list[PromptRunItems]) -> pd.DataFrame:
    return _build_run_level_table(records, item_prefix="tool", item_plural="tools", count_column="n_tool_calls")


def build_graph_run_level_table(records: list[PromptRunItems]) -> pd.DataFrame:
    return _build_run_level_table(
        records,
        item_prefix="graph_node",
        item_plural="graph_nodes",
        count_column="n_graph_nodes",
    )


def _build_prompt_consistency_summary(
    run_level: pd.DataFrame,
    *,
    item_prefix: str,
    count_column: str,
    count_prefix: str,
) -> pd.DataFrame:
    if run_level.empty:
        return pd.DataFrame()

    rows = []
    sequence_sig_col = f"{item_prefix}_sequence_sig"
    set_sig_col = f"{item_prefix}_set_sig"
    multiset_sig_col = f"{item_prefix}_multiset_sig"
    sequence_json_col = f"{item_prefix}_sequence_json"

    grouped = run_level.groupby(["prompt_key"], sort=True, dropna=False)
    for prompt_key, g in grouped:
        g = g.sort_values(["run_folder"], kind="stable")
        n_runs = len(g)
        seq_values = g[sequence_sig_col].fillna("").astype(str).tolist()
        set_values = g[set_sig_col].fillna("").astype(str).tolist()
        multiset_values = g[multiset_sig_col].fillna("").astype(str).tolist()
        seq_lists = [json.loads(s) for s in g[sequence_json_col].astype(str)]
        sets = [set(seq) for seq in seq_lists]
        counters = [Counter(seq) for seq in seq_lists]

        seq_mode_count, seq_mode_value = _mode_count_and_value(g[sequence_sig_col])
        set_mode_count, set_mode_value = _mode_count_and_value(g[set_sig_col])
        multiset_mode_count, multiset_mode_value = _mode_count_and_value(g[multiset_sig_col])

        prompt_id = g["prompt_id"].dropna().astype(str).iloc[0] if g["prompt_id"].notna().any() else ""
        difficulty = g["difficulty"].dropna().astype(str).iloc[0] if g["difficulty"].notna().any() else ""
        target = g["target"].dropna().astype(str).iloc[0] if g["target"].notna().any() else ""
        architecture = g["architecture"].dropna().astype(str).iloc[0] if g["architecture"].notna().any() else ""
        n_counts = pd.to_numeric(g[count_column], errors="coerce")

        rows.append(
            {
                "architecture": architecture,
                "prompt_key": prompt_key,
                "prompt_id": prompt_id,
                "difficulty": difficulty,
                "target": target,
                "n_runs_observed": n_runs,
                "n_distinct_sequences": g[sequence_sig_col].nunique(dropna=False),
                "n_distinct_item_sets": g[set_sig_col].nunique(dropna=False),
                "n_distinct_item_multisets": g[multiset_sig_col].nunique(dropna=False),
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
                f"{count_prefix}_mean": n_counts.mean(skipna=True),
                f"{count_prefix}_std": n_counts.std(skipna=True, ddof=1),
                f"{count_prefix}_min": n_counts.min(skipna=True),
                f"{count_prefix}_max": n_counts.max(skipna=True),
            }
        )

    out = pd.DataFrame(rows)
    out["_prompt_id_num"] = out["prompt_id"].map(_prompt_id_num)
    sort_cols = [c for c in ("architecture", "_prompt_id_num", "prompt_id", "prompt_key") if c in out.columns]
    out = out.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return out.drop(columns=["_prompt_id_num"], errors="ignore")


def build_prompt_consistency_summary(run_level: pd.DataFrame) -> pd.DataFrame:
    return _build_prompt_consistency_summary(
        run_level,
        item_prefix="tool",
        count_column="n_tool_calls",
        count_prefix="tool_calls",
    )


def build_graph_prompt_consistency_summary(run_level: pd.DataFrame) -> pd.DataFrame:
    return _build_prompt_consistency_summary(
        run_level,
        item_prefix="graph_node",
        count_column="n_graph_nodes",
        count_prefix="graph_nodes",
    )


def _build_presence_table(
    run_level: pd.DataFrame,
    *,
    item_prefix: str,
    item_name_column: str,
) -> pd.DataFrame:
    if run_level.empty:
        return pd.DataFrame()

    expanded_rows = []
    sequence_json_col = f"{item_prefix}_sequence_json"
    for _, row in run_level.iterrows():
        seq = json.loads(str(row[sequence_json_col]))
        counter = Counter(seq)
        for item_name in sorted(set(seq)):
            expanded_rows.append(
                {
                    "architecture": row.get("architecture", ""),
                    "prompt_key": row["prompt_key"],
                    "prompt_id": row["prompt_id"],
                    "difficulty": row.get("difficulty", ""),
                    "target": row.get("target", ""),
                    "run_folder": row["run_folder"],
                    item_name_column: item_name,
                    "present": 1,
                    "count_in_run": counter[item_name],
                }
            )

    expanded = pd.DataFrame(expanded_rows)
    if expanded.empty:
        return pd.DataFrame()

    group_cols = ["architecture", "prompt_key", "prompt_id", "difficulty", "target", item_name_column]
    summary = (
        expanded.groupby(group_cols, dropna=False)
        .agg(
            n_runs_with_item=("present", "sum"),
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
    summary["presence_rate_across_runs"] = summary["n_runs_with_item"] / summary["n_runs_observed"]

    summary["_prompt_id_num"] = summary["prompt_id"].map(_prompt_id_num)
    sort_cols = ["architecture", "_prompt_id_num", "prompt_id", item_name_column, "prompt_key"]
    summary = summary.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return summary.drop(columns=["_prompt_id_num"], errors="ignore")


def build_tool_presence_table(run_level: pd.DataFrame) -> pd.DataFrame:
    return _build_presence_table(run_level, item_prefix="tool", item_name_column="tool_name")


def build_graph_node_presence_table(run_level: pd.DataFrame) -> pd.DataFrame:
    return _build_presence_table(run_level, item_prefix="graph_node", item_name_column="graph_node_name")


def _build_overall_summary(
    prompt_summary: pd.DataFrame,
    run_level: pd.DataFrame,
    presence: pd.DataFrame,
    *,
    count_column: str,
    count_prefix: str,
    item_plural: str,
    item_name_column: str,
) -> pd.DataFrame:
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

    architectures = sorted(run_level["architecture"].dropna().astype(str).unique()) if "architecture" in run_level.columns else []
    n_prompts = int(prompt_summary["prompt_key"].nunique())
    n_prompt_runs = int(len(run_level))
    n_runs_unique = int(run_level["run_folder"].nunique()) if not run_level.empty else 0

    row = {
        "architectures": " | ".join(architectures),
        "n_architectures": len(architectures),
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
        f"mean_{count_prefix}_per_prompt_run": pd.to_numeric(run_level[count_column], errors="coerce").mean(skipna=True),
        f"std_{count_prefix}_per_prompt_run": pd.to_numeric(run_level[count_column], errors="coerce").std(skipna=True, ddof=1),
        f"n_distinct_{item_plural}_used_total": int(presence[item_name_column].nunique()) if not presence.empty else 0,
    }
    return pd.DataFrame([row])


def build_overall_summary(prompt_summary: pd.DataFrame, run_level: pd.DataFrame, tool_presence: pd.DataFrame) -> pd.DataFrame:
    return _build_overall_summary(
        prompt_summary,
        run_level,
        tool_presence,
        count_column="n_tool_calls",
        count_prefix="tool_calls",
        item_plural="tools",
        item_name_column="tool_name",
    )


def build_graph_overall_summary(
    prompt_summary: pd.DataFrame,
    run_level: pd.DataFrame,
    graph_presence: pd.DataFrame,
) -> pd.DataFrame:
    return _build_overall_summary(
        prompt_summary,
        run_level,
        graph_presence,
        count_column="n_graph_nodes",
        count_prefix="graph_nodes",
        item_plural="graph_nodes",
        item_name_column="graph_node_name",
    )


def build_rq3_results(
    runs_dir: Path,
    trace_glob: str,
    sheet_name: str | None,
    *,
    graph_architecture_prefix: str = DEFAULT_GRAPH_ARCHITECTURE,
) -> RQ3Results:
    tracing_paths = discover_tracing_workbooks(runs_dir, trace_glob)

    all_tool_records: list[PromptRunItems] = []
    all_graph_records: list[PromptRunItems] = []
    for tracing_path in tracing_paths:
        df = load_tracing_workbook(tracing_path, sheet_name)
        if df.empty:
            continue
        all_tool_records.extend(extract_prompt_run_sequences(df))
        all_graph_records.extend(
            extract_graph_prompt_run_sequences(df, graph_architecture_prefix=graph_architecture_prefix)
        )

    tool_run_level = build_run_level_table(all_tool_records)
    tool_prompt_summary = build_prompt_consistency_summary(tool_run_level)
    tool_presence = build_tool_presence_table(tool_run_level)
    tool_overall_summary = build_overall_summary(tool_prompt_summary, tool_run_level, tool_presence)

    graph_run_level = build_graph_run_level_table(all_graph_records)
    graph_prompt_summary = build_graph_prompt_consistency_summary(graph_run_level)
    graph_presence = build_graph_node_presence_table(graph_run_level)
    graph_overall_summary = build_graph_overall_summary(graph_prompt_summary, graph_run_level, graph_presence)

    if tool_run_level.empty and graph_run_level.empty:
        raise SystemExit(
            "No tool rows (`run_type == tool`) or graph node rows (`metadata.langgraph_node`) "
            "found in the discovered tracing workbooks."
        )

    return RQ3Results(
        tracing_paths=tuple(tracing_paths),
        tool=ConsistencyTables(
            overall_summary=tool_overall_summary,
            prompt_summary=tool_prompt_summary,
            run_level=tool_run_level,
            presence=tool_presence,
        ),
        graph=ConsistencyTables(
            overall_summary=graph_overall_summary,
            prompt_summary=graph_prompt_summary,
            run_level=graph_run_level,
            presence=graph_presence,
        ),
    )


def _format_float(value: float | int | None, ndigits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "nan"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{ndigits}f}"


def _print_summary(label: str, tables: ConsistencyTables) -> None:
    print(f"{label}:")
    print(f"  Prompt-runs observed: {len(tables.run_level)}")
    print(f"  Unique prompts: {tables.run_level['prompt_key'].nunique() if not tables.run_level.empty else 0}")
    if tables.overall_summary.empty:
        print("  No rows available.")
        return
    row = tables.overall_summary.iloc[0]
    print(f"  Exact sequence (mean): {_format_float(row.get('mean_exact_sequence_consistency'))}")
    print(f"  Exact set (mean): {_format_float(row.get('mean_exact_set_consistency'))}")
    print(f"  Exact multiset (mean): {_format_float(row.get('mean_exact_multiset_consistency'))}")
    print(f"  Pairwise set Jaccard (mean): {_format_float(row.get('mean_pairwise_set_jaccard'))}")
    print(f"  Pairwise multiset Jaccard (mean): {_format_float(row.get('mean_pairwise_multiset_jaccard'))}")


def main() -> None:
    args = parse_args()

    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)
    results = build_rq3_results(
        runs_dir,
        args.trace_glob,
        args.sheet,
        graph_architecture_prefix=args.graph_architecture_prefix,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    workbook_path = save_outputs(
        out_dir,
        results.tool.overall_summary,
        results.tool.prompt_summary,
        results.tool.run_level,
        results.tool.presence,
        graph_overall_summary=results.graph.overall_summary,
        graph_prompt_summary=results.graph.prompt_summary,
        graph_run_level=results.graph.run_level,
        graph_presence=results.graph.presence,
        export_csvs=args.export_csvs,
    )

    print(f"Discovered tracing workbooks: {len(results.tracing_paths)}")
    print(f"Wrote workbook: {workbook_path}")
    _print_summary("Tool consistency", results.tool)
    _print_summary("Graph consistency", results.graph)


if __name__ == "__main__":
    main()
