import time
import pathlib
import argparse
import pandas as pd

from app.run_interaction import run_one
from app.setup_configuration import *

from typing import Dict, Any

from app.setup_logger import setup_logging

columns = [
    "run_id", "run_group_id", "arch_id", "prompt_id", "prompt", "timeout_s",
    "timed_out", "returncode", "latency_s", "answer", "fallback", "stdout_chars",
    "stderr_chars", "answer_chars", "run_dir"
]
results_df = pd.DataFrame(columns=columns)


def append_jsonl(path: pathlib.Path, obj: Dict[str, Any]):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    setup_logging(args.verbose)

    ensure_dirs()
    logging.info("Loading architectures and prompts")

    archs = load_architectures(str(pathlib.Path(__file__).parent.parent / "configs" / "architectures.json"))
    prompts = load_prompts_json(str(pathlib.Path(__file__).parent.parent / "configs" / "prompts.json"))

    timeout_s = 300
    now = time.time()
    run_group_id = time.strftime("%Y%m%d_%H%M%S", time.localtime(now)) + f"_{int((now % 1) * 1000):03d}"
    group_results = []

    # Limpia results.jsonl si quieres empezar de cero
    # RESULTS_PATH.unlink(missing_ok=True)

    for arch in archs:
        logging.info("Architecture start id=%s", arch.id)
        for p in prompts:
            try:
                res = run_one(
                    arch=arch,
                    prompt_id=p["id"],
                    prompt_text=p["text"],
                    sensei_project=p["project"],
                    prompt_type=p["type"],
                    timeout_s=timeout_s,
                    run_group_id=run_group_id,
                    verbose=args.verbose
                )
                append_jsonl(RESULTS_PATH, res)
                group_results.append(res)
                logging.info(
                    "[OK] %s %s latency=%.3fs timed_out=%s",
                    res["arch_id"],
                    res["prompt_id"],
                    res["latency_s"],
                    res["timed_out"],
                )

            except FileNotFoundError as e:
                logging.warning("Skipping prompt_id=%s project=%s: %s", p.get("id"), p.get("project"), e)
            print("\n"
                  "------------------------------------------------------------------------------------------------\n"
                  "------------------------------------------------------------------------------------------------"
                  "\n")
        logging.info("Architecture end id=%s", arch.id)

    if group_results:
        group_dir = RUNS_DIR / run_group_id
        group_dir.mkdir(parents=True, exist_ok=True)
        group_csv_path = group_dir / "results.csv"
        df = pd.DataFrame(group_results)
        # Use UTF-8 BOM for better compatibility with Excel on Windows.
        df.to_csv(group_csv_path, index=False, encoding="utf-8-sig", sep=";")

if __name__ == "__main__":
    main()

