"""Local XLSX export helpers for LangSmith traces."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_TRACE_FILENAME_STEM = "langsmith_tracing"
_TRACE_COLUMNS = [
    "automation_run_timestamp",
    "conversation_id",
    "langsmith_run_id",
    "parent_run_id",
    "trace_id",
    "run_type",
    "name",
    "start_time",
    "end_time",
    "latency_s",
    "error",
    "execution_order",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "llm_cost",
    "tags",
    "metadata",
]


def _resolve_automation_run_timestamp(env: dict[str, str] | None = None) -> str:
    """Resolve a stable automation-run timestamp for tracing file naming."""
    env_data = env or os.environ
    return (
        env_data.get("AUTOMATION_RUN_TIMESTAMP")
        or env_data.get("SENPAI_AUTOMATION_TIMESTAMP")
        or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    )


def _resolve_tracing_xlsx_path(
    tracing_path: str | Path, automation_run_timestamp: str
) -> Path:
    """Build the timestamped XLSX path used to store LangSmith traces."""
    base_path = Path(tracing_path).expanduser()
    if base_path.suffix.lower() == ".xlsx":
        directory = base_path.parent
        stem = base_path.stem
    else:
        directory = base_path
        stem = f"{_TRACE_FILENAME_STEM}_{automation_run_timestamp}"
    return directory / f"{stem}.xlsx"


def _serialize_trace_field(value: Any) -> str | int | float | None:
    """Serialize LangSmith run fields for XLSX output."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (str, int, float)):
        return value
    return str(value)


