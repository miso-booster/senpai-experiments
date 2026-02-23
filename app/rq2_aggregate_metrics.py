import argparse
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

try:
    from app.rq2_excel import save_outputs
    from app.rq2_plots import generate_plots
except ModuleNotFoundError:  # Supports `python app/rq2_aggregate_metrics.py`
    from rq2_excel import save_outputs
    from rq2_plots import generate_plots


METRICS: dict[str, str] = {
    "latency_s": "Response time (s)",
    "total_input_tokens": "Input tokens",
    "llm_call_count": "LLM calls",
}

NUMERIC_COLUMNS = (
    "latency_s",
    "total_input_tokens",
    "llm_call_count",
    "is_yaml_valid",
    "returncode",
    "timeout_s",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate multiple execution results.xlsx files and compare "
            "architectures for RQ2 (average per response + variability)."
        )
    )
    parser.add_argument(
        "--runs-dir",
        default="out/runs",
        help="Directory containing run folders (default: out/runs)",
    )
    parser.add_argument(
        "--results-name",
        default="results.xlsx",
        help="Workbook filename inside each run folder (default: results.xlsx)",
    )
    parser.add_argument(
        "--out-dir",
        default="out/RQ2_architecture_metrics",
        help="Output directory for the RQ2 workbook and plots",
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
        "--include-failed",
        action="store_true",
        help="Include timed out / non-zero returncode rows in metric summaries",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Skip plot generation",
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
        "--export-csvs",
        action="store_true",
        help="Also export CSV files in addition to the single Excel workbook",
    )
    parser.add_argument(
        "--detailed-sheets",
        action="store_true",
        help="Include extra detailed sheets in the Excel workbook",
    )
    return parser.parse_args()


def _safe_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
        "yes": True,
        "no": False,
    }
    return series.astype(str).str.strip().str.lower().map(mapping)


def discover_workbooks(runs_dir: Path, results_name: str) -> list[Path]:
    return sorted(p for p in runs_dir.glob(f"*/{results_name}") if p.is_file())


def load_workbook(path: Path, sheet_name: str | None) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    chosen_sheet = sheet_name or xl.sheet_names[0]
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

    if "arch_id" in df.columns:
        df["arch_id"] = df["arch_id"].astype(str).str.strip()
    if "run_group_id" in df.columns:
        df["run_group_id"] = df["run_group_id"].astype(str).str.strip()

    return df


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(missing)}")


def filter_rows(df: pd.DataFrame, architectures: Sequence[str] | None, include_failed: bool) -> pd.DataFrame:
    out = df.copy()
    if architectures:
        wanted = {a.strip() for a in architectures if a.strip()}
        out = out[out["arch_id"].isin(wanted)]

    if not include_failed:
        mask = pd.Series(True, index=out.index)
        if "timed_out" in out.columns:
            mask &= out["timed_out"].fillna(False) != True
        if "returncode" in out.columns:
            mask &= out["returncode"].fillna(0) == 0
        out = out[mask]

    return out


def _series_cv(series: pd.Series) -> float:
    mean = series.mean(skipna=True)
    std = series.std(skipna=True, ddof=1)
    if pd.isna(mean) or mean == 0 or pd.isna(std):
        return float("nan")
    return float(std / mean)


def build_row_level_summary(df: pd.DataFrame, metric_cols: Sequence[str]) -> pd.DataFrame:
    summaries: list[dict[str, float | int | str]] = []
    for arch, group in df.groupby("arch_id", sort=True):
        row: dict[str, float | int | str] = {
            "arch_id": arch,
            "n_rows": int(len(group)),
            "n_executions": int(group["run_group_id"].nunique()),
        }
        if "timed_out" in group.columns:
            row["timed_out_count"] = int(group["timed_out"].fillna(False).astype(bool).sum())
        if "returncode" in group.columns:
            row["nonzero_returncode_count"] = int((group["returncode"].fillna(0) != 0).sum())

        for metric in metric_cols:
            values = pd.to_numeric(group[metric], errors="coerce")
            row[f"{metric}__mean"] = values.mean()
            row[f"{metric}__std"] = values.std(ddof=1)
            row[f"{metric}__cv"] = _series_cv(values)
            row[f"{metric}__p25"] = values.quantile(0.25)
            row[f"{metric}__median"] = values.median()
            row[f"{metric}__p75"] = values.quantile(0.75)
            row[f"{metric}__min"] = values.min()
            row[f"{metric}__max"] = values.max()
        summaries.append(row)

    return pd.DataFrame(summaries).sort_values("arch_id").reset_index(drop=True)


