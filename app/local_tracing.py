"""Local CSV export helpers for LangSmith traces."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.utilities import escape_multiline_text

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
    "latency_ms",
    "outputs",
    "error",
    "execution_order",
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


def _resolve_tracing_csv_path(tracing_path: str | Path, automation_run_timestamp: str) -> Path:
    """Build the timestamped CSV path used to store LangSmith traces."""
    base_path = Path(tracing_path).expanduser()
    if base_path.suffix.lower() == ".csv":
        directory = base_path.parent
        stem = base_path.stem
    else:
        directory = base_path
        stem = f"{_TRACE_FILENAME_STEM}_{automation_run_timestamp}"
    return directory / f"{stem}.csv"


def _serialize_trace_field(value: Any) -> str | int | float | None:
    """Serialize LangSmith run fields for CSV output."""


    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (str, int, float)):
        if isinstance(value, str):
            return escape_multiline_text(value)
        return value
    return str(value)


def export_langsmith_traces_to_csv(
    tracing_path: str | Path,
    start_time: datetime,
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Export LangSmith traces for one automation execution to a local CSV."""
    env_data = env or os.environ
    if env_data.get("LANGSMITH_TRACING", "").lower() != "true":
        logger.debug("Skipping tracing export because LANGSMITH_TRACING is not enabled.")
        return

    project_name = env_data.get("LANGSMITH_PROJECT") or env_data.get("LANGCHAIN_PROJECT")
    if not project_name:
        logger.warning("Skipping tracing export because no LangSmith project is configured.")
        return

    api_key = env_data.get("LANGSMITH_API_KEY") or env_data.get("LANGCHAIN_API_KEY")
    if not api_key:
        logger.warning("Skipping tracing export because no LangSmith API key is configured.")
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
    csv_path = _resolve_tracing_csv_path(tracing_path, automation_run_timestamp)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    client = Client(api_url=api_url, api_key=api_key)

    lookback_seconds = int(env_data.get("LANGSMITH_EXPORT_LOOKBACK_SECONDS", "30"))
    retries = int(env_data.get("LANGSMITH_EXPORT_RETRIES", "4"))
    retry_delay_seconds = float(env_data.get("LANGSMITH_EXPORT_RETRY_DELAY_SECONDS", "0.8"))
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
    # Iterate in reverse so that rows are written oldest-first for chronological CSV output.
    for run in reversed(runs):
        langsmith_run_id = str(run.id)
        latency_ms: float | None = None
        if run.start_time and run.end_time:
            latency_ms = (run.end_time - run.start_time).total_seconds()

        run_extra = getattr(run, "extra", None) or {}
        run_metadata = run.metadata
        conversation_id = None
        if isinstance(run_metadata, dict):
            conversation_id = (
                    run.metadata.get("conversation_id")
                    or run.metadata.get("senpai_conversation_id")
                    or run.metadata.get("chat_conversation_id")
                    or run.metadata.get("thread_id")  # Standard LangSmith thread key
                    or run.metadata.get("session_id")
            )

        rows.append(
            {
                "automation_run_timestamp": automation_run_timestamp,
                "conversation_id": conversation_id,
                "langsmith_run_id": langsmith_run_id,
                "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
                "trace_id": str(run.trace_id) if getattr(run, "trace_id", None) else None,
                "run_type": getattr(run, "run_type", None),
                "name": getattr(run, "name", None),
                "start_time": _serialize_trace_field(getattr(run, "start_time", None)),
                "end_time": _serialize_trace_field(getattr(run, "end_time", None)),
                "latency_ms": latency_ms,
                "outputs": _serialize_trace_field(getattr(run, "outputs", None)),
                "error": _serialize_trace_field(getattr(run, "error", None)),
                "execution_order": getattr(run, "execution_order", None),
                "tags": _serialize_trace_field(getattr(run, "tags", None)),
                "metadata": _serialize_trace_field(run_extra.get("metadata")),
            }
        )
    if not rows:
        logger.info("No new LangSmith runs to append to '%s'.", csv_path)
        return

    file_exists = csv_path.exists()
    trace_df = pd.DataFrame(rows, columns=_TRACE_COLUMNS)
    trace_df.to_csv(
        csv_path,
        sep=";",
        index=False,
        mode="a",
        header=not file_exists,
        encoding="utf-8-sig",
        lineterminator="\r\n",
    )

    logger.info("Exported %d LangSmith runs to '%s'.", len(rows), csv_path)
