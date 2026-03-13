import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

try:
    from app.setup_configuration import OUT_DIR, RUNS_DIR
except Exception:  # Supports `python app/rq3_clustering/answer_clustering.py` without package imports
    _ROOT = Path(__file__).resolve().parents[2]
    OUT_DIR = _ROOT / "out"
    RUNS_DIR = OUT_DIR / "runs"

try:
    from app.setup_configuration import parse_env_file
except Exception:  # Supports `python app/rq3_clustering/answer_clustering.py` without package imports
    def parse_env_file(path: str) -> dict[str, str]:
        env: dict[str, str] = {}
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    env[key] = value
        return env

try:
    from .excel import save_outputs
    from .review import build_review_assignments, build_review_cluster_reference
except ImportError:  # Supports `python app/rq3_clustering/answer_clustering.py`
    from excel import save_outputs
    from review import build_review_assignments, build_review_cluster_reference


DEFAULT_RUNS_DIR = RUNS_DIR / "advanced_prompt_arch_comparison"
DEFAULT_OUT_DIR = OUT_DIR / "RQ3_clustering"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_API_TIMEOUT_S = 120
DEFAULT_CACHE_DIRNAME = "_cluster_cache"
DEFAULT_MAX_CLUSTER_RETRIES = 4
REQUIRED_COLUMNS = ("arch_id", "prompt_id", "run_group_id", "answer")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CLUSTER_JSON_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "answer_clustering",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "clusters": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "cluster_label": {"type": "string"},
                            "cluster_summary": {"type": "string"},
                            "response_ids": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["cluster_label", "cluster_summary", "response_ids"],
                        "additionalProperties": False,
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["clusters", "notes"],
            "additionalProperties": False,
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cluster repeated answers per architecture and prompt using the OpenAI API, "
            "while also exporting the answer matrices used for RQ3."
        )
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help=f"Directory containing run folders (default: {DEFAULT_RUNS_DIR})",
    )
    parser.add_argument(
        "--results-name",
        default="results.xlsx",
        help="Workbook filename inside each run folder (default: results.xlsx)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Output directory for clustering workbooks (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--sheet",
        help="Optional sheet name to read from each workbook (default: first sheet)",
    )
    parser.add_argument(
        "--arch-ids",
        nargs="*",
        help="Optional arch_id values to include (default: all detected)",
    )
    parser.add_argument(
        "--prompt-ids",
        nargs="*",
        help="Optional prompt_id values to include (default: all detected)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model used for semantic clustering (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--api-timeout-s",
        type=int,
        default=DEFAULT_API_TIMEOUT_S,
        help=f"Timeout in seconds for each OpenAI request (default: {DEFAULT_API_TIMEOUT_S})",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Skip OpenAI clustering and only export the answer matrices and inventory sheets",
    )
    parser.add_argument(
        "--max-groups",
        type=int,
        help="Optional limit on architecture/prompt groups to cluster, useful for smoke testing",
    )
    parser.add_argument(
        "--cache-dir",
        help=(
            "Optional directory for cached cluster responses. "
            "Defaults to <out-dir>/_cluster_cache."
        ),
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cached cluster responses and call the API again",
    )
    parser.add_argument(
        "--max-cluster-retries",
        type=int,
        default=DEFAULT_MAX_CLUSTER_RETRIES,
        help=f"Maximum OpenAI repair attempts per prompt group before auto-repair (default: {DEFAULT_MAX_CLUSTER_RETRIES})",
    )
    parser.add_argument(
        "--export-csvs",
        action="store_true",
        help="Also export CSV files for matrices and clustering reports",
    )
    return parser.parse_args()


