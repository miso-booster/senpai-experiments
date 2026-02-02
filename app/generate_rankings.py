import argparse
import csv
import json
import pathlib
import random
import time
from typing import Dict, List, Tuple

from app.setup_configuration import RUNS_DIR, load_prompts_json


def _load_results(results_path: pathlib.Path) -> List[Dict[str, str]]:
    with results_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        return list(reader)


def _load_prompts(prompts_path: pathlib.Path) -> Tuple[List[str], Dict[str, str]]:
    data = load_prompts_json(str(prompts_path))
    prompt_order: List[str] = []
    prompt_text_by_id: Dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            pid = item.get("id")
            if not pid:
                continue
            prompt_order.append(pid)
            prompt_text_by_id[pid] = item.get("text", "")
    elif isinstance(data, dict):
        for item in data.get("prompts", []):
            pid = item.get("id")
            if not pid:
                continue
            prompt_order.append(pid)
            prompt_text_by_id[pid] = item.get("text", "")
    return prompt_order, prompt_text_by_id


def _blockquote(text: str) -> str:
    if text is None:
        return ">"
    lines = str(text).splitlines()
    if not lines:
        return ">"
    out = []
    for line in lines:
        if line.strip():
            out.append(f"> {line}")
        else:
            out.append(">")
    return "\n".join(out)


def _resolve_results_path(args: argparse.Namespace) -> pathlib.Path:
    if args.results:
        return pathlib.Path(args.results)
    if args.run_group_id:
        return RUNS_DIR / args.run_group_id / "results.csv"
    raise SystemExit("Provide --results or --run-group-id")


def _resolve_out_dir(
    results_path: pathlib.Path, out_dir_arg: str | None
) -> pathlib.Path:
    if out_dir_arg:
        return pathlib.Path(out_dir_arg)
    return results_path.parent / "ranking"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate randomized ranking markdown + key + answers template."
    )
    parser.add_argument("--results", help="Path to results.csv")
    parser.add_argument(
        "--run-group-id", help="Run group id to locate out/runs/<id>/results.csv"
    )
    parser.add_argument(
        "--prompts",
        default=str(pathlib.Path(__file__).parent.parent / "configs" / "prompts.json"),
        help="Path to prompts.json",
    )
    parser.add_argument(
        "--out-dir", help="Output directory (default: results parent / ranking)"
    )
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    args = parser.parse_args()

    results_path = _resolve_results_path(args)
    if not results_path.exists():
        raise SystemExit(f"results.csv not found: {results_path}")

    prompts_path = pathlib.Path(args.prompts)
    if not prompts_path.exists():
        raise SystemExit(f"prompts.json not found: {prompts_path}")

    out_dir = _resolve_out_dir(results_path, args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    seed = args.seed if args.seed is not None else int(time.time() * 1000)
    rng = random.Random(seed)

    results = _load_results(results_path)
    prompt_order, prompt_text_by_id = _load_prompts(prompts_path)

    rows_by_prompt: Dict[str, List[Dict[str, str]]] = {}
    for row in results:
        pid = row.get("prompt_id")
        if not pid:
            continue
        rows_by_prompt.setdefault(pid, []).append(row)

    # Include prompts that appear in results but not in prompts.json
    for pid in rows_by_prompt.keys():
        if pid not in prompt_order:
            prompt_order.append(pid)

    md_path = out_dir / "ranking.md"
    key_path = out_dir / "key.csv"
    answers_path = out_dir / "answers.csv"

    key_rows: List[Dict[str, str]] = []

    md_lines: List[str] = []
    md_lines.append("# Ranking sheet")
    run_group_id = ""
    if results:
        run_group_id = results[0].get("run_group_id", "")
    if run_group_id:
        md_lines.append(f"Run group: {run_group_id}")
    md_lines.append(f"Seed: {seed}")
    md_lines.append("")
    md_lines.append("Instructions:")
    md_lines.append(
        "- For each prompt, you will see responses labeled A/B/C (order is random)."
    )
    md_lines.append("- Rank them from best to worst in the CSV.")
    md_lines.append(
        "- In the CSV, put the best label in rank1, the second-best in rank2, and the worst in rank3."
    )
    md_lines.append("- Use each label only once per prompt (no repeats).")
    md_lines.append(f"- Fill and return {answers_path.name} (delimiter is ';').")
    md_lines.append("")
    md_lines.append("Example row:")
    md_lines.append("prompt_id;rank1;rank2;rank3")
    md_lines.append("p1;B;C;A")
    md_lines.append("")
    md_lines.append(
        "Important: only send back the filled answers CSV (you may rename it like answers_manolito.csv)."
    )
    md_lines.append("")

    max_responses = 0
    for pid in prompt_order:
        rows = rows_by_prompt.get(pid, [])
        if not rows:
            continue
        prompt_text = prompt_text_by_id.get(pid, "(prompt text not found in configs)")
        rows_copy = list(rows)
        rng.shuffle(rows_copy)
        labels = [chr(ord("A") + i) for i in range(len(rows_copy))]
        max_responses = max(max_responses, len(labels))

        md_lines.append(f"## Prompt {pid}")
        md_lines.append("")
        md_lines.append(prompt_text)
        md_lines.append("")

        for label, row in zip(labels, rows_copy):
            md_lines.append(f"### Response {label}")
            md_lines.append("")
            md_lines.append(_blockquote(row.get("answer", "")))
            md_lines.append("")

            key_rows.append(
                {
                    "prompt_id": pid,
                    "label": label,
                    "arch_id": row.get("arch_id", ""),
                    "run_id": row.get("run_id", ""),
                    "run_group_id": row.get("run_group_id", ""),
                    "run_dir": row.get("run_dir", ""),
                }
            )

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    with key_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "prompt_id",
                "label",
                "arch_id",
                "run_id",
                "run_group_id",
                "run_dir",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(key_rows)

    # Answers template
    if max_responses == 0:
        max_responses = 3
    rank_columns = [f"rank{i}" for i in range(1, max_responses + 1)]
    with answers_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["prompt_id"] + rank_columns, delimiter=";"
        )
        writer.writeheader()
        for pid in prompt_order:
            if pid in rows_by_prompt:
                writer.writerow({"prompt_id": pid})

    print(f"Wrote markdown: {md_path}")
    print(f"Wrote key: {key_path}")
    print(f"Wrote answers template: {answers_path}")


if __name__ == "__main__":
    main()
