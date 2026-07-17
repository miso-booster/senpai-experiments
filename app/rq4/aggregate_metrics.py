import argparse
from itertools import combinations
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence

import pandas as pd
from scipy.stats import wilcoxon

try:
    from app.setup_configuration import (
        OUT_DIR,
        RQ4_EXPERIMENT_DIRNAME,
        resolve_model_output_dir,
        resolve_runs_dir,
        sanitize_path_component,
    )
except Exception:  # Supports `python app/rq4/aggregate_metrics.py`
    import re

    _ROOT = Path(__file__).resolve().parents[2]
    OUT_DIR = _ROOT / "out"

    def sanitize_path_component(value: str, *, field_name: str = "path component") -> str:
        sanitized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
        if not sanitized:
            raise ValueError(
                f"{field_name} must contain at least one alphanumeric character after sanitization: {value!r}"
            )
        return sanitized

    def resolve_runs_dir(experiment_dirname: str, model_label: str | None = None) -> Path:
        runs_dir = OUT_DIR / "runs"
        if not model_label:
            return runs_dir / experiment_dirname
        return runs_dir / sanitize_path_component(model_label, field_name="model label") / experiment_dirname

    def resolve_model_output_dir(base_dir: Path, model_label: str | None = None) -> Path:
        if not model_label:
            return base_dir
        return base_dir / sanitize_path_component(model_label, field_name="model label")

    RQ4_EXPERIMENT_DIRNAME = "guardrail_test"

try:
    from .excel import save_outputs
    from .plots import generate_plots
except ImportError:  # Supports `python app/rq4/aggregate_metrics.py`
    from excel import save_outputs
    from plots import generate_plots

DEFAULT_OUT_DIR = OUT_DIR / "RQ4_guardrail_metrics"
DEFAULT_PROMPT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "rq4_prompts.json"

METRICS: dict[str, str] = {
    "correct_behavior_int": "Correct behavior",
    "unsafe_allow_int": "Unsafe allow",
    "false_block_int": "False block",
    "latency_s": "Response time (s)",
    "total_input_tokens": "Input tokens",
    "llm_call_count": "LLM calls",
}

NUMERIC_COLUMNS = (
    "latency_s",
    "total_input_tokens",
    "llm_call_count",
    "answer_code_lines",
    "returncode",
    "timeout_s",
)

PAIRWISE_ID_COLUMNS = (
    "model_label",
    "run_group_id",
    "prompt_id",
    "prompt",
)


class RunSource(NamedTuple):
    workbook: Path
    runs_dir: Path
    model_label: str


def default_rq4_runs_dir(model_label: str | None = None) -> Path:
    return resolve_runs_dir(RQ4_EXPERIMENT_DIRNAME, model_label)


def default_rq4_out_dir(model_label: str | None = None) -> Path:
    return resolve_model_output_dir(DEFAULT_OUT_DIR, model_label)


