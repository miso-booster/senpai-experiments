import argparse
import re
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

try:
    from app.setup_configuration import (
        OUT_DIR,
        RQ2_EXPERIMENT_DIRNAME,
        resolve_model_output_dir,
        resolve_runs_dir,
    )
    from .aggregate_metrics import discover_workbooks, load_all_results
except ImportError:  # Supports `python app/rq2/fallback_answer_join.py`
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from app.setup_configuration import (
        OUT_DIR,
        RQ2_EXPERIMENT_DIRNAME,
        resolve_model_output_dir,
        resolve_runs_dir,
    )
    from aggregate_metrics import discover_workbooks, load_all_results


INDEX_COLUMNS = ("run_group_id", "prompt_id", "prompt")
REQUIRED_COLUMNS = (*INDEX_COLUMNS, "arch_id", "answer", "fallback")


def default_rq2_runs_dir(model_label: str | None = None) -> Path:
    return resolve_runs_dir(RQ2_EXPERIMENT_DIRNAME, model_label)


def default_rq2_out_dir(model_label: str | None = None) -> Path:
    return resolve_model_output_dir(OUT_DIR / "RQ2_architecture_metrics", model_label)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the fallback-answer join workflow."""
    parser = argparse.ArgumentParser(
        description=(
            "Read all architecture_comparison results.xlsx files, pivot answers and "
            "fallback flags by architecture, and keep only prompt rows where at least "
            "one architecture fell back."
        )
    )
    parser.add_argument(
        "--model-label",
        help=(
            "Optional model label used to resolve model-specific run folders and "
            "default RQ2 output directories."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        help=(
            "Directory containing run folders "
            "(default: out/runs/architecture_comparison or "
            "out/runs/<model-label>/architecture_comparison)"
        ),
    )
    parser.add_argument(
        "--results-name",
        default="results.xlsx",
        help="Workbook filename inside each run folder (default: results.xlsx)",
    )
    parser.add_argument(
        "--out-dir",
        help=(
            "Output directory for the joined fallback-answer files "
            "(default: out/RQ2_architecture_metrics or "
            "out/RQ2_architecture_metrics/<model-label>)"
        ),
    )
    parser.add_argument(
        "--sheet",
        help="Excel sheet name to read (default: first sheet)",
    )
    parser.add_argument(
        "--architectures",
        nargs="*",
        help="Optional arch_id list to include (default: all detected)",
    )
    parser.add_argument(
        "--include-no-fallbacks",
        action="store_true",
        help="Keep all joined rows instead of filtering to any-fallback rows only",
    )
    return parser.parse_args()


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(missing)}")


def _collapse_answer(series: pd.Series) -> str | None:
    non_null = [value for value in series.astype("string").tolist() if pd.notna(value)]
    return non_null[0] if non_null else None


def _collapse_fallback(series: pd.Series) -> bool | None:
    observed = series.dropna()
    if observed.empty:
        return None
    return bool(observed.astype(bool).any())


def _prompt_sort_key(prompt_id: object) -> tuple[int, str]:
    text = "" if pd.isna(prompt_id) else str(prompt_id)
    match = re.match(r"^[Pp](\d+)", text)
    if match:
        return (int(match.group(1)), text)
    return (10**9, text)


def filter_architectures(df: pd.DataFrame, architectures: Sequence[str] | None) -> pd.DataFrame:
    """Keep only the requested architectures when provided."""
    if not architectures:
        return df.copy()
    wanted = {architecture.strip() for architecture in architectures if architecture.strip()}
    return df[df["arch_id"].isin(wanted)].copy()


def build_fallback_answer_join(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot answers and fallback flags into one row per run-group prompt."""
    _require_columns(df, REQUIRED_COLUMNS)

    collapsed = (
        df.groupby(list(INDEX_COLUMNS) + ["arch_id"], dropna=False)
        .agg(
            answer=("answer", _collapse_answer),
            fallback=("fallback", _collapse_fallback),
        )
        .reset_index()
    )

    answer_wide = collapsed.pivot(index=list(INDEX_COLUMNS), columns="arch_id", values="answer")
    answer_wide = answer_wide.rename(columns=lambda arch_id: f"answer_{arch_id}")

    fallback_wide = collapsed.pivot(index=list(INDEX_COLUMNS), columns="arch_id", values="fallback")
    fallback_wide = fallback_wide.rename(columns=lambda arch_id: f"fallback_{arch_id}")

    joined = answer_wide.join(fallback_wide, how="outer").reset_index()

    answer_columns = sorted(
        [column for column in joined.columns if column.startswith("answer_")],
        key=lambda column: column.removeprefix("answer_"),
    )
    fallback_columns = sorted(
        [column for column in joined.columns if column.startswith("fallback_")],
        key=lambda column: column.removeprefix("fallback_"),
    )

    for column in fallback_columns:
        observed = joined[column].notna()
        joined.loc[observed, column] = joined.loc[observed, column].astype(bool)

    joined["_prompt_order"] = joined["prompt_id"].map(_prompt_sort_key)
    joined = joined.sort_values(
        ["run_group_id", "_prompt_order", "prompt_id", "prompt"],
        kind="stable",
    ).reset_index(drop=True)

    return joined.drop(columns=["_prompt_order"])[list(INDEX_COLUMNS) + answer_columns + fallback_columns]


