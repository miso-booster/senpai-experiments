import argparse
import re
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

try:
    from app.setup_configuration import OUT_DIR, RUNS_DIR
except Exception:  # Supports `python app/rq3_clustering/answer_clustering.py` without package imports
    _ROOT = Path(__file__).resolve().parents[2]
    OUT_DIR = _ROOT / "out"
    RUNS_DIR = OUT_DIR / "runs"

try:
    from .excel import save_outputs
except ImportError:  # Supports `python app/rq3_clustering/answer_clustering.py`
    from excel import save_outputs


DEFAULT_RUNS_DIR = RUNS_DIR / "advanced_prompt_arch_comparison"
DEFAULT_OUT_DIR = OUT_DIR / "RQ3_clustering"
REQUIRED_COLUMNS = ("arch_id", "prompt_id", "run_group_id", "answer")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build one answer matrix per architecture from repeated "
            "results.xlsx files for downstream clustering."
        )
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Directory containing run folders (default: {DEFAULT_RUNS_DIR})",
    )
    parser.add_argument(
        "--results-name",
        default="results.xlsx",
        help="Workbook filename inside each run folder (default: results.xlsx)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory for architecture-specific clustering workbooks (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--sheet",
        help="Optional sheet name to read from each workbook (default: first sheet)",
    )
    parser.add_argument(
        "--arch-ids",
        nargs="*",
        help="Optional arch_id values to include (default: all detected)",
    )
    parser.add_argument(
        "--prompt-ids",
        nargs="*",
        help="Optional prompt_id values to include (default: all detected)",
    )
    parser.add_argument(
        "--export-csvs",
        action="store_true",
        help="Also export CSV files for each architecture matrix and inventory",
    )
    return parser.parse_args()


def _clean_string_id(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned == "", pd.NA)


def _prompt_sort_key(value: object) -> tuple[int, str]:
    text = "" if value is None else str(value).strip().lower()
    match = re.fullmatch(r"p(\d+)(?:_(.+))?", text)
    if not match:
        return (10**9, text)
    return (int(match.group(1)), text)


def discover_workbooks(runs_dir: Path, results_name: str) -> list[Path]:
    if not runs_dir.exists():
        raise SystemExit(f"runs-dir not found: {runs_dir}")
    if not runs_dir.is_dir():
        raise SystemExit(f"runs-dir is not a directory: {runs_dir}")
    workbooks = sorted(path for path in runs_dir.glob(f"*/{results_name}") if path.is_file())
    if not workbooks:
        raise SystemExit(f"No workbooks found at {runs_dir} with name {results_name}")
    return workbooks


def load_workbook(path: Path, sheet_name: str | None) -> pd.DataFrame:
    chosen_sheet = sheet_name
    if chosen_sheet is None:
        xl = pd.ExcelFile(path)
        if not xl.sheet_names:
            raise ValueError("Workbook has no sheets")
        chosen_sheet = xl.sheet_names[0]

    df = pd.read_excel(path, sheet_name=chosen_sheet)
    if df.empty:
        return df

    df = df.copy()
    df["source_results_xlsx"] = str(path)
    df["source_run_folder"] = path.parent.name
    if "run_group_id" not in df.columns:
        df["run_group_id"] = path.parent.name
    else:
        missing = df["run_group_id"].isna() | (df["run_group_id"].astype(str).str.strip() == "")
        df.loc[missing, "run_group_id"] = path.parent.name
    return df


def load_all_results(workbooks: Sequence[Path], sheet_name: str | None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for workbook in workbooks:
        try:
            frame = load_workbook(workbook, sheet_name)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] Skipping {workbook}: {exc}")
            continue
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True, sort=False)
    for column in ("arch_id", "prompt_id", "run_group_id"):
        if column in df.columns:
            df[column] = _clean_string_id(df[column])
    if "answer" in df.columns:
        df["answer"] = df["answer"].astype("string")
    return df


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(missing)}")


