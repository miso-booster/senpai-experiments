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
    arch_ids = set()

    overall_rank_sum: Dict[str, int] = {}
    overall_rank_count: Dict[str, int] = {}
    overall_borda_sum: Dict[str, int] = {}
    overall_first_count: Dict[str, int] = {}

    prompt_rank_sum: Dict[Tuple[str, str], int] = {}
    prompt_rank_count: Dict[Tuple[str, str], int] = {}
    prompt_first_count: Dict[Tuple[str, str], int] = {}
    prompt_first_total: Dict[str, int] = {}

    pairwise_wins: Dict[Tuple[str, str], int] = {}

    # Load the key once and reuse it for all answers files.
    key_map = _load_key(key_path)
    for answers_path in answers_files:
        subject_id = answers_path.stem.replace("answers_", "", 1)

        with answers_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            if not reader.fieldnames:
                continue
            rank_cols = _rank_columns(reader.fieldnames)
            total_ranks = len(rank_cols)

            for row in reader:
                pid = (row.get("prompt_id") or "").strip()
                if not pid:
                    continue
                ordered_labels: List[str] = []
                for col in rank_cols:
                    label = (row.get(col) or "").strip().upper()
                    if label:
                        ordered_labels.append(label)

                for idx, label in enumerate(ordered_labels, start=1):
                    key_row = key_map.get((pid, label))
                    if not key_row:
                        raise SystemExit(
                            f"Unknown label '{label}' for prompt '{pid}' in {answers_path.name}"
                        )
                    arch_id = key_row.get("arch_id", "")
                    arch_ids.add(arch_id)

                    all_rows.append(
                        {
                            "subject_id": subject_id,
                            "prompt_id": pid,
                            "rank_position": str(idx),
                            "label": label,
                            "arch_id": arch_id,
                            "run_id": key_row.get("run_id", ""),
                            "run_group_id": key_row.get("run_group_id", ""),
                            "run_dir": key_row.get("run_dir", ""),
                        }
                    )

                    overall_rank_sum[arch_id] = overall_rank_sum.get(arch_id, 0) + idx
                    overall_rank_count[arch_id] = overall_rank_count.get(arch_id, 0) + 1
                    borda_score = max(total_ranks - idx, 0)
                    overall_borda_sum[arch_id] = overall_borda_sum.get(arch_id, 0) + borda_score

                    prompt_key = (pid, arch_id)
                    prompt_rank_sum[prompt_key] = prompt_rank_sum.get(prompt_key, 0) + idx
                    prompt_rank_count[prompt_key] = prompt_rank_count.get(prompt_key, 0) + 1

                    if idx == 1:
                        overall_first_count[arch_id] = overall_first_count.get(arch_id, 0) + 1
                        prompt_first_count[prompt_key] = prompt_first_count.get(prompt_key, 0) + 1
                        prompt_first_total[pid] = prompt_first_total.get(pid, 0) + 1

                # Pairwise wins (earlier rank beats later rank)
                for i in range(len(ordered_labels)):
                    for j in range(i + 1, len(ordered_labels)):
                        label_i = ordered_labels[i]
                        label_j = ordered_labels[j]
                        key_row_i = key_map.get((pid, label_i))
                        key_row_j = key_map.get((pid, label_j))
                        if not key_row_i or not key_row_j:
                            continue
                        arch_i = key_row_i.get("arch_id", "")
                        arch_j = key_row_j.get("arch_id", "")
                        pairwise_wins[(arch_i, arch_j)] = pairwise_wins.get((arch_i, arch_j), 0) + 1

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

    # Metrics: overall per architecture
    metrics_overall_path = answers_dir / "metrics_overall.csv"
    total_firsts = sum(overall_first_count.values())
    with metrics_overall_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "arch_id",
                "n",
                "avg_rank",
                "borda_sum",
                "borda_avg",
                "win_count",
                "win_rate",
            ],
            delimiter=";",
        )
        writer.writeheader()
        for arch_id in sorted(arch_ids):
            n = overall_rank_count.get(arch_id, 0)
            avg_rank = (overall_rank_sum.get(arch_id, 0) / n) if n else 0.0
            borda_sum = overall_borda_sum.get(arch_id, 0)
            borda_avg = (borda_sum / n) if n else 0.0
            win_count = overall_first_count.get(arch_id, 0)
            win_rate = (win_count / total_firsts) if total_firsts else 0.0
            writer.writerow(
                {
                    "arch_id": arch_id,
                    "n": n,
                    "avg_rank": f"{avg_rank:.6f}",
                    "borda_sum": borda_sum,
                    "borda_avg": f"{borda_avg:.6f}",
                    "win_count": win_count,
                    "win_rate": f"{win_rate:.6f}",
                }
            )

    # Metrics: per prompt per architecture
    metrics_prompt_path = answers_dir / "metrics_per_prompt.csv"
    with metrics_prompt_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "prompt_id",
                "arch_id",
                "n",
                "avg_rank",
                "win_count",
                "win_rate",
            ],
            delimiter=";",
        )
        writer.writeheader()
        for (pid, arch_id), n in sorted(prompt_rank_count.items()):
            avg_rank = prompt_rank_sum.get((pid, arch_id), 0) / n if n else 0.0
            win_count = prompt_first_count.get((pid, arch_id), 0)
            total_prompt_firsts = prompt_first_total.get(pid, 0)
            win_rate = (win_count / total_prompt_firsts) if total_prompt_firsts else 0.0
            writer.writerow(
                {
                    "prompt_id": pid,
                    "arch_id": arch_id,
                    "n": n,
                    "avg_rank": f"{avg_rank:.6f}",
                    "win_count": win_count,
                    "win_rate": f"{win_rate:.6f}",
                }
            )

    # Metrics: pairwise win rates
    metrics_pairwise_path = answers_dir / "metrics_pairwise.csv"
    arch_list = sorted(arch_ids)
    with metrics_pairwise_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "arch_a",
                "arch_b",
                "wins_a_over_b",
                "wins_b_over_a",
                "total",
                "win_rate_a_over_b",
            ],
            delimiter=";",
        )
        writer.writeheader()
        for i in range(len(arch_list)):
            for j in range(i + 1, len(arch_list)):
                a = arch_list[i]
                b = arch_list[j]
                wins_a = pairwise_wins.get((a, b), 0)
                wins_b = pairwise_wins.get((b, a), 0)
                total = wins_a + wins_b
                win_rate = (wins_a / total) if total else 0.0
                writer.writerow(
                    {
                        "arch_a": a,
                        "arch_b": b,
                        "wins_a_over_b": wins_a,
                        "wins_b_over_a": wins_b,
                        "total": total,
                        "win_rate_a_over_b": f"{win_rate:.6f}",
                    }
                )

    print(f"Wrote combined rankings: {out_path}")
    print(f"Wrote metrics: {metrics_overall_path}")
    print(f"Wrote metrics: {metrics_prompt_path}")
    print(f"Wrote metrics: {metrics_pairwise_path}")


if __name__ == "__main__":
    main()
