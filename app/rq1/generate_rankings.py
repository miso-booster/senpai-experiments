import argparse
import csv
import pathlib
import random
import time
from typing import Dict, List, Tuple

import pandas as pd

from app.setup_configuration import OUT_DIR, RUNS_DIR, load_prompts_json
from app.yaml_validation import validate_answer_yaml_status

DEFAULT_RQ1_RUNS_DIR = RUNS_DIR / "architecture_comparison"
DEFAULT_RQ1_OUT_ROOT = OUT_DIR / "RQ1"


def _sanitize_run_dir(raw_run_dir: str) -> str:
    normalized = (raw_run_dir or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    marker = "/out/"
    marker_index = normalized.lower().find(marker)
    if marker_index >= 0:
        return normalized[marker_index + 1 :]
    if normalized.startswith("out/"):
        return normalized
    return ""


def _load_results(results_path: pathlib.Path) -> List[Dict[str, str]]:
    df = pd.read_excel(results_path)
    df = df.fillna("")
    return df.astype(str).to_dict(orient="records")


def _load_prompts(
    prompts_path: pathlib.Path,
) -> Tuple[List[str], Dict[str, str], Dict[str, str]]:
    data = load_prompts_json(str(prompts_path))
    prompt_order: List[str] = []
    prompt_text_by_id: Dict[str, str] = {}
    prompt_type_by_id: Dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            pid = item.get("id")
            if not pid:
                continue
            prompt_order.append(pid)
            prompt_text_by_id[pid] = item.get("text", "")
            prompt_type_by_id[pid] = item.get("type", "")
    elif isinstance(data, dict):
        for item in data.get("prompts", []):
            pid = item.get("id")
            if not pid:
                continue
            prompt_order.append(pid)
            prompt_text_by_id[pid] = item.get("text", "")
            prompt_type_by_id[pid] = item.get("type", "")
    return prompt_order, prompt_text_by_id, prompt_type_by_id


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


def _yaml_status_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"true", "1", "yes"}:
        return "true"
    if normalized in {"false", "0", "no"}:
        return "false"
    return "n/a"


def _yaml_status_label_for_row(row: Dict[str, str], prompt_type: str | None) -> str:
    stored = _yaml_status_label(row.get("is_yaml_valid"))
    if stored != "n/a":
        return stored

    status = validate_answer_yaml_status(prompt_type or "", row.get("answer", ""))
    if status == "valid":
        return "true"
    if status == "invalid":
        return "false"
    return "n/a"


def _resolve_run_dir(runs_dir: pathlib.Path, run_id: str | None) -> pathlib.Path:
    if not runs_dir.exists():
        raise SystemExit(f"runs-dir not found: {runs_dir}")
    if not runs_dir.is_dir():
        raise SystemExit(f"runs-dir is not a directory: {runs_dir}")

    if run_id:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise SystemExit(f"run_id not found in {runs_dir}: {run_id}")
        if not run_dir.is_dir():
            raise SystemExit(f"run_id path is not a directory: {run_dir}")
        return run_dir

    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    if not run_dirs:
        raise SystemExit(f"No run directories found in: {runs_dir}")
    selected = run_dirs[0]
    print(f"Using first run in {runs_dir}: {selected.name}")
    return selected


def _resolve_results_path(args: argparse.Namespace) -> pathlib.Path:
    if args.results:
        return pathlib.Path(args.results)
    run_dir = _resolve_run_dir(pathlib.Path(args.runs_dir), args.run_id)
    return run_dir / "results.xlsx"


def _resolve_out_dir(
    results_path: pathlib.Path, out_dir_arg: str | None
) -> pathlib.Path:
    if out_dir_arg:
        return pathlib.Path(out_dir_arg)
    return DEFAULT_RQ1_OUT_ROOT / results_path.parent.name


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate randomized ranking markdown + key + answers template."
    )
    parser.add_argument("--results", help="Path to results.xlsx")
    parser.add_argument(
        "--run-id",
        "--run-group-id",
        dest="run_id",
        help=(
            "Run folder id inside the runs directory "
            "(alias: --run-group-id). If omitted, the first run folder is used."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RQ1_RUNS_DIR),
        help=(
            "Directory containing run folders "
            f"(default: {DEFAULT_RQ1_RUNS_DIR})"
        ),
    )
    parser.add_argument(
        "--prompts",
        default=str(pathlib.Path(__file__).resolve().parents[2] / "configs" / "prompts.json"),
        help="Path to prompts.json",
    )
    parser.add_argument(
        "--out-dir", help="Output directory (default: out/RQ1/<run_id>)"
    )
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    args = parser.parse_args()

    results_path = _resolve_results_path(args)
    if not results_path.exists():
        raise SystemExit(f"results.xlsx not found: {results_path}")

    prompts_path = pathlib.Path(args.prompts)
    if not prompts_path.exists():
        raise SystemExit(f"prompts.json not found: {prompts_path}")

    out_dir = _resolve_out_dir(results_path, args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    seed = args.seed if args.seed is not None else int(time.time() * 1000)
    rng = random.Random(seed)

    results = _load_results(results_path)
    prompt_order, prompt_text_by_id, prompt_type_by_id = _load_prompts(prompts_path)

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
    md_lines.append("- Fill confidence with `H`, `M`, or `L` for each prompt ranking.")
    md_lines.append(f"- Fill and return {answers_path.name} (delimiter is ';').")
    md_lines.append("")
    md_lines.append("Example row:")
    md_lines.append("prompt_id;rank1;rank2;rank3;confidence")
    md_lines.append("p1;B;C;A;H")
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
        prompt_type = prompt_type_by_id.get(pid, "")
        rows_copy = list(rows)
        rng.shuffle(rows_copy)
        num_responses = len(rows_copy)
        if num_responses > 26:
            raise ValueError(
                f"Prompt {pid} has {num_responses} responses, but at most 26 (A-Z) "
                "are supported for labeling."
            )
        labels = [chr(ord("A") + i) for i in range(num_responses)]
        max_responses = max(max_responses, len(labels))

        md_lines.append(f"## Prompt {pid}")
        md_lines.append("")
        md_lines.append(prompt_text)
        md_lines.append("")

        for label, row in zip(labels, rows_copy):
            md_lines.append(f"### Response {label}")
            md_lines.append("")
            yaml_status = _yaml_status_label_for_row(row, prompt_type)
            md_lines.append(f"YAML: `{yaml_status}`")
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
                    "run_dir": _sanitize_run_dir(row.get("run_dir", "")),
                    "is_yaml_valid": row.get("is_yaml_valid", ""),
                }
            )

    # Write BOM so Windows editors detect UTF-8 instead of local ANSI/GBK.
    md_path.write_text("\n".join(md_lines), encoding="utf-8-sig")

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
                "is_yaml_valid",
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
            f, fieldnames=["prompt_id"] + rank_columns + ["confidence"], delimiter=";"
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
