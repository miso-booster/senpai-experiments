import argparse
import csv
import pathlib
from typing import Dict, List, Tuple


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


def _rank_columns(fieldnames: List[str]) -> List[str]:
    cols = []
    for name in fieldnames:
        if name.lower().startswith("rank"):
            cols.append(name)
    # sort by numeric suffix if possible
    def _rank_key(name: str) -> int:
        suffix = "".join(ch for ch in name if ch.isdigit())
        return int(suffix) if suffix else 0

    return sorted(cols, key=_rank_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate subject answers into a long-form CSV.")
    parser.add_argument("--answers-dir", required=True, help="Directory containing answers_*.csv files")
    parser.add_argument("--key", help="Key CSV to use for all answers files (default: <answers-dir>/key.csv)")
    parser.add_argument("--out", help="Output CSV path (default: <answers-dir>/combined_rankings.csv)")
    args = parser.parse_args()

    answers_dir = pathlib.Path(args.answers_dir)
    if not answers_dir.exists():
        raise SystemExit(f"answers-dir not found: {answers_dir}")

    answers_files = sorted(answers_dir.glob("answers_*.csv"))
    if not answers_files:
        raise SystemExit(f"No answers_*.csv files found in: {answers_dir}")

    out_path = pathlib.Path(args.out) if args.out else answers_dir / "combined_rankings.csv"
    key_path = pathlib.Path(args.key) if args.key else (answers_dir / "key.csv")
    if not key_path.exists():
        raise SystemExit(f"Missing key: {key_path}")

    all_rows: List[Dict[str, str]] = []

    for answers_path in answers_files:
        subject_id = answers_path.stem.replace("answers_", "", 1)
        key_map = _load_key(key_path)

        with answers_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            if not reader.fieldnames:
                continue
            rank_cols = _rank_columns(reader.fieldnames)

            for row in reader:
                pid = (row.get("prompt_id") or "").strip()
                if not pid:
                    continue
                for idx, col in enumerate(rank_cols, start=1):
                    label = (row.get(col) or "").strip().upper()
                    if not label:
                        continue
                    key_row = key_map.get((pid, label))
                    if not key_row:
                        raise SystemExit(
                            f"Unknown label '{label}' for prompt '{pid}' in {answers_path.name}"
                        )
                    all_rows.append(
                        {
                            "subject_id": subject_id,
                            "prompt_id": pid,
                            "rank_position": str(idx),
                            "label": label,
                            "arch_id": key_row.get("arch_id", ""),
                            "run_id": key_row.get("run_id", ""),
                            "run_group_id": key_row.get("run_group_id", ""),
                            "run_dir": key_row.get("run_dir", ""),
                        }
                    )

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "subject_id",
                "prompt_id",
                "rank_position",
                "label",
                "arch_id",
                "run_id",
                "run_group_id",
                "run_dir",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote combined rankings: {out_path}")


if __name__ == "__main__":
    main()