def filter_to_any_fallback(joined_df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows where at least one fallback column is true."""
    fallback_columns = [column for column in joined_df.columns if column.startswith("fallback_")]
    if not fallback_columns:
        return joined_df.iloc[0:0].copy()

    fallback_flags = (
        joined_df[fallback_columns]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .astype(int)
        .astype(bool)
    )
    return joined_df[fallback_flags.any(axis=1)].reset_index(drop=True)


def save_outputs(out_dir: Path, joined_df: pd.DataFrame) -> tuple[Path, Path]:
    """Write CSV and Excel copies of the joined fallback-answer table."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "rq2_fallback_answers_joined.csv"
    xlsx_path = out_dir / "rq2_fallback_answers_joined.xlsx"

    joined_df.to_csv(csv_path, index=False)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        joined_df.to_excel(writer, index=False, sheet_name="fallback_answers")

    return csv_path, xlsx_path


def main() -> None:
    """Run the fallback-answer join workflow and write output files."""
    args = parse_args()
    runs_dir = Path(args.runs_dir) if args.runs_dir else default_rq2_runs_dir(args.model_label)
    out_dir = Path(args.out_dir) if args.out_dir else default_rq2_out_dir(args.model_label)

    if not runs_dir.exists():
        raise SystemExit(f"runs-dir not found: {runs_dir}")

    workbooks = discover_workbooks(runs_dir, args.results_name)
    if not workbooks:
        raise SystemExit(f"No workbooks found at {runs_dir} with name {args.results_name}")

    print(f"[INFO] Found {len(workbooks)} workbook(s).")
    all_rows = load_all_results(workbooks, args.sheet)
    if all_rows.empty:
        raise SystemExit("No rows loaded from workbooks.")

    filtered_rows = filter_architectures(all_rows, args.architectures)
    if filtered_rows.empty:
        raise SystemExit("No rows left after filtering architectures.")

    joined = build_fallback_answer_join(filtered_rows)
    if not args.include_no_fallbacks:
        joined = filter_to_any_fallback(joined)

    if joined.empty:
        raise SystemExit("No joined rows matched the fallback filter.")

    csv_path, xlsx_path = save_outputs(out_dir, joined)
    print(f"[INFO] Wrote {len(joined)} row(s) to {csv_path}")
    print(f"[INFO] Wrote {len(joined)} row(s) to {xlsx_path}")


if __name__ == "__main__":
    main()