def discover_model_run_dirs(runs_root: Path | None = None) -> list[tuple[str, Path]]:
    root = runs_root or (OUT_DIR / "runs")
    if not root.exists():
        return []
    discovered: list[tuple[str, Path]] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        rq4_dir = candidate / RQ4_EXPERIMENT_DIRNAME
        if rq4_dir.is_dir():
            discovered.append((candidate.name, rq4_dir))
    return discovered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate repeated guardrail-test runs into the RQ4 metrics workbook and plots."
    )
    parser.add_argument(
        "--model-label",
        help=(
            "Optional model label used to resolve model-specific run folders and "
            "default RQ4 output directories."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        help=(
            "Directory containing run folders "
            "(default: out/runs/guardrail_test or out/runs/<model-label>/guardrail_test)"
        ),
    )
    parser.add_argument(
        "--runs-root",
        help=(
            "Root directory containing <model-label>/guardrail_test folders for multi-model aggregation "
            "(default: out/runs). Ignored when --runs-dir or --model-label is used."
        ),
    )
    parser.add_argument(
        "--out-dir",
        help=(
            "Output directory for the RQ4 workbook and plots "
            "(default: out/RQ4_guardrail_metrics or out/RQ4_guardrail_metrics/<model-label>)"
        ),
    )
    parser.add_argument(
        "--prompt-config",
        default=str(DEFAULT_PROMPT_CONFIG),
        help=f"Prompt catalog JSON path (default: {DEFAULT_PROMPT_CONFIG})",
    )
    parser.add_argument(
        "--results-name",
        default="results.xlsx",
        help="Workbook filename inside each run folder (default: results.xlsx)",
    )
    parser.add_argument(
        "--sheet",
        help="Excel sheet name to read (default: first sheet)",
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
    parser.add_argument(
        "--no-export-csvs",
        action="store_true",
        help="Skip CSV exports and write the Excel workbook only",
    )
    parser.add_argument(
        "--no-detailed-sheets",
        action="store_true",
        help="Skip extra detailed workbook sheets",
    )
    return parser.parse_args()


def compute_a12(x: pd.Series, y: pd.Series) -> float:
    """Compute Vargha-Delaney A12 for two numeric samples."""
    x_vals = pd.to_numeric(x, errors="coerce").dropna().to_numpy(dtype=float)
    y_vals = pd.to_numeric(y, errors="coerce").dropna().to_numpy(dtype=float)
    if len(x_vals) == 0 or len(y_vals) == 0:
        return float("nan")

    diff = x_vals[:, None] - y_vals[None, :]
    wins = float((diff > 0).sum())
    ties = float((diff == 0).sum())
    return (wins + 0.5 * ties) / (len(x_vals) * len(y_vals))


def classify_a12_magnitude(a12: float) -> str:
    """Return an effect-size label for A12."""
    if pd.isna(a12):
        return "n/a"
    dominance = max(float(a12), 1.0 - float(a12))
    if dominance < 0.56:
        return "negligible"
    if dominance < 0.64:
        return "small"
    if dominance < 0.71:
        return "medium"
    return "large"


def _safe_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series
    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
        "1.0": True,
        "0.0": False,
        "yes": True,
        "no": False,
    }
    out = series.astype(str).str.strip().str.lower().map(mapping)
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_bool = numeric.map({1: True, 0: False})
    return out.where(out.notna(), numeric_bool)


def _clean_string_id(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned == "", pd.NA)


def _normalize_expected_decision(series: pd.Series) -> pd.Series:
    normalized = series.astype("string").str.strip().str.lower()
    return normalized.where(normalized.isin(["block", "allow"]), "block")


def _prompt_id_num(value: object) -> int:
    text = "" if value is None else str(value).strip().lower()
    if "_" in text:
        text = text.split("_", 1)[0]
    if text.startswith("p") and text[1:].isdigit():
        return int(text[1:])
    return 10**9


def discover_workbooks(runs_dir: Path, results_name: str) -> list[Path]:
    return sorted(p for p in runs_dir.glob(f"*/{results_name}") if p.is_file())


def discover_workbook_sources(
    run_dirs: Sequence[tuple[str, Path]],
    results_name: str,
) -> list[RunSource]:
    sources: list[RunSource] = []
    for model_label, runs_dir in run_dirs:
        sources.extend(
            RunSource(workbook=workbook, runs_dir=runs_dir, model_label=model_label)
            for workbook in discover_workbooks(runs_dir, results_name)
        )
    return sorted(sources, key=lambda source: (source.model_label, str(source.workbook)))


def load_workbook(path: Path, sheet_name: str | None, model_label: str | None = None) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    chosen_sheet = sheet_name or xl.sheet_names[0]
    df = pd.read_excel(path, sheet_name=chosen_sheet)
    if df.empty:
        return df

    df = df.copy()
    df["source_results_xlsx"] = str(path)
    df["source_run_folder"] = path.parent.name
    if model_label:
        df["model_label"] = model_label
    if "run_group_id" not in df.columns:
        df["run_group_id"] = path.parent.name
    else:
        missing = df["run_group_id"].isna() | (df["run_group_id"].astype(str).str.strip() == "")
        df.loc[missing, "run_group_id"] = path.parent.name
    return df


def load_all_results(workbooks: Sequence[Path], sheet_name: str | None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for wb in workbooks:
        try:
            frame = load_workbook(wb, sheet_name)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] Skipping {wb}: {exc}")
            continue
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True, sort=False)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "timed_out" in df.columns:
        df["timed_out"] = _safe_bool(df["timed_out"])
    if "fallback" in df.columns:
        df["fallback"] = _safe_bool(df["fallback"])
    for col in ("arch_id", "run_group_id", "prompt_id", "conversation_id"):
        if col in df.columns:
            df[col] = _clean_string_id(df[col])
    return df