def filter_rows(
    df: pd.DataFrame,
    arch_ids: Sequence[str] | None,
    prompt_ids: Sequence[str] | None,
) -> pd.DataFrame:
    filtered = df.copy()
    if arch_ids:
        wanted_arches = {value.strip() for value in arch_ids if value and value.strip()}
        filtered = filtered[filtered["arch_id"].isin(wanted_arches)]
    if prompt_ids:
        wanted_prompts = {value.strip() for value in prompt_ids if value and value.strip()}
        filtered = filtered[filtered["prompt_id"].isin(wanted_prompts)]
    filtered = filtered[filtered["answer"].notna()].copy()
    filtered["answer"] = filtered["answer"].astype("string")
    return filtered


def build_inventory(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "arch_id",
        "prompt_id",
        "run_group_id",
        "answer",
        "source_run_folder",
        "source_results_xlsx",
    ]
    existing = [column for column in columns if column in df.columns]
    inventory = df[existing].copy()
    inventory["answer_length"] = inventory["answer"].astype("string").str.len()
    inventory["_prompt_order"] = inventory["prompt_id"].map(_prompt_sort_key)
    inventory = inventory.sort_values(
        ["arch_id", "_prompt_order", "prompt_id", "run_group_id"],
        kind="stable",
    ).reset_index(drop=True)
    return inventory.drop(columns=["_prompt_order"])


def build_duplicates_report(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["arch_id", "prompt_id", "run_group_id"]
    grouped = (
        df.groupby(group_cols, dropna=False)
        .agg(
            answer_count=("answer", "size"),
            distinct_answer_count=("answer", lambda s: s.astype("string").nunique(dropna=True)),
            sample_answer=("answer", "first"),
        )
        .reset_index()
    )
    duplicates = grouped[grouped["answer_count"] > 1].copy()
    if duplicates.empty:
        return duplicates
    duplicates["_prompt_order"] = duplicates["prompt_id"].map(_prompt_sort_key)
    duplicates = duplicates.sort_values(
        ["arch_id", "_prompt_order", "prompt_id", "run_group_id"],
        kind="stable",
    ).reset_index(drop=True)
    return duplicates.drop(columns=["_prompt_order"])


def _collapse_answer(series: pd.Series) -> str | None:
    non_null = [value for value in series.astype("string").tolist() if pd.notna(value)]
    return non_null[0] if non_null else None


def build_architecture_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    prompt_order = sorted(df["prompt_id"].dropna().astype(str).unique().tolist(), key=_prompt_sort_key)
    run_group_order = sorted(df["run_group_id"].dropna().astype(str).unique().tolist())

    for arch_id, group in df.groupby("arch_id", sort=True):
        collapsed = (
            group.groupby(["prompt_id", "run_group_id"], dropna=False)["answer"]
            .agg(_collapse_answer)
            .reset_index()
        )
        table = collapsed.pivot(index="prompt_id", columns="run_group_id", values="answer")
        table = table.reindex(index=prompt_order, columns=run_group_order)
        table.index.name = "prompt_id"
        tables[str(arch_id)] = table

    return tables


def main() -> None:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)

    workbooks = discover_workbooks(runs_dir, args.results_name)
    print(f"[INFO] Found {len(workbooks)} workbook(s).")

    all_rows = load_all_results(workbooks, args.sheet)
    if all_rows.empty:
        raise SystemExit("No rows loaded from workbooks.")

    _require_columns(all_rows, REQUIRED_COLUMNS)
    filtered_rows = filter_rows(all_rows, args.arch_ids, args.prompt_ids)
    if filtered_rows.empty:
        raise SystemExit("No rows left after filtering arch_id / prompt_id / non-null answer.")

    inventory = build_inventory(filtered_rows)
    duplicates = build_duplicates_report(filtered_rows)
    architecture_tables = build_architecture_tables(filtered_rows)
    written_paths = save_outputs(
        out_dir=out_dir,
        architecture_tables=architecture_tables,
        inventory=inventory,
        duplicates=duplicates,
        export_csvs=args.export_csvs,
    )

    print(f"[INFO] Architectures exported: {len(architecture_tables)}")
    if not duplicates.empty:
        print(f"[WARN] Duplicate answer groups detected: {len(duplicates)}. Using the first non-null answer per group.")
    print("[INFO] Files:")
    for path in written_paths:
        print(f"  - {path.name}")


if __name__ == "__main__":
    main()