def _clean_string_id(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    return cleaned.mask(cleaned == "", pd.NA)


def _clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _first_non_empty(series: pd.Series) -> str:
    for value in series.tolist():
        text = _clean_text(value)
        if text:
            return text
    return ""


def _prompt_sort_key(value: object) -> tuple[int, str]:
    text = "" if value is None else str(value).strip().lower()
    match = re.fullmatch(r"p(\d+)(?:_(.+))?", text)
    if not match:
        return (10**9, text)
    return (int(match.group(1)), text)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return slug.strip("_") or "value"


def discover_workbooks(runs_dir: Path, results_name: str) -> list[Path]:
    if not runs_dir.exists():
        raise SystemExit(f"runs-dir not found: {runs_dir}")
    if not runs_dir.is_dir():
        raise SystemExit(f"runs-dir is not a directory: {runs_dir}")
    workbooks = sorted(path for path in runs_dir.glob(f"*/{results_name}") if path.is_file())
    if not workbooks:
        raise SystemExit(f"No workbooks found at {runs_dir} with name {results_name}")
    return workbooks


def load_workbook(path: Path, sheet_name: str | None) -> pd.DataFrame:
    chosen_sheet = sheet_name
    if chosen_sheet is None:
        xl = pd.ExcelFile(path)
        if not xl.sheet_names:
            raise ValueError("Workbook has no sheets")
        chosen_sheet = xl.sheet_names[0]

    df = pd.read_excel(path, sheet_name=chosen_sheet)
    if df.empty:
        return df

    df = df.copy()
    df["source_results_xlsx"] = str(path)
    df["source_run_folder"] = path.parent.name
    if "run_group_id" not in df.columns:
        df["run_group_id"] = path.parent.name
    else:
        missing = df["run_group_id"].isna() | (df["run_group_id"].astype(str).str.strip() == "")
        df.loc[missing, "run_group_id"] = path.parent.name
    return df


def load_all_results(workbooks: Sequence[Path], sheet_name: str | None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for workbook in workbooks:
        try:
            frame = load_workbook(workbook, sheet_name)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[WARN] Skipping {workbook}: {exc}")
            continue
        if not frame.empty:
            frames.append(frame)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True, sort=False)
    for column in ("arch_id", "prompt_id", "run_group_id", "run_id"):
        if column in df.columns:
            df[column] = _clean_string_id(df[column])
    if "prompt" in df.columns:
        df["prompt"] = df["prompt"].astype("string")
    if "answer" in df.columns:
        df["answer"] = df["answer"].astype("string")
    return df


def _require_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise SystemExit(f"Missing required columns: {', '.join(missing)}")


def filter_rows(
    df: pd.DataFrame,
    arch_ids: Sequence[str] | None,
    prompt_ids: Sequence[str] | None,
) -> pd.DataFrame:
    filtered = df.copy()
    if arch_ids:
        wanted_arches = {value.strip() for value in arch_ids if value and value.strip()}
        filtered = filtered[filtered["arch_id"].isin(wanted_arches)]
    if prompt_ids:
        wanted_prompts = {value.strip() for value in prompt_ids if value and value.strip()}
        filtered = filtered[filtered["prompt_id"].isin(wanted_prompts)]
    filtered = filtered[filtered["answer"].notna()].copy()
    filtered["answer"] = filtered["answer"].astype("string")
    return filtered


def build_inventory(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "arch_id",
        "prompt_id",
        "prompt",
        "run_group_id",
        "run_id",
        "answer",
        "source_run_folder",
        "source_results_xlsx",
    ]
    existing = [column for column in columns if column in df.columns]
    inventory = df[existing].copy()
    inventory["answer_length"] = inventory["answer"].astype("string").str.len()
    inventory["_prompt_order"] = inventory["prompt_id"].map(_prompt_sort_key)
    inventory = inventory.sort_values(
        ["arch_id", "_prompt_order", "prompt_id", "run_group_id", "run_id"],
        kind="stable",
    ).reset_index(drop=True)
    return inventory.drop(columns=["_prompt_order"])


def build_duplicates_report(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["arch_id", "prompt_id", "run_group_id"]
    grouped = (
        df.groupby(group_cols, dropna=False)
        .agg(
            answer_count=("answer", "size"),
            distinct_answer_count=("answer", lambda s: s.astype("string").nunique(dropna=True)),
            sample_answer=("answer", "first"),
        )
        .reset_index()
    )
    duplicates = grouped[grouped["answer_count"] > 1].copy()
    if duplicates.empty:
        return duplicates
    duplicates["_prompt_order"] = duplicates["prompt_id"].map(_prompt_sort_key)
    duplicates = duplicates.sort_values(
        ["arch_id", "_prompt_order", "prompt_id", "run_group_id"],
        kind="stable",
    ).reset_index(drop=True)
    return duplicates.drop(columns=["_prompt_order"])


def _collapse_answer(series: pd.Series) -> str | None:
    non_null = [value for value in series.astype("string").tolist() if pd.notna(value)]
    return non_null[0] if non_null else None


def build_architecture_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    prompt_order = sorted(df["prompt_id"].dropna().astype(str).unique().tolist(), key=_prompt_sort_key)
    run_group_order = sorted(df["run_group_id"].dropna().astype(str).unique().tolist())

    for arch_id, group in df.groupby("arch_id", sort=True):
        collapsed = (
            group.groupby(["prompt_id", "run_group_id"], dropna=False)["answer"]
            .agg(_collapse_answer)
            .reset_index()
        )
        table = collapsed.pivot(index="prompt_id", columns="run_group_id", values="answer")
        table = table.reindex(index=prompt_order, columns=run_group_order)
        table.index.name = "prompt_id"
        tables[str(arch_id)] = table

    return tables


def _prepare_group_rows(group: pd.DataFrame) -> pd.DataFrame:
    prepared = group.copy()
    sort_columns = [column for column in ("run_group_id", "run_id", "source_run_folder", "source_results_xlsx") if column in prepared.columns]
    prepared = prepared.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    width = max(2, len(str(len(prepared))))
    prepared["response_index"] = list(range(1, len(prepared) + 1))
    prepared["response_id"] = [f"r{index:0{width}d}" for index in prepared["response_index"].tolist()]
    prepared["prompt"] = prepared["prompt"] if "prompt" in prepared.columns else ""
    return prepared


def _build_cache_key(
    arch_id: str,
    prompt_id: str,
    prompt_text: str,
    model: str,
    rows: pd.DataFrame,
) -> str:
    serializable = {
        "arch_id": arch_id,
        "prompt_id": prompt_id,
        "prompt": prompt_text,
        "model": model,
        "responses": [
            {
                "response_id": row["response_id"],
                "run_group_id": _clean_text(row.get("run_group_id")),
                "run_id": _clean_text(row.get("run_id")),
                "answer": _clean_text(row.get("answer")),
            }
            for _, row in rows.iterrows()
        ],
    }
    payload = json.dumps(serializable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cache_path_for_group(
    cache_dir: Path,
    arch_id: str,
    prompt_id: str,
    cache_key: str,
) -> Path:
    filename = f"{_slugify(arch_id)}__{_slugify(prompt_id)}__{cache_key}.json"
    return cache_dir / filename


def _build_cluster_messages(
    arch_id: str,
    prompt_id: str,
    prompt_text: str,
    rows: pd.DataFrame,
    validation_error: str | None = None,
) -> tuple[str, str]:
    system_message = (
        "You are a rigorous research assistant clustering repeated LLM answers. "
        "The responses all answer the same user prompt under the same architecture. "
        "Group answers by substantive meaning and final conclusion, not wording. "
        "Merge answers that are materially equivalent. "
        "Keep answers separate when they differ on facts, selected files, endpoints, counts, classifications, or any other evaluation-relevant claim. "
        "Each response_id must appear in exactly one cluster. "
        "Use concise cluster labels that describe the shared conclusion. "
        "Return JSON only."
    )

    response_lines: list[str] = []
    for _, row in rows.iterrows():
        response_lines.append(
            "\n".join(
                [
                    f"response_id: {row['response_id']}",
                    f"run_group_id: {_clean_text(row.get('run_group_id'))}",
                    f"run_id: {_clean_text(row.get('run_id'))}",
                    "answer:",
                    _clean_text(row.get("answer")),
                ]
            )
        )

    user_parts = [
        f"architecture_id: {arch_id}",
        f"prompt_id: {prompt_id}",
        f"prompt_text: {prompt_text or '(missing prompt text)'}",
        "",
        "Cluster the following responses:",
        "",
        "\n\n".join(response_lines),
        "",
        "Rules:",
        "- Every response_id must appear exactly once.",
        "- Do not create singleton clusters unless the response is genuinely distinct.",
        "- cluster_summary should briefly explain why those responses belong together.",
        "- notes should mention any borderline distinctions if relevant, otherwise use an empty string.",
    ]
    if validation_error:
        user_parts.extend(
            [
                "",
                "Your previous output was invalid.",
                f"Fix this issue: {validation_error}",
            ]
        )

    return system_message, "\n".join(user_parts)


def _parse_cluster_response(response: Any) -> Mapping[str, Any]:
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def _request_cluster_payload(
    client: OpenAI,
    model: str,
    system_message: str,
    user_message: str,
    api_timeout_s: int,
) -> Mapping[str, Any]:
    def _request(response_format: Mapping[str, Any]) -> Any:
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            "response_format": response_format,
            "timeout": api_timeout_s,
        }
        # GPT-5 mini on chat.completions currently only supports the default temperature.
        if not model.startswith("gpt-5"):
            request_kwargs["temperature"] = 0

        return client.chat.completions.create(
            **request_kwargs,
        )

    try:
        response = _request(CLUSTER_JSON_SCHEMA)
        return _parse_cluster_response(response)
    except (BadRequestError, APIStatusError, APIResponseValidationError):
        response = _request({"type": "json_object"})
        return _parse_cluster_response(response)


def normalize_cluster_payload(
    payload: Mapping[str, Any],
    expected_response_ids: Sequence[str],
) -> list[dict[str, Any]]:
    raw_clusters = payload.get("clusters")
    if not isinstance(raw_clusters, list) or not raw_clusters:
        raise ValueError("LLM payload must contain a non-empty 'clusters' list.")

    expected_order = {response_id: index for index, response_id in enumerate(expected_response_ids)}
    expected_set = set(expected_response_ids)
    seen_ids: list[str] = []
    normalized: list[dict[str, Any]] = []

    for raw_cluster in raw_clusters:
        if not isinstance(raw_cluster, Mapping):
            raise ValueError("Each cluster must be an object.")
        cluster_label = _clean_text(raw_cluster.get("cluster_label"))
        cluster_summary = _clean_text(raw_cluster.get("cluster_summary"))
        response_ids = raw_cluster.get("response_ids")
        if not isinstance(response_ids, list) or not response_ids:
            raise ValueError("Each cluster must include a non-empty response_ids list.")

        clean_ids = [_clean_text(value) for value in response_ids if _clean_text(value)]
        if not clean_ids:
            raise ValueError("Each cluster must include at least one valid response_id.")

        seen_ids.extend(clean_ids)
        normalized.append(
            {
                "cluster_label": cluster_label or "Unlabeled cluster",
                "cluster_summary": cluster_summary or "Responses share the same underlying answer.",
                "response_ids": clean_ids,
            }
        )

    counts = Counter(seen_ids)
    duplicates = sorted(response_id for response_id, count in counts.items() if count > 1)
    seen_set = set(seen_ids)
    missing = sorted(expected_set - seen_set)
    extra = sorted(seen_set - expected_set)
    if duplicates or missing or extra:
        errors: list[str] = []
        if duplicates:
            errors.append(f"duplicate ids: {', '.join(duplicates)}")
        if missing:
            errors.append(f"missing ids: {', '.join(missing)}")
        if extra:
            errors.append(f"unexpected ids: {', '.join(extra)}")
        raise ValueError("; ".join(errors))

    normalized.sort(
        key=lambda item: (
            -len(item["response_ids"]),
            min(expected_order[response_id] for response_id in item["response_ids"]),
        )
    )

    for index, cluster in enumerate(normalized, start=1):
        cluster["cluster_id"] = f"c{index}"
        cluster["response_ids"] = sorted(cluster["response_ids"], key=expected_order.get)

    return normalized


def repair_cluster_payload(
    payload: Mapping[str, Any],
    expected_response_ids: Sequence[str],
) -> Mapping[str, Any]:
    raw_clusters = payload.get("clusters")
    if not isinstance(raw_clusters, list):
        raw_clusters = []

    expected_set = set(expected_response_ids)
    seen_ids: set[str] = set()
    repaired_clusters: list[dict[str, Any]] = []
    repair_notes: list[str] = []

    for index, raw_cluster in enumerate(raw_clusters, start=1):
        if not isinstance(raw_cluster, Mapping):
            repair_notes.append(f"dropped invalid cluster object at position {index}")
            continue

        cluster_label = _clean_text(raw_cluster.get("cluster_label")) or f"Recovered cluster {index}"
        cluster_summary = (
            _clean_text(raw_cluster.get("cluster_summary"))
            or "Recovered from an invalid clustering payload."
        )
        response_ids = raw_cluster.get("response_ids")
        if not isinstance(response_ids, list):
            repair_notes.append(f"dropped cluster '{cluster_label}' because response_ids was not a list")
            continue

        cleaned_ids: list[str] = []
        for value in response_ids:
            response_id = _clean_text(value)
            if not response_id:
                continue
            if response_id not in expected_set:
                repair_notes.append(f"dropped unexpected id {response_id}")
                continue
            if response_id in seen_ids:
                repair_notes.append(f"dropped duplicate id {response_id}")
                continue
            cleaned_ids.append(response_id)
            seen_ids.add(response_id)

        if cleaned_ids:
            repaired_clusters.append(
                {
                    "cluster_label": cluster_label,
                    "cluster_summary": cluster_summary,
                    "response_ids": cleaned_ids,
                }
            )

    missing_ids = [response_id for response_id in expected_response_ids if response_id not in seen_ids]
    for response_id in missing_ids:
        repaired_clusters.append(
            {
                "cluster_label": f"Auto-repaired singleton {response_id}",
                "cluster_summary": (
                    "This response was omitted by the clustering model and was conservatively "
                    "kept as its own singleton cluster."
                ),
                "response_ids": [response_id],
            }
        )
    if missing_ids:
        repair_notes.append(f"added singleton clusters for missing ids: {', '.join(missing_ids)}")

    notes = _clean_text(payload.get("notes"))
    if repair_notes:
        notes = " | ".join(part for part in [notes, "auto_repair=" + "; ".join(repair_notes)] if part)

    return {
        "clusters": repaired_clusters,
        "notes": notes,
    }


def build_cluster_frames_for_group(
    group: pd.DataFrame,
    payload: Mapping[str, Any],
    *,
    model: str,
    result_source: str,
    cache_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prepared = _prepare_group_rows(group)
    expected_ids = prepared["response_id"].tolist()
    normalized_clusters = normalize_cluster_payload(payload, expected_ids)

    arch_id = str(prepared["arch_id"].iloc[0])
    prompt_id = str(prepared["prompt_id"].iloc[0])
    prompt_text = _first_non_empty(prepared["prompt"])
    total_responses = len(prepared)
    response_lookup = prepared.set_index("response_id", drop=False)
    notes = _clean_text(payload.get("notes"))
    cache_path_str = str(cache_path) if cache_path is not None else ""

    assignment_rows: list[dict[str, Any]] = []
    cluster_rows: list[dict[str, Any]] = []

    for cluster in normalized_clusters:
        cluster_id = cluster["cluster_id"]
        response_ids = cluster["response_ids"]
        cluster_size = len(response_ids)
        cluster_share = cluster_size / total_responses if total_responses else 0.0
        representative_response_id = response_ids[0]
        representative_response_index = int(response_lookup.loc[representative_response_id, "response_index"])
        representative_answer = _clean_text(response_lookup.loc[representative_response_id, "answer"])
        response_indexes = [
            int(response_lookup.loc[response_id, "response_index"])
            for response_id in response_ids
        ]
        run_group_ids = [
            _clean_text(response_lookup.loc[response_id].get("run_group_id"))
            for response_id in response_ids
        ]

        cluster_rows.append(
            {
                "arch_id": arch_id,
                "prompt_id": prompt_id,
                "prompt": prompt_text,
                "cluster_id": cluster_id,
                "cluster_label": cluster["cluster_label"],
                "cluster_summary": cluster["cluster_summary"],
                "response_count": cluster_size,
                "response_share": cluster_share,
                "response_ids": ", ".join(response_ids),
                "response_indexes": ", ".join(str(value) for value in response_indexes),
                "run_group_ids": ", ".join(run_group_ids),
                "representative_response_id": representative_response_id,
                "representative_response_index": representative_response_index,
                "representative_answer": representative_answer,
                "model": model,
                "result_source": result_source,
                "cache_path": cache_path_str,
                "notes": notes,
            }
        )

        for response_id in response_ids:
            row = response_lookup.loc[response_id]
            assignment_rows.append(
                {
                    "arch_id": arch_id,
                    "prompt_id": prompt_id,
                    "prompt": prompt_text,
                    "response_id": response_id,
                    "response_index": int(row["response_index"]),
                    "run_group_id": _clean_text(row.get("run_group_id")),
                    "run_id": _clean_text(row.get("run_id")),
                    "answer": _clean_text(row.get("answer")),
                    "cluster_id": cluster_id,
                    "cluster_label": cluster["cluster_label"],
                    "cluster_summary": cluster["cluster_summary"],
                    "cluster_size": cluster_size,
                    "cluster_share": cluster_share,
                    "model": model,
                    "result_source": result_source,
                    "cache_path": cache_path_str,
                    "source_run_folder": _clean_text(row.get("source_run_folder")),
                    "source_results_xlsx": _clean_text(row.get("source_results_xlsx")),
                }
            )

    cluster_summary = pd.DataFrame(cluster_rows)
    cluster_summary = cluster_summary.sort_values(
        ["arch_id", "prompt_id", "cluster_id"], key=lambda s: s.map(_prompt_sort_key) if s.name == "prompt_id" else s, kind="stable"
    ).reset_index(drop=True)

    assignments = pd.DataFrame(assignment_rows)
    assignments = assignments.sort_values(
        ["arch_id", "prompt_id", "response_id"],
        key=lambda s: s.map(_prompt_sort_key) if s.name == "prompt_id" else s,
        kind="stable",
    ).reset_index(drop=True)

    majority_cluster = cluster_rows[0]
    prompt_summary = pd.DataFrame(
        [
            {
                "arch_id": arch_id,
                "prompt_id": prompt_id,
                "prompt": prompt_text,
                "total_responses": total_responses,
                "cluster_count": len(cluster_rows),
                "majority_cluster_id": majority_cluster["cluster_id"],
                "majority_cluster_label": majority_cluster["cluster_label"],
                "majority_cluster_size": majority_cluster["response_count"],
                "majority_cluster_share": majority_cluster["response_share"],
                "is_perfect_consensus": len(cluster_rows) == 1,
                "cluster_breakdown": " | ".join(
                    f"{row['cluster_id']}={row['response_count']} ({row['cluster_label']})" for row in cluster_rows
                ),
                "model": model,
                "result_source": result_source,
                "cache_path": cache_path_str,
                "notes": notes,
            }
        ]
    )

    return prompt_summary, cluster_summary, assignments


def _single_response_payload() -> Mapping[str, Any]:
    return {
        "clusters": [
            {
                "cluster_label": "Only observed answer",
                "cluster_summary": "Only one answer was available for this prompt and architecture.",
                "response_ids": ["r01"],
            }
        ],
        "notes": "",
    }


def _get_openai_client() -> OpenAI:
    if "OPENAI_API_KEY" not in os.environ:
        for candidate in (PROJECT_ROOT / ".env", PROJECT_ROOT / "configs" / ".env"):
            if not candidate.is_file():
                continue
            try:
                env_from_file = parse_env_file(str(candidate))
            except FileNotFoundError:
                continue
            api_key = env_from_file.get("OPENAI_API_KEY")
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key
                break

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Export it in the shell or place it in .env / configs/.env, or use --prepare-only."
        )
    return OpenAI(api_key=api_key)


def _cluster_group_via_api(
    group: pd.DataFrame,
    client: OpenAI,
    model: str,
    api_timeout_s: int,
    cache_dir: Path,
    force_refresh: bool,
    max_cluster_retries: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prepared = _prepare_group_rows(group)
    arch_id = str(prepared["arch_id"].iloc[0])
    prompt_id = str(prepared["prompt_id"].iloc[0])
    prompt_text = _first_non_empty(prepared["prompt"])

    if len(prepared) == 1:
        return build_cluster_frames_for_group(
            prepared,
            _single_response_payload(),
            model=model,
            result_source="single_response",
        )

    cache_key = _build_cache_key(arch_id, prompt_id, prompt_text, model, prepared)
    cache_path = _cache_path_for_group(cache_dir, arch_id, prompt_id, cache_key)

    if cache_path.exists() and not force_refresh:
        with cache_path.open("r", encoding="utf-8") as handle:
            cached_document = json.load(handle)
        return build_cluster_frames_for_group(
            prepared,
            cached_document["result"],
            model=model,
            result_source="cache",
            cache_path=cache_path,
        )

    last_error: str | None = None
    last_payload: Mapping[str, Any] | None = None
    for _attempt in range(max(1, max_cluster_retries)):
        system_message, user_message = _build_cluster_messages(
            arch_id,
            prompt_id,
            prompt_text,
            prepared,
            validation_error=last_error,
        )
        payload = _request_cluster_payload(client, model, system_message, user_message, api_timeout_s)
        last_payload = payload
        try:
            normalize_cluster_payload(payload, prepared["response_id"].tolist())
        except ValueError as exc:
            last_error = str(exc)
            continue

        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_document = {
            "arch_id": arch_id,
            "prompt_id": prompt_id,
            "prompt": prompt_text,
            "model": model,
            "responses": prepared[
                ["response_id", "run_group_id", "run_id", "answer"]
            ].to_dict(orient="records"),
            "result": payload,
        }
        with cache_path.open("w", encoding="utf-8") as handle:
            json.dump(cache_document, handle, ensure_ascii=False, indent=2)
        return build_cluster_frames_for_group(
            prepared,
            payload,
            model=model,
            result_source="api",
            cache_path=cache_path,
        )

    if last_payload is not None:
        repaired_payload = repair_cluster_payload(last_payload, prepared["response_id"].tolist())
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_document = {
            "arch_id": arch_id,
            "prompt_id": prompt_id,
            "prompt": prompt_text,
            "model": model,
            "responses": prepared[
                ["response_id", "run_group_id", "run_id", "answer"]
            ].to_dict(orient="records"),
            "result": repaired_payload,
        }
        with cache_path.open("w", encoding="utf-8") as handle:
            json.dump(cache_document, handle, ensure_ascii=False, indent=2)
        print(
            f"[WARN] Auto-repaired invalid clustering payload for arch_id={arch_id} prompt_id={prompt_id}: {last_error}"
        )
        return build_cluster_frames_for_group(
            prepared,
            repaired_payload,
            model=model,
            result_source="api_repaired",
            cache_path=cache_path,
        )

    raise ValueError(
        f"Could not obtain a valid clustering payload for arch_id={arch_id}, prompt_id={prompt_id}: {last_error}"
    )


def cluster_all_prompt_groups(
    df: pd.DataFrame,
    *,
    model: str,
    api_timeout_s: int,
    prepare_only: bool,
    cache_dir: Path,
    force_refresh: bool,
    max_groups: int | None,
    max_cluster_retries: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if prepare_only:
        empty = pd.DataFrame()
        return empty, empty, empty, empty

    prompt_groups = sorted(
        df.groupby(["arch_id", "prompt_id"], dropna=False),
        key=lambda item: (str(item[0][0]), _prompt_sort_key(item[0][1])),
    )
    if max_groups is not None:
        prompt_groups = prompt_groups[:max_groups]

    if not prompt_groups:
        empty = pd.DataFrame()
        return empty, empty, empty, empty

    client = _get_openai_client()

    prompt_frames: list[pd.DataFrame] = []
    cluster_frames: list[pd.DataFrame] = []
    assignment_frames: list[pd.DataFrame] = []

    for (arch_id, prompt_id), group in prompt_groups:
        print(f"[INFO] Processing arch_id={arch_id} prompt_id={prompt_id} ({len(group)} responses)")
        prompt_summary, cluster_summary, assignments = _cluster_group_via_api(
            group,
            client=client,
            model=model,
            api_timeout_s=api_timeout_s,
            cache_dir=cache_dir,
            force_refresh=force_refresh,
            max_cluster_retries=max_cluster_retries,
        )

        prompt_frames.append(prompt_summary)
        cluster_frames.append(cluster_summary)
        assignment_frames.append(assignments)

    prompt_summary_all = pd.concat(prompt_frames, ignore_index=True, sort=False)
    cluster_summary_all = pd.concat(cluster_frames, ignore_index=True, sort=False)
    assignments_all = pd.concat(assignment_frames, ignore_index=True, sort=False)

    overall_summary = (
        prompt_summary_all.groupby("arch_id", dropna=False)
        .agg(
            prompt_count=("prompt_id", "nunique"),
            total_responses=("total_responses", "sum"),
            mean_majority_cluster_share=("majority_cluster_share", "mean"),
            median_majority_cluster_share=("majority_cluster_share", "median"),
            mean_cluster_count=("cluster_count", "mean"),
            perfect_consensus_prompts=("is_perfect_consensus", "sum"),
        )
        .reset_index()
        .sort_values("arch_id", kind="stable")
        .reset_index(drop=True)
    )
    overall_summary["perfect_consensus_rate"] = (
        overall_summary["perfect_consensus_prompts"] / overall_summary["prompt_count"]
    )
    overall_summary["model"] = model

    return overall_summary, prompt_summary_all, cluster_summary_all, assignments_all


def main() -> None:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)
    cache_dir = Path(args.cache_dir) if args.cache_dir else out_dir / DEFAULT_CACHE_DIRNAME

    workbooks = discover_workbooks(runs_dir, args.results_name)
    print(f"[INFO] Found {len(workbooks)} workbook(s).")

    all_rows = load_all_results(workbooks, args.sheet)
    if all_rows.empty:
        raise SystemExit("No rows loaded from workbooks.")

    _require_columns(all_rows, REQUIRED_COLUMNS)
    filtered_rows = filter_rows(all_rows, args.arch_ids, args.prompt_ids)
    if filtered_rows.empty:
        raise SystemExit("No rows left after filtering arch_id / prompt_id / non-null answer.")

    inventory = build_inventory(filtered_rows)
    duplicates = build_duplicates_report(filtered_rows)
    architecture_tables = build_architecture_tables(filtered_rows)
    overall_summary, prompt_summary, cluster_summary, assignments = cluster_all_prompt_groups(
        filtered_rows,
        model=args.model,
        api_timeout_s=args.api_timeout_s,
        prepare_only=args.prepare_only,
        cache_dir=cache_dir,
        force_refresh=args.force_refresh,
        max_groups=args.max_groups,
        max_cluster_retries=args.max_cluster_retries,
    )
    review_assignments = build_review_assignments(assignments)
    review_cluster_reference = build_review_cluster_reference(cluster_summary)

    written_paths = save_outputs(
        out_dir=out_dir,
        architecture_tables=architecture_tables,
        inventory=inventory,
        duplicates=duplicates,
        overall_summary=overall_summary,
        prompt_summary=prompt_summary,
        cluster_summary=cluster_summary,
        cluster_assignments=assignments,
        review_assignments=review_assignments,
        review_cluster_reference=review_cluster_reference,
        export_csvs=args.export_csvs,
    )

    print(f"[INFO] Architectures exported: {len(architecture_tables)}")
    if not duplicates.empty:
        print(f"[WARN] Duplicate answer groups detected: {len(duplicates)}. Using the first non-null answer per group.")
    print("[INFO] Files:")
    for path in written_paths:
        print(f"  - {path.name}")


if __name__ == "__main__":
    try:
        main()
    except AuthenticationError as exc:
        raise SystemExit(f"OpenAI authentication failed: {exc}") from exc
    except RateLimitError as exc:
        raise SystemExit(f"OpenAI rate limit hit during clustering: {exc}") from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise SystemExit(f"OpenAI network or timeout error during clustering: {exc}") from exc
    except (BadRequestError, APIStatusError, APIResponseValidationError, OpenAIError) as exc:
        raise SystemExit(f"OpenAI request failed during clustering: {exc}") from exc