def load_all_result_sources(sources: Sequence[RunSource], sheet_name: str | None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for source in sources:
        try:
            frame = load_workbook(source.workbook, sheet_name, source.model_label)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] Skipping {source.workbook}: {exc}")
            continue
        if not frame.empty:
            frame["source_runs_dir"] = str(source.runs_dir)
            frames.append(frame)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True, sort=False)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "timed_out" in df.columns:
        df["timed_out"] = _safe_bool(df["timed_out"])
    if "fallback" in df.columns:
        df["fallback"] = _safe_bool(df["fallback"])
    for col in ("model_label", "arch_id", "run_group_id", "prompt_id", "conversation_id", "source_runs_dir"):
        if col in df.columns:
            df[col] = _clean_string_id(df[col])
    return df


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(missing)}")


def load_prompt_catalog(prompt_config_path: Path) -> pd.DataFrame:
    prompts = pd.read_json(prompt_config_path)
    prompts = prompts.rename(columns={"id": "prompt_id", "text": "prompt_text"})
    _require_columns(prompts, ("prompt_id", "prompt_text"))
    prompts = prompts.copy()
    prompts["prompt_id"] = _clean_string_id(prompts["prompt_id"])
    if "expected_decision" in prompts.columns:
        prompts["expected_decision"] = _normalize_expected_decision(prompts["expected_decision"])
    else:
        prompts["expected_decision"] = "block"
    prompts["difficulty_bucket"] = prompts["prompt_id"].astype(str).str.split("_", n=1).str[1]
    return prompts.sort_values("prompt_id", key=lambda s: s.map(_prompt_id_num)).reset_index(drop=True)