def export_langsmith_traces_to_xlsx(
    tracing_path: str | Path,
    start_time: datetime,
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Export LangSmith traces for one automation execution to a local XLSX."""
    env_data = env or os.environ
    if env_data.get("LANGSMITH_TRACING", "").lower() != "true":
        logger.debug(
            "Skipping tracing export because LANGSMITH_TRACING is not enabled."
        )
        return

    project_name = env_data.get("LANGSMITH_PROJECT") or env_data.get(
        "LANGCHAIN_PROJECT"
    )
    if not project_name:
        logger.warning(
            "Skipping tracing export because no LangSmith project is configured."
        )
        return

    api_key = env_data.get("LANGSMITH_API_KEY") or env_data.get("LANGCHAIN_API_KEY")
    if not api_key:
        logger.warning(
            "Skipping tracing export because no LangSmith API key is configured."
        )
        return

    api_url = (
        env_data.get("LANGSMITH_ENDPOINT")
        or env_data.get("LANGCHAIN_ENDPOINT")
        or "https://api.smith.langchain.com"
    )

    try:
        from langsmith import Client
    except ImportError:
        logger.warning("Skipping tracing export because langsmith is not installed.")
        return

    automation_run_timestamp = _resolve_automation_run_timestamp(env_data)
    xlsx_path = _resolve_tracing_xlsx_path(tracing_path, automation_run_timestamp)
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)

    client = Client(api_url=api_url, api_key=api_key)

    lookback_seconds = int(env_data.get("LANGSMITH_EXPORT_LOOKBACK_SECONDS", "30"))
    retries = int(env_data.get("LANGSMITH_EXPORT_RETRIES", "4"))
    retry_delay_seconds = float(
        env_data.get("LANGSMITH_EXPORT_RETRY_DELAY_SECONDS", "0.8")
    )
    query_start_time = start_time - timedelta(seconds=max(0, lookback_seconds))

    runs: list[Any] = []
    for attempt in range(retries + 1):
        runs = list(
            client.list_runs(
                project_name=project_name,
                start_time=query_start_time,
            )
        )
        if runs:
            break
        if attempt < retries:
            time.sleep(max(0.0, retry_delay_seconds))

    if not runs:
        logger.info(
            "No LangSmith runs found for export after %s (project=%s, lookback=%ss, retries=%s).",
            start_time.isoformat(),
            project_name,
            lookback_seconds,
            retries,
        )
        return

    rows: list[dict[str, Any]] = []
    # LangSmith `list_runs` returns runs in reverse chronological order (newest first).
    # Iterate in reverse so that rows are written oldest-first for chronological XLSX output.
    for run in reversed(runs):
        langsmith_run_id = str(run.id)
        latency_s: float | None = None
        if run.start_time and run.end_time:
            latency_s = (run.end_time - run.start_time).total_seconds()
        input_tokens = getattr(run, "prompt_tokens", None)
        output_tokens = getattr(run, "completion_tokens", None)
        total_tokens = getattr(run, "total_tokens", None)
        llm_cost = getattr(run, "total_cost", None)

        run_extra = getattr(run, "extra", None) or {}
        run_metadata = run.metadata
        conversation_id = None
        if isinstance(run_metadata, dict):
            conversation_id = (
                run_metadata.get("conversation_id")
                or run_metadata.get("senpai_conversation_id")
                or run_metadata.get("chat_conversation_id")
                or run_metadata.get("thread_id")  # Standard LangSmith thread key
                or run_metadata.get("session_id")
            )

        rows.append(
            {
                "automation_run_timestamp": automation_run_timestamp,
                "conversation_id": conversation_id,
                "langsmith_run_id": langsmith_run_id,
                "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
                "trace_id": str(run.trace_id)
                if getattr(run, "trace_id", None)
                else None,
                "run_type": getattr(run, "run_type", None),
                "name": getattr(run, "name", None),
                "start_time": _serialize_trace_field(getattr(run, "start_time", None)),
                "end_time": _serialize_trace_field(getattr(run, "end_time", None)),
                "latency_s": latency_s,
                "error": _serialize_trace_field(getattr(run, "error", None)),
                "execution_order": getattr(run, "execution_order", None),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "llm_cost": llm_cost,
                "tags": _serialize_trace_field(getattr(run, "tags", None)),
                "metadata": _serialize_trace_field(run_extra.get("metadata")),
            }
        )
    if not rows:
        logger.info("No new LangSmith runs to append to '%s'.", xlsx_path)
        return

    trace_df = pd.DataFrame(rows, columns=_TRACE_COLUMNS)
    if xlsx_path.exists():
        try:
            existing_df = pd.read_excel(xlsx_path)
            trace_df = pd.concat([existing_df, trace_df], ignore_index=True)
        except Exception:
            logger.exception(
                "Failed to read existing tracing file '%s'. Rewriting it.", xlsx_path
            )
    trace_df = trace_df.drop_duplicates(subset=["langsmith_run_id"], keep="last")
    trace_df.to_excel(xlsx_path, index=False)

    logger.info(
        "Exported %d LangSmith runs to '%s' (fetched %d new runs before deduplication).",
        len(trace_df),
        xlsx_path,
        len(rows),
    )


def update_results_metrics_from_tracing(
    tracing_path: str | Path,
    results_path: str | Path,
) -> None:
    """
    Update results.xlsx with metrics computed from tracing.xlsx.

    Mapping rule:
    - tracing.conversation_id -> results.run_id

    Metrics:
    - llm_call_count: count of rows where run_type == "llm" for each conversation
    - total_input_tokens: input_tokens from the first row where name == "LangGraph"
      for each conversation (LangGraph aggregate row)
    """
    tracing_file = Path(tracing_path).expanduser()
    results_file = Path(results_path).expanduser()

    if not tracing_file.exists():
        logger.warning(
            "Cannot update tracing-derived metrics: tracing file does not exist: %s",
            tracing_file,
        )
        return
    if not results_file.exists():
        logger.warning(
            "Cannot update tracing-derived metrics: results file does not exist: %s",
            results_file,
        )
        return

    try:
        tracing_df = pd.read_excel(tracing_file)
        results_df = pd.read_excel(results_file)
    except Exception:
        logger.exception(
            "Failed reading tracing/results xlsx files to update tracing-derived metrics."
        )
        return

    required_tracing_cols_for_llm = {"conversation_id", "run_type"}
    if not required_tracing_cols_for_llm.issubset(tracing_df.columns):
        logger.warning(
            "Cannot update tracing-derived metrics: tracing file is missing columns %s",
            sorted(required_tracing_cols_for_llm - set(tracing_df.columns)),
        )
        return
    if "run_id" not in results_df.columns:
        logger.warning(
            "Cannot update tracing-derived metrics: results file is missing 'run_id' column."
        )
        return

    llm_mask = tracing_df["run_type"].astype(str).str.lower().eq("llm")
    conv_series = tracing_df["conversation_id"].astype(str)
    valid_conv_mask = (
        tracing_df["conversation_id"].notna()
        & conv_series.ne("")
        & conv_series.ne("nan")
    )
    llm_counts = (
        tracing_df[llm_mask & valid_conv_mask]
        .groupby("conversation_id")
        .size()
        .to_dict()
    )

    total_input_tokens_updated = False
    if {"name", "input_tokens"}.issubset(tracing_df.columns):
        langgraph_mask = tracing_df["name"].astype(str).str.strip().eq("LangGraph")
        langgraph_rows = tracing_df[langgraph_mask & valid_conv_mask].copy()
        if not langgraph_rows.empty:
            # Keep the first LangGraph row seen per conversation; this row contains the aggregate totals.
            langgraph_rows = langgraph_rows.drop_duplicates(
                subset=["conversation_id"], keep="first"
            )
            langgraph_rows["input_tokens"] = pd.to_numeric(
                langgraph_rows["input_tokens"], errors="coerce"
            )
            total_input_tokens_by_conv = langgraph_rows.set_index("conversation_id")[
                "input_tokens"
            ].to_dict()
        else:
            total_input_tokens_by_conv = {}
        results_df["total_input_tokens"] = (
            pd.to_numeric(
                results_df["run_id"].map(total_input_tokens_by_conv), errors="coerce"
            )
            .fillna(0)
            .astype(int)
        )
        total_input_tokens_updated = True
    else:
        logger.warning(
            "Skipping total_input_tokens update: tracing file is missing columns %s",
            sorted({"name", "input_tokens"} - set(tracing_df.columns)),
        )

    results_df["llm_call_count"] = (
        results_df["run_id"].map(llm_counts).fillna(0).astype(int)
    )
    results_df.to_excel(results_file, index=False)
    if total_input_tokens_updated:
        logger.info(
            "Updated llm_call_count and total_input_tokens in '%s' from tracing '%s'.",
            results_file,
            tracing_file,
        )
    else:
        logger.info(
            "Updated llm_call_count in '%s' from tracing '%s' (total_input_tokens skipped).",
            results_file,
            tracing_file,
        )
