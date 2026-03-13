import time
import pathlib
import argparse
import logging
import json
import pandas as pd
from datetime import datetime, timezone

from app.run_interaction import run_one
from app.setup_configuration import (
    RUNS_DIR,
    RESULTS_PATH,
    ensure_dirs,
    load_architectures,
    load_prompts_json,
    build_env,
)
from app.local_tracing import (
    export_langsmith_traces_to_xlsx,
    update_results_metrics_from_tracing,
)

from typing import Dict, Any

from app.setup_logger import setup_logging

RESULT_COLUMNS = [
    "run_id", "run_group_id", "arch_id", "prompt_id", "prompt", "timeout_s",
    "timed_out", "returncode", "latency_s", "answer", "fallback", "is_yaml_valid", "stdout_chars",
    "stderr_chars", "answer_chars", "answer_word_count", "answer_code_lines", "llm_call_count",
    "total_input_tokens",
    "conversation_id", "run_dir"
]
MANDATORY_TRACING_COLUMNS = ["end_time", "latency_s"]


def append_jsonl(path: pathlib.Path, obj: Dict[str, Any]):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _collect_langsmith_export_envs(archs: list[Any], run_group_id: str) -> list[dict[str, str]]:
    export_envs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for arch in archs:
        env = build_env(arch, run_group_id)
        project_name = env.get("LANGSMITH_PROJECT") or env.get("LANGCHAIN_PROJECT") or ""
        api_url = env.get("LANGSMITH_ENDPOINT") or env.get("LANGCHAIN_ENDPOINT") or "https://api.smith.langchain.com"
        api_key = env.get("LANGSMITH_API_KEY") or env.get("LANGCHAIN_API_KEY") or ""
        signature = (project_name, api_url, api_key)
        if signature in seen:
            continue
        seen.add(signature)
        export_envs.append(env)
    return export_envs


def _export_tracing_with_completeness_retry(
    *,
    tracing_xlsx_path: pathlib.Path,
    tracing_envs: list[dict[str, str]],
    automation_start_time: datetime,
    expected_conversations: int,
    expected_run_ids: set[str],
    mandatory_columns: list[str],
) -> None:
    retries = 8
    retry_delay_s = 2.0

    for attempt in range(1, retries + 1):
        for export_env in tracing_envs:
            try:
                export_langsmith_traces_to_xlsx(
                    tracing_path=tracing_xlsx_path,
                    start_time=automation_start_time,
                    env=export_env,
                )
            except Exception:
                project_name = export_env.get("LANGSMITH_PROJECT") or export_env.get("LANGCHAIN_PROJECT")
                logging.exception(
                    "Failed to export LangSmith traces for project=%s run_group_id=%s",
                    project_name,
                    tracing_xlsx_path.parent.name,
                )

        observed_conversations = 0
        incomplete_rows = 0
        missing_mandatory_columns: list[str] = []
        if tracing_xlsx_path.exists():
            try:
                trace_df = pd.read_excel(tracing_xlsx_path)
                if "conversation_id" in trace_df.columns:
                    conversation_series = trace_df["conversation_id"].astype(str)
                    relevant_rows = trace_df[conversation_series.isin(expected_run_ids)].copy()
                    observed_conversations = int(relevant_rows["conversation_id"].nunique(dropna=True))
                else:
                    relevant_rows = trace_df.iloc[0:0].copy()

                missing_mandatory_columns = [
                    column for column in mandatory_columns if column not in trace_df.columns
                ]

                if not missing_mandatory_columns and not relevant_rows.empty:
                    empty_any_mask = pd.Series(False, index=relevant_rows.index)
                    for column in mandatory_columns:
                        column_values = relevant_rows[column]
                        empty_mask = column_values.isna()
                        if column_values.dtype == "object":
                            empty_mask = empty_mask | column_values.astype(str).str.strip().eq("")
                        empty_any_mask = empty_any_mask | empty_mask
                    incomplete_rows = int(empty_any_mask.sum())
            except Exception:
                logging.exception("Failed reading tracing file '%s' for completeness check.", tracing_xlsx_path)

        completeness_ok = observed_conversations == expected_conversations
        mandatory_ok = (not missing_mandatory_columns) and (incomplete_rows == 0)

        if completeness_ok and mandatory_ok:
            logging.info(
                "Tracing completeness check passed: expected=%s observed=%s incomplete_rows=%s",
                expected_conversations,
                observed_conversations,
                incomplete_rows,
            )
            return

        if attempt < retries:
            logging.warning(
                (
                    "Tracing completeness mismatch (attempt %s/%s): expected=%s observed=%s "
                    "incomplete_rows=%s missing_mandatory_columns=%s. Retrying in %.1fs."
                ),
                attempt,
                retries,
                expected_conversations,
                observed_conversations,
                incomplete_rows,
                missing_mandatory_columns,
                retry_delay_s,
            )
            time.sleep(retry_delay_s)

    logging.warning(
        (
            "Tracing completeness not reached after %s attempts: expected=%s observed=%s "
            "incomplete_rows=%s missing_mandatory_columns=%s."
        ),
        retries,
        expected_conversations,
        observed_conversations,
        incomplete_rows,
        missing_mandatory_columns,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument(
        "-r",
        "--runs",
        type=int,
        default=1,
        help= "Indicates the amount of runs to make."
    )
    args = parser.parse_args()
    setup_logging(args.verbose)

    ensure_dirs()
    logging.info("Loading architectures and prompts")

    archs = load_architectures(str(pathlib.Path(__file__).parent.parent / "configs" / "architectures.json"))
    prompts = load_prompts_json(str(pathlib.Path(__file__).parent.parent / "configs" / "ro3_prompts.json"))

    timeout_s = 300

    # Limpia results.jsonl si quieres empezar de cero
    # RESULTS_PATH.unlink(missing_ok=True)

    for i in range(args.runs):
        now = time.time()
        run_group_id = time.strftime("%Y%m%d_%H%M%S", time.localtime(now)) + f"_{int((now % 1) * 1000):03d}"
        automation_start_time = datetime.now(timezone.utc)
        group_results = []
        tracing_envs = _collect_langsmith_export_envs(archs, run_group_id)
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
            group_xlsx_path = group_dir / "results.xlsx"
            df = pd.DataFrame(group_results, columns=RESULT_COLUMNS)
            df.to_excel(group_xlsx_path, index=False)

            tracing_xlsx_path = RUNS_DIR / run_group_id / f"tracing_{run_group_id}.xlsx"
            _export_tracing_with_completeness_retry(
                tracing_xlsx_path=tracing_xlsx_path,
                tracing_envs=tracing_envs,
                automation_start_time=automation_start_time,
                expected_conversations=len(group_results),
                expected_run_ids={str(item["run_id"]) for item in group_results if item.get("run_id") is not None},
                mandatory_columns=MANDATORY_TRACING_COLUMNS,
            )
            update_results_metrics_from_tracing(
                tracing_path=tracing_xlsx_path,
                results_path=group_xlsx_path,
            )

if __name__ == "__main__":
    main()