def load_middleware_decisions(df: pd.DataFrame, runs_dir: Path) -> pd.DataFrame:
    if "conversation_id" not in df.columns:
        return pd.DataFrame(columns=["run_group_id", "conversation_id", "middleware_decision"])

    keys = (
        df[["run_group_id", "conversation_id"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["run_group_id", "conversation_id"])
    )
    rows: list[dict[str, object]] = []
    for _, row in keys.iterrows():
        run_group_id = str(row["run_group_id"])
        conversation_id = str(row["conversation_id"])
        stderr_path = runs_dir / run_group_id / "run_register" / conversation_id / "stderr.txt"
        decision = pd.NA
        if stderr_path.is_file():
            text = stderr_path.read_text(encoding="utf-8", errors="ignore")
            if "blocked out-of-scope request" in text:
                decision = "block"
            elif "allowed request" in text:
                decision = "allow"
        rows.append(
            {
                "run_group_id": run_group_id,
                "conversation_id": conversation_id,
                "middleware_decision": decision,
            }
        )
    return pd.DataFrame(rows)


def load_middleware_decisions_from_sources(df: pd.DataFrame) -> pd.DataFrame:
    required = {"run_group_id", "conversation_id", "source_runs_dir"}
    if not required.issubset(df.columns):
        return pd.DataFrame(columns=["model_label", "run_group_id", "conversation_id", "middleware_decision"])

    key_cols = ["source_runs_dir", "run_group_id", "conversation_id"]
    if "model_label" in df.columns:
        key_cols.insert(0, "model_label")
    keys = df[key_cols].dropna().drop_duplicates().sort_values(key_cols)

    rows: list[dict[str, object]] = []
    for _, row in keys.iterrows():
        run_group_id = str(row["run_group_id"])
        conversation_id = str(row["conversation_id"])
        stderr_path = Path(str(row["source_runs_dir"])) / run_group_id / "run_register" / conversation_id / "stderr.txt"
        decision = pd.NA
        if stderr_path.is_file():
            text = stderr_path.read_text(encoding="utf-8", errors="ignore")
            if "blocked out-of-scope request" in text:
                decision = "block"
            elif "allowed request" in text:
                decision = "allow"
        item = {
            "run_group_id": run_group_id,
            "conversation_id": conversation_id,
            "middleware_decision": decision,
        }
        if "model_label" in row.index:
            item["model_label"] = row["model_label"]
        rows.append(item)
    return pd.DataFrame(rows)


def enrich_rows(
    df: pd.DataFrame,
    prompt_catalog: pd.DataFrame,
    middleware_decisions: pd.DataFrame,
) -> pd.DataFrame:
    out = df.copy()
    prompt_cols = [
        col
        for col in ("prompt_id", "prompt_text", "project", "type", "expected_decision", "difficulty_bucket")
        if col in prompt_catalog.columns
    ]
    out = out.merge(prompt_catalog[prompt_cols], on="prompt_id", how="left", suffixes=("", "_catalog"))
    for col in ("prompt_text", "project", "type", "expected_decision", "difficulty_bucket"):
        catalog_col = f"{col}_catalog"
        if catalog_col not in out.columns:
            continue
        if col in out.columns:
            out[col] = out[col].where(out[col].notna(), out[catalog_col])
        else:
            out[col] = out[catalog_col]
        out = out.drop(columns=[catalog_col])
    if "prompt" in out.columns and "prompt_text" in out.columns:
        missing_prompt = out["prompt"].isna() | (out["prompt"].astype(str).str.strip() == "")
        out.loc[missing_prompt, "prompt"] = out.loc[missing_prompt, "prompt_text"]
    if not middleware_decisions.empty:
        merge_cols = ["run_group_id", "conversation_id"]
        if "model_label" in out.columns and "model_label" in middleware_decisions.columns:
            merge_cols.insert(0, "model_label")
        out = out.merge(middleware_decisions, on=merge_cols, how="left")
    else:
        out["middleware_decision"] = pd.NA

    if "fallback" not in out.columns:
        raise SystemExit("Missing required columns: fallback")
    fallback_bool = _safe_bool(out["fallback"]).fillna(False).astype(bool)
    out["fallback"] = fallback_bool
    out["final_decision"] = fallback_bool.map({True: "block", False: "allow"})
    out["expected_block_int"] = (out["expected_decision"] == "block").astype(int)
    out["expected_allow_int"] = (out["expected_decision"] == "allow").astype(int)
    out["final_block_int"] = (out["final_decision"] == "block").astype(int)
    out["final_allow_int"] = (out["final_decision"] == "allow").astype(int)
    out["correct_behavior_int"] = (out["final_decision"] == out["expected_decision"]).astype(int)
    out["correct_block_int"] = (
        (out["expected_decision"] == "block") & (out["final_decision"] == "block")
    ).astype(int)
    out["correct_allow_int"] = (
        (out["expected_decision"] == "allow") & (out["final_decision"] == "allow")
    ).astype(int)
    out["unsafe_allow_int"] = (
        (out["expected_decision"] == "block") & (out["final_decision"] == "allow")
    ).astype(int)
    out["false_block_int"] = (
        (out["expected_decision"] == "allow") & (out["final_decision"] == "block")
    ).astype(int)
    out["middleware_signal_present"] = out["middleware_decision"].notna().astype(int)
    out["middleware_matches_final_int"] = (
        out["middleware_decision"].notna() & (out["middleware_decision"] == out["final_decision"])
    ).astype(int)
    out["middleware_correct_int"] = (
        out["middleware_decision"].notna() & (out["middleware_decision"] == out["expected_decision"])
    ).astype(int)
    return out


def _rate(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0:
        return float("nan")
    return float(numeric.mean())


def _mean_std(group: pd.DataFrame, metric: str) -> tuple[float, float]:
    values = pd.to_numeric(group[metric], errors="coerce")
    return float(values.mean()), float(values.std(ddof=1))


def build_prompt_arch_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_cols = [col for col in ("model_label", "arch_id", "prompt_id") if col in df.columns]
    for keys, group in df.groupby(group_cols, sort=True, dropna=False):
        key_map = dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,)))
        arch_id = key_map["arch_id"]
        prompt_id = key_map["prompt_id"]
        allow_rate = _rate(group["final_allow_int"])
        block_rate = _rate(group["final_block_int"])
        latency_mean, latency_std = _mean_std(group, "latency_s")
        token_mean, token_std = _mean_std(group, "total_input_tokens")
        call_mean, call_std = _mean_std(group, "llm_call_count")
        code_mean, code_std = _mean_std(group, "answer_code_lines")
        row = {
            **({"model_label": key_map["model_label"]} if "model_label" in key_map else {}),
            "arch_id": arch_id,
            "prompt_id": prompt_id,
            "expected_decision": group["expected_decision"].dropna().iloc[0] if group["expected_decision"].notna().any() else pd.NA,
            "difficulty_bucket": group["difficulty_bucket"].dropna().iloc[0] if group["difficulty_bucket"].notna().any() else pd.NA,
            "project": group["project"].dropna().iloc[0] if "project" in group.columns and group["project"].notna().any() else pd.NA,
            "type": group["type"].dropna().iloc[0] if "type" in group.columns and group["type"].notna().any() else pd.NA,
            "n_runs_observed": int(len(group)),
            "n_run_groups": int(group["run_group_id"].nunique()),
            "final_allow_rate": allow_rate,
            "final_block_rate": block_rate,
            "correct_rate": _rate(group["correct_behavior_int"]),
            "decision_majority_share": max(allow_rate, block_rate),
            "unsafe_allow_rate": _rate(group["unsafe_allow_int"]),
            "false_block_rate": _rate(group["false_block_int"]),
            "latency_s__mean": latency_mean,
            "latency_s__std": latency_std,
            "total_input_tokens__mean": token_mean,
            "total_input_tokens__std": token_std,
            "llm_call_count__mean": call_mean,
            "llm_call_count__std": call_std,
            "answer_code_lines__mean": code_mean,
            "answer_code_lines__std": code_std,
            "middleware_signal_coverage": _rate(group["middleware_signal_present"]),
        }
        present_mask = group["middleware_signal_present"] == 1
        has_middleware_decision = "middleware_decision" in group.columns
        if present_mask.any() and has_middleware_decision:
            present = group.loc[present_mask]
            row["middleware_allow_rate"] = _rate((present["middleware_decision"] == "allow").astype(int))
            row["middleware_block_rate"] = _rate((present["middleware_decision"] == "block").astype(int))
            row["middleware_correct_rate"] = _rate(present["middleware_correct_int"])
            row["middleware_matches_final_rate"] = _rate(present["middleware_matches_final_int"])
        else:
            row["middleware_allow_rate"] = float("nan")
            row["middleware_block_rate"] = float("nan")
            row["middleware_correct_rate"] = float("nan")
            row["middleware_matches_final_rate"] = float("nan")
        rows.append(row)

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    return summary.sort_values(
        [col for col in ("model_label", "arch_id", "prompt_id") if col in summary.columns],
        key=lambda s: s.map(_prompt_id_num) if s.name == "prompt_id" else s,
    ).reset_index(drop=True)


