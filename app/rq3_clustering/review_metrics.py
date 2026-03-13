import argparse
from pathlib import Path

import pandas as pd

try:
    from app.setup_configuration import OUT_DIR
except Exception:  # Supports direct execution
    OUT_DIR = Path(__file__).resolve().parents[2] / "out"

try:
    from .excel import save_reviewed_outputs
    from .review import build_summaries_from_assignments
except ImportError:  # Supports `python app/rq3_clustering/review_metrics.py`
    from excel import save_reviewed_outputs
    from review import build_summaries_from_assignments


DEFAULT_OUT_DIR = OUT_DIR / "RQ3_clustering"
DEFAULT_REVIEW_WORKBOOK = DEFAULT_OUT_DIR / "RQ3_clustering_review_template.xlsx"


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y", "x"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build final RQ3 clustering metrics from human-reviewed cluster assignments."
    )
    parser.add_argument(
        "--review-workbook",
        default=str(DEFAULT_REVIEW_WORKBOOK),
        help=f"Workbook edited by the human reviewer (default: {DEFAULT_REVIEW_WORKBOOK})",
    )
    parser.add_argument(
        "--sheet",
        default="review_assignments",
        help="Sheet name containing the reviewed assignments (default: review_assignments)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory for the reviewed metrics workbook (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="Allow rows with review_status=pending and compute metrics anyway",
    )
    parser.add_argument(
        "--export-csvs",
        action="store_true",
        help="Also export reviewed metrics as CSV files",
    )
    return parser.parse_args()


def load_review_assignments(path: Path, sheet_name: str) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"review-workbook not found: {path}")
    df = pd.read_excel(path, sheet_name=sheet_name)
    if df.empty:
        raise SystemExit(f"No rows found in {path} sheet {sheet_name}")
    return df


def validate_review_assignments(df: pd.DataFrame, *, allow_pending: bool) -> pd.DataFrame:
    required = {
        "arch_id",
        "prompt_id",
        "prompt",
        "response_index",
        "answer",
        "final_cluster_id",
        "reviewed",
    }
    missing = sorted(column for column in required if column not in df.columns)
    if missing:
        raise SystemExit(f"Missing required review columns: {', '.join(missing)}")

    review = df.copy()
    review["reviewed"] = review["reviewed"].map(_to_bool)
    if not allow_pending:
        pending = review[~review["reviewed"]]
        if not pending.empty:
            raise SystemExit(
                f"Found {len(pending)} rows with reviewed=FALSE. Finish the review first, or rerun with --allow-pending."
            )

    review["final_cluster_id"] = (
        review["final_cluster_id"].astype("string").fillna("").str.strip().str.upper()
    )
    if "review_notes" in review.columns:
        review["review_notes"] = review["review_notes"].astype("string").fillna("").str.strip()
    review["response_index"] = review["response_index"].astype(int)
    return review


def main() -> None:
    args = parse_args()
    review_workbook = Path(args.review_workbook)
    out_dir = Path(args.out_dir)

    reviewed_assignments = load_review_assignments(review_workbook, args.sheet)
    reviewed_assignments = validate_review_assignments(
        reviewed_assignments,
        allow_pending=args.allow_pending,
    )

    reviewed_overall_summary, reviewed_prompt_summary, reviewed_cluster_summary = (
        build_summaries_from_assignments(
            reviewed_assignments,
            final_cluster_id_col="final_cluster_id",
            proposed_cluster_label_col="proposed_cluster_label",
            proposed_cluster_reason_col="proposed_cluster_reason",
            reviewed_flag_col="reviewed",
            review_notes_col="review_notes",
            result_source="human_review",
        )
    )

    written_paths = save_reviewed_outputs(
        out_dir,
        reviewed_assignments,
        reviewed_overall_summary,
        reviewed_prompt_summary,
        reviewed_cluster_summary,
        export_csvs=args.export_csvs,
    )

    print(f"[INFO] Reviewed assignments: {len(reviewed_assignments)}")
    print("[INFO] Files:")
    for path in written_paths:
        print(f"  - {path.name}")


if __name__ == "__main__":
    main()
