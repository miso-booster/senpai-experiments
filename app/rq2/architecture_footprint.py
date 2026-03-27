#!/usr/bin/env python3
"""Write branch implementation metrics for the Senpai repo to CSV and stdout."""

from __future__ import annotations

import ast
import csv
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_CSV = PROJECT_ROOT / "out" / "RQ2_architecture_metrics" / "architecture_footprint.csv"
BRANCHES = [
    "one-node-based-assistant",
    "graph-based-assistant",
    "main",
]


@dataclass
class BranchMetrics:
    branch: str
    app_py_files: int
    app_py_loc: int
    app_classes: int
    app_functions: int


def resolve_source_repo() -> Path:
    source_repo = PROJECT_ROOT.parent / "Senpai-Assistant"
    if source_repo.exists():
        return source_repo
    raise SystemExit(
        f"Source repo not found: {source_repo}. "
        "Check out Senpai-Assistant next to this project."
    )


SOURCE_REPO = resolve_source_repo()


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=SOURCE_REPO,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8", errors="ignore")


def read_branch_file(branch: str, path: str) -> str:
    return git_text("show", f"{branch}:{path}")


def count_non_empty_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def collect_branch_metrics(branch: str) -> BranchMetrics:
    files = git_text("ls-tree", "-r", "--name-only", branch).splitlines()
    app_files = [path for path in files if path.startswith("app/") and path.endswith(".py")]

    app_py_loc = 0
    app_classes = 0
    app_functions = 0

    for path in app_files:
        text = read_branch_file(branch, path)
        app_py_loc += count_non_empty_lines(text)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        app_classes += sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
        app_functions += sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))

    return BranchMetrics(
        branch=branch,
        app_py_files=len(app_files),
        app_py_loc=app_py_loc,
        app_classes=app_classes,
        app_functions=app_functions,
    )


def main() -> None:
    rows = [asdict(collect_branch_metrics(branch)) for branch in BRANCHES]
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    writer = csv.DictWriter(
        sys.stdout,
        fieldnames=list(rows[0].keys()),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