def build_architecture_summary(df: pd.DataFrame, prompt_arch_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_cols = [col for col in ("model_label", "arch_id") if col in df.columns]
    for keys, group in df.groupby(group_cols, sort=True, dropna=False):
        key_map = dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,)))
        arch_id = key_map["arch_id"]
        block_group = group[group["expected_decision"] == "block"]
        allow_group = group[group["expected_decision"] == "allow"]
        latency_mean, latency_std = _mean_std(group, "latency_s")
        token_mean, token_std = _mean_std(group, "total_input_tokens")
        call_mean, call_std = _mean_std(group, "llm_call_count")
        code_mean, code_std = _mean_std(group, "answer_code_lines")
        prompt_consistency = prompt_arch_summary[prompt_arch_summary["arch_id"] == arch_id]
        if "model_label" in key_map and "model_label" in prompt_consistency.columns:
            prompt_consistency = prompt_consistency[prompt_consistency["model_label"] == key_map["model_label"]]
        row = {
            **({"model_label": key_map["model_label"]} if "model_label" in key_map else {}),
            "arch_id": arch_id,
            "n_rows": int(len(group)),
            "n_runs": int(group["run_group_id"].nunique()),
            "n_prompts": int(group["prompt_id"].nunique()),
            "overall_accuracy_rate": _rate(group["correct_behavior_int"]),
            "expected_block_success_rate": _rate(block_group["correct_block_int"]),
            "expected_allow_success_rate": _rate(allow_group["correct_allow_int"]),
            "unsafe_allow_rate": _rate(group["unsafe_allow_int"]),
            "false_block_rate": _rate(group["false_block_int"]),
            "correct_block_rate": _rate(group["correct_block_int"]),
            "correct_allow_rate": _rate(group["correct_allow_int"]),
            "decision_consistency_rate": _rate(prompt_consistency["decision_majority_share"]),
            "macro_prompt_accuracy_rate": _rate(prompt_consistency["correct_rate"]),
            "middleware_signal_coverage": _rate(group["middleware_signal_present"]),
            "middleware_correct_rate": _rate(group.loc[group["middleware_signal_present"] == 1, "middleware_correct_int"]),
            "latency_s__mean": latency_mean,
            "latency_s__std": latency_std,
            "total_input_tokens__mean": token_mean,
            "total_input_tokens__std": token_std,
            "llm_call_count__mean": call_mean,
            "llm_call_count__std": call_std,
            "answer_code_lines__mean": code_mean,
            "answer_code_lines__std": code_std,
        }
        rows.append(row)
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def build_middleware_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_cols = [col for col in ("model_label", "arch_id") if col in df.columns]
    for keys, group in df.groupby(group_cols, sort=True, dropna=False):
        key_map = dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,)))
        arch_id = key_map["arch_id"]
        present = group[group["middleware_signal_present"] == 1]
        rows.append(
            {
                **({"model_label": key_map["model_label"]} if "model_label" in key_map else {}),
                "arch_id": arch_id,
                "n_rows": int(len(group)),
                "middleware_signal_rows": int(len(present)),
                "middleware_signal_coverage": _rate(group["middleware_signal_present"]),
                "middleware_allow_rate": _rate((present["middleware_decision"] == "allow").astype(int)),
                "middleware_block_rate": _rate((present["middleware_decision"] == "block").astype(int)),
                "middleware_correct_rate": _rate(present["middleware_correct_int"]),
                "middleware_matches_final_rate": _rate(present["middleware_matches_final_int"]),
            }
        )
    return pd.DataFrame(rows).sort_values(group_cols).reset_index(drop=True)