def build_fallback_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "fallback" not in df.columns:
        return pd.DataFrame()

    rows: list[dict[str, float | int | str]] = []
    for arch, group in df.groupby("arch_id", sort=True):
        series = group["fallback"]
        observed = series.notna().sum()
        true_count = int((series == True).sum())  # noqa: E712
        false_count = int((series == False).sum())  # noqa: E712
        rows.append(
            {
                "arch_id": arch,
                "n_responses": int(len(group)),
                "n_runs": int(group["run_group_id"].nunique()),
                "fallback_observed_n": int(observed),
                "fallback_count": true_count,
                "non_fallback_count": false_count,
                "fallback_rate": (true_count / observed) if observed else float("nan"),
            }
        )
    return pd.DataFrame(rows).sort_values("arch_id").reset_index(drop=True)


def build_yaml_validity_summary(df: pd.DataFrame) -> pd.DataFrame:
    if "is_yaml_valid" not in df.columns:
        return pd.DataFrame()

    rows: list[dict[str, float | int | str]] = []
    for arch, group in df.groupby("arch_id", sort=True):
        series = pd.to_numeric(group["is_yaml_valid"], errors="coerce")
        applicable = int(series.notna().sum())
        valid_count = int((series == 1).sum())
        invalid_count = int((series == 0).sum())
        missing_count = int(len(group) - applicable)
        rows.append(
            {
                "arch_id": arch,
                "n_responses": int(len(group)),
                "n_runs": int(group["run_group_id"].nunique()),
                "yaml_applicable_n": applicable,
                "yaml_valid_count": valid_count,
                "yaml_invalid_count": invalid_count,
                "yaml_missing_n": missing_count,
                "yaml_valid_rate_on_applicable": (
                    valid_count / applicable if applicable else float("nan")
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("arch_id").reset_index(drop=True)


def build_per_execution_arch_summary(df: pd.DataFrame, metric_cols: Sequence[str]) -> pd.DataFrame:
    agg: dict[str, tuple[str, str]] = {}
    for metric in metric_cols:
        agg[f"{metric}__mean"] = (metric, "mean")
        agg[f"{metric}__std"] = (metric, "std")
        agg[f"{metric}__median"] = (metric, "median")
        agg[f"{metric}__min"] = (metric, "min")
        agg[f"{metric}__max"] = (metric, "max")
    agg["n_rows"] = ("arch_id", "size")

    out = (
        df.groupby(["run_group_id", "arch_id"], dropna=False)
        .agg(**agg)
        .reset_index()
        .sort_values(["run_group_id", "arch_id"])
        .reset_index(drop=True)
    )
    return out


def build_execution_level_summary(per_exec_arch_df: pd.DataFrame, metric_cols: Sequence[str]) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for arch, group in per_exec_arch_df.groupby("arch_id", sort=True):
        row: dict[str, float | int | str] = {
            "arch_id": arch,
            "n_executions": int(group["run_group_id"].nunique()),
            "avg_rows_per_execution": float(pd.to_numeric(group["n_rows"], errors="coerce").mean()),
        }
        for metric in metric_cols:
            col = f"{metric}__mean"
            vals = pd.to_numeric(group[col], errors="coerce")
            row[f"{metric}__execution_mean"] = vals.mean()
            row[f"{metric}__execution_std"] = vals.std(ddof=1)
            row[f"{metric}__execution_cv"] = _series_cv(vals)
            row[f"{metric}__execution_min"] = vals.min()
            row[f"{metric}__execution_max"] = vals.max()
        rows.append(row)

    return pd.DataFrame(rows).sort_values("arch_id").reset_index(drop=True)


def build_run_inventory(all_rows_df: pd.DataFrame, filtered_df: pd.DataFrame) -> pd.DataFrame:
    all_counts = (
        all_rows_df.groupby(["run_group_id", "arch_id"], dropna=False)
        .size()
        .rename("rows_in_workbook")
        .reset_index()
    )
    kept_counts = (
        filtered_df.groupby(["run_group_id", "arch_id"], dropna=False)
        .size()
        .rename("rows_used_for_metrics")
        .reset_index()
    )
    inv = all_counts.merge(kept_counts, on=["run_group_id", "arch_id"], how="outer")
    inv["rows_in_workbook"] = inv["rows_in_workbook"].fillna(0).astype(int)
    inv["rows_used_for_metrics"] = inv["rows_used_for_metrics"].fillna(0).astype(int)
    inv["rows_excluded"] = inv["rows_in_workbook"] - inv["rows_used_for_metrics"]
    return inv.sort_values(["run_group_id", "arch_id"]).reset_index(drop=True)


def main() -> None:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)

    if not runs_dir.exists():
        raise SystemExit(f"runs-dir not found: {runs_dir}")

    workbooks = discover_workbooks(runs_dir, args.results_name)
    if not workbooks:
        raise SystemExit(f"No workbooks found at {runs_dir} with name {args.results_name}")

    print(f"[INFO] Found {len(workbooks)} workbook(s).")
    all_rows = load_all_results(workbooks, args.sheet)
    if all_rows.empty:
        raise SystemExit("No rows loaded from workbooks.")

    _require_columns(all_rows, ("arch_id", "run_group_id"))
    available_metric_cols = [m for m in METRICS if m in all_rows.columns]
    _require_columns(all_rows, available_metric_cols)
    if len(available_metric_cols) != len(METRICS):
        missing = [m for m in METRICS if m not in all_rows.columns]
        print(f"[WARN] Missing metric columns; skipping: {', '.join(missing)}")

    filtered_rows = filter_rows(all_rows, args.architectures, args.include_failed)
    if filtered_rows.empty:
        raise SystemExit("No rows left after filtering (architectures / failures).")

    row_summary = build_row_level_summary(filtered_rows, available_metric_cols)
    per_exec_arch = build_per_execution_arch_summary(filtered_rows, available_metric_cols)
    exec_summary = build_execution_level_summary(per_exec_arch, available_metric_cols)
    run_inventory = build_run_inventory(all_rows, filtered_rows)
    fallback_summary = build_fallback_summary(filtered_rows)
    yaml_validity_summary = build_yaml_validity_summary(filtered_rows)

    save_outputs(
        out_dir=out_dir,
        all_rows=all_rows,
        filtered_rows=filtered_rows,
        row_summary=row_summary,
        per_exec_arch=per_exec_arch,
        exec_summary=exec_summary,
        run_inventory=run_inventory,
        fallback_summary=fallback_summary,
        yaml_validity_summary=yaml_validity_summary,
        export_csvs=args.export_csvs,
        detailed_sheets=args.detailed_sheets,
    )

    if not args.no_plots:
        generate_plots(
            out_dir=out_dir,
            filtered_rows=filtered_rows,
            metrics={m: METRICS[m] for m in available_metric_cols},
            architectures=args.architectures,
            plot_format=args.plot_format,
            dpi=args.dpi,
        )

    print(f"[INFO] Output written to: {out_dir}")
    print(
        "[INFO] Primary metric in plots: per-response averages/variability "
        "(one row = one prompt x one architecture response)."
    )
    print("[INFO] Files:")
    for path in sorted(out_dir.iterdir()):
        print(f"  - {path.name}")


if __name__ == "__main__":
    main()