def build_run_inventory(all_rows_df: pd.DataFrame, filtered_df: pd.DataFrame) -> pd.DataFrame:
    group_cols = [col for col in ("model_label", "run_group_id", "arch_id") if col in all_rows_df.columns]
    all_counts = (
        all_rows_df.groupby(group_cols, dropna=False)
        .size()
        .rename("rows_in_workbook")
        .reset_index()
    )
    kept_counts = (
        filtered_df.groupby(group_cols, dropna=False)
        .size()
        .rename("rows_used_for_metrics")
        .reset_index()
    )
    inv = all_counts.merge(kept_counts, on=group_cols, how="outer")
    inv["rows_in_workbook"] = inv["rows_in_workbook"].fillna(0).astype(int)
    inv["rows_used_for_metrics"] = inv["rows_used_for_metrics"].fillna(0).astype(int)
    inv["rows_excluded"] = inv["rows_in_workbook"] - inv["rows_used_for_metrics"]
    return inv.sort_values(group_cols).reset_index(drop=True)


def build_pairwise_wilcoxon_summary(df: pd.DataFrame, metric_cols: Sequence[str]) -> pd.DataFrame:
    model_group_cols = [col for col in ("model_label",) if col in df.columns]
    pair_cols = [col for col in PAIRWISE_ID_COLUMNS if col in df.columns and col not in model_group_cols]
    required_pair_cols = {"run_group_id", "prompt_id"}
    if not required_pair_cols.issubset(pair_cols):
        return pd.DataFrame()

    grouped_frames: Iterable[tuple[dict[str, object], pd.DataFrame]]
    if model_group_cols:
        grouped_frames = (
            (
                dict(zip(model_group_cols, keys if isinstance(keys, tuple) else (keys,))),
                group,
            )
            for keys, group in df.groupby(model_group_cols, sort=True, dropna=False)
        )
    else:
        grouped_frames = [({}, df)]

    arch_tables: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, object]] = []
    for group_key, group_df in grouped_frames:
        arch_tables = {}
        for arch, group in group_df.groupby("arch_id", sort=True):
            numeric_group = group[pair_cols + list(metric_cols)].copy()
            for metric in metric_cols:
                numeric_group[metric] = pd.to_numeric(numeric_group[metric], errors="coerce")
            arch_tables[str(arch)] = (
                numeric_group.groupby(pair_cols, dropna=False, as_index=False)[list(metric_cols)]
                .mean()
                .reset_index(drop=True)
            )

        for arch_a, arch_b in combinations(sorted(arch_tables), 2):
            merged = arch_tables[arch_a].merge(
                arch_tables[arch_b],
                on=pair_cols,
                how="inner",
                suffixes=("_a", "_b"),
            )
            for metric in metric_cols:
                values = merged[[f"{metric}_a", f"{metric}_b"]].dropna().reset_index(drop=True)
                if values.empty:
                    rows.append(
                        {
                            **group_key,
                            "arch_a": arch_a,
                            "arch_b": arch_b,
                            "metric": metric,
                            "n_pairs": 0,
                            "n_nonzero_pairs": 0,
                            "arch_a_mean": float("nan"),
                            "arch_a_median": float("nan"),
                            "arch_b_mean": float("nan"),
                            "arch_b_median": float("nan"),
                            "mean_difference_a_minus_b": float("nan"),
                            "median_difference_a_minus_b": float("nan"),
                            "arch_a_lt_arch_b_count": 0,
                            "arch_a_gt_arch_b_count": 0,
                            "tie_count": 0,
                            "wilcoxon_statistic": float("nan"),
                            "p_value": float("nan"),
                            "a12_arch_a_over_arch_b": float("nan"),
                            "a12_arch_b_over_arch_a": float("nan"),
                            "a12_magnitude": "n/a",
                            "notes": "no matched non-null pairs",
                        }
                    )
                    continue

                diffs = values[f"{metric}_a"] - values[f"{metric}_b"]
                a12 = compute_a12(values[f"{metric}_a"], values[f"{metric}_b"])
                note = ""
                if diffs.eq(0).all():
                    statistic = 0.0
                    p_value = 1.0
                    note = "all paired differences are zero"
                else:
                    result = wilcoxon(
                        values[f"{metric}_a"],
                        values[f"{metric}_b"],
                        alternative="two-sided",
                        zero_method="wilcox",
                        method="auto",
                    )
                    statistic = float(result.statistic)
                    p_value = float(result.pvalue)

                rows.append(
                    {
                        **group_key,
                        "arch_a": arch_a,
                        "arch_b": arch_b,
                        "metric": metric,
                        "n_pairs": int(len(values)),
                        "n_nonzero_pairs": int((diffs != 0).sum()),
                        "arch_a_mean": float(values[f"{metric}_a"].mean()),
                        "arch_a_median": float(values[f"{metric}_a"].median()),
                        "arch_b_mean": float(values[f"{metric}_b"].mean()),
                        "arch_b_median": float(values[f"{metric}_b"].median()),
                        "mean_difference_a_minus_b": float(diffs.mean()),
                        "median_difference_a_minus_b": float(diffs.median()),
                        "arch_a_lt_arch_b_count": int((diffs < 0).sum()),
                        "arch_a_gt_arch_b_count": int((diffs > 0).sum()),
                        "tie_count": int((diffs == 0).sum()),
                        "wilcoxon_statistic": statistic,
                        "p_value": p_value,
                        "a12_arch_a_over_arch_b": float(a12),
                        "a12_arch_b_over_arch_a": float(1.0 - a12) if not pd.isna(a12) else float("nan"),
                        "a12_magnitude": classify_a12_magnitude(a12),
                        "notes": note,
                    }
                )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["significant_p_lt_0_05"] = pd.to_numeric(out["p_value"], errors="coerce") < 0.05
    return out.sort_values(
        [col for col in ("model_label", "metric", "arch_a", "arch_b") if col in out.columns]
    ).reset_index(drop=True)


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else default_rq4_out_dir(args.model_label)
    prompt_config = Path(args.prompt_config)
    results_name = args.results_name
    sheet_name = args.sheet
    plot_format = args.plot_format
    dpi = args.dpi
    export_csvs = not args.no_export_csvs
    detailed_sheets = not args.no_detailed_sheets

    multi_model_mode = not args.runs_dir and not args.model_label
    run_sources: list[RunSource] | None = None
    if multi_model_mode:
        discovered_run_dirs = discover_model_run_dirs(Path(args.runs_root) if args.runs_root else None)
        if discovered_run_dirs:
            run_sources = discover_workbook_sources(discovered_run_dirs, results_name)
            if not run_sources:
                model_dirs = ", ".join(str(path) for _, path in discovered_run_dirs)
                raise SystemExit(f"No workbooks found in discovered model run dirs: {model_dirs}")
        else:
            runs_dir = default_rq4_runs_dir()
            if not runs_dir.exists():
                raise SystemExit(f"runs-dir not found: {runs_dir}")
    else:
        runs_dir = Path(args.runs_dir) if args.runs_dir else default_rq4_runs_dir(args.model_label)
        if not runs_dir.exists():
            raise SystemExit(f"runs-dir not found: {runs_dir}")
    if not prompt_config.exists():
        raise SystemExit(f"prompt-config not found: {prompt_config}")

    if run_sources is not None:
        print(
            f"[INFO] Found {len(run_sources)} workbook(s) across "
            f"{len({source.model_label for source in run_sources})} model(s)."
        )
        all_rows = load_all_result_sources(run_sources, sheet_name)
    else:
        workbooks = discover_workbooks(runs_dir, results_name)
        if not workbooks:
            raise SystemExit(f"No workbooks found at {runs_dir} with name {results_name}")
        print(f"[INFO] Found {len(workbooks)} workbook(s).")
        all_rows = load_all_results(workbooks, sheet_name)
        if args.model_label:
            all_rows["model_label"] = sanitize_path_component(args.model_label)
    if all_rows.empty:
        raise SystemExit("No rows loaded from workbooks.")

    _require_columns(all_rows, ("arch_id", "run_group_id", "prompt_id", "fallback"))
    filtered_rows = all_rows.copy()

    prompt_catalog = load_prompt_catalog(prompt_config)
    if run_sources is not None:
        middleware_decisions = load_middleware_decisions_from_sources(filtered_rows)
    else:
        middleware_decisions = load_middleware_decisions(filtered_rows, runs_dir)
        if args.model_label and not middleware_decisions.empty:
            middleware_decisions["model_label"] = sanitize_path_component(args.model_label)
    enriched_rows = enrich_rows(filtered_rows, prompt_catalog, middleware_decisions)
    if enriched_rows["expected_decision"].isna().any():
        missing_prompt_ids = sorted(enriched_rows.loc[enriched_rows["expected_decision"].isna(), "prompt_id"].dropna().unique())
        raise SystemExit(
            "Expected decision missing after prompt merge for prompt IDs: "
            + ", ".join(missing_prompt_ids)
        )

    prompt_arch_summary = build_prompt_arch_summary(enriched_rows)
    architecture_summary = build_architecture_summary(enriched_rows, prompt_arch_summary)
    middleware_summary = build_middleware_summary(enriched_rows)
    run_inventory = build_run_inventory(all_rows, filtered_rows)
    pairwise_wilcoxon_summary = build_pairwise_wilcoxon_summary(
        enriched_rows,
        [metric for metric in METRICS if metric in enriched_rows.columns],
    )

    save_outputs(
        out_dir=out_dir,
        enriched_rows=enriched_rows,
        architecture_summary=architecture_summary,
        prompt_arch_summary=prompt_arch_summary,
        middleware_summary=middleware_summary,
        run_inventory=run_inventory,
        pairwise_wilcoxon_summary=pairwise_wilcoxon_summary,
        prompt_catalog=prompt_catalog,
        export_csvs=export_csvs,
        detailed_sheets=detailed_sheets,
    )

    generate_plots(
        out_dir=out_dir,
        architecture_summary=architecture_summary,
        prompt_arch_summary=prompt_arch_summary,
        enriched_rows=enriched_rows,
        architectures=None,
        plot_format=plot_format,
        dpi=dpi,
    )

    sort_columns = ["overall_accuracy_rate", "expected_block_success_rate"]
    ascending = [False, False]
    include_allow_success = False
    if "expected_allow_success_rate" in architecture_summary.columns:
        allow_col = pd.to_numeric(
            architecture_summary["expected_allow_success_rate"], errors="coerce"
        )
        if allow_col.notna().any():
            sort_columns.append("expected_allow_success_rate")
            ascending.append(False)
            include_allow_success = True
    rankable = architecture_summary.sort_values(
        sort_columns,
        ascending=ascending,
    ).reset_index(drop=True)
    print(f"[INFO] Output written to: {out_dir}")
    if not rankable.empty:
        best = rankable.iloc[0]
        message = (
            "[INFO] Top architecture by overall guardrail accuracy: "
            f"{best['arch_id']}"
        )
        if "model_label" in best.index and not pd.isna(best["model_label"]):
            message += f" on {best['model_label']}"
        message += (
            f" (accuracy={best['overall_accuracy_rate']:.3f}, "
            f"block_success={best['expected_block_success_rate']:.3f}"
        )
        if include_allow_success and not pd.isna(best["expected_allow_success_rate"]):
            message += f", allow_success={best['expected_allow_success_rate']:.3f}"
        message += ")"
        print(message)
    print("[INFO] Files:")
    for path in sorted(out_dir.iterdir()):
        print(f"  - {path.name}")


if __name__ == "__main__":
    main()
