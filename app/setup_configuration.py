import os
import re
import json
import pathlib
import logging


from typing import List, Dict
from app.architecture import Architecture


# Comando de salida del chat. Cambia si tu CLI usa otro (por ej. "exit", "/quit", etc.)
EXIT_COMMAND = "exit"

OUT_DIR = pathlib.Path(__file__).parent.parent / "out"
RUNS_DIR = OUT_DIR / "runs"
RESULTS_PATH = OUT_DIR / "results.jsonl"
MODEL_BUCKET_DIRNAME = "by_model"

RQ2_EXPERIMENT_DIRNAME = "architecture_comparison"
RQ3_EXPERIMENT_DIRNAME = "advanced_prompt_arch_comparison"
RQ4_EXPERIMENT_DIRNAME = "guardrail_test"

SENPAI_PREFIX_RE = re.compile(r"Senpai:\s*(.*)$")


def sanitize_path_component(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    if not normalized:
        raise ValueError("Path component cannot be empty.")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not slug:
        raise ValueError(f"Could not derive a filesystem-safe slug from: {raw!r}")
    return slug


def resolve_experiment_dirname(*, rq2: bool = False, rq3: bool = False, rq4: bool = False) -> str:
    enabled = [name for name, flag in {
        RQ2_EXPERIMENT_DIRNAME: rq2,
        RQ3_EXPERIMENT_DIRNAME: rq3,
        RQ4_EXPERIMENT_DIRNAME: rq4,
    }.items() if flag]
    if len(enabled) != 1:
        raise ValueError("Exactly one experiment flag must be enabled.")
    return enabled[0]


def resolve_runs_dir(experiment_dirname: str, model_label: str | None = None) -> pathlib.Path:
    base_dir = RUNS_DIR / experiment_dirname
    if not model_label:
        return base_dir
    return base_dir / MODEL_BUCKET_DIRNAME / sanitize_path_component(model_label)


def load_architectures(path: str) -> List[Architecture]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    archs = []
    for a in data["architectures"]:
        archs.append(
            Architecture(
                id=a["id"],
                cmd=a["cmd"],
                cwd=a.get("cwd"),
                env=a.get("env"),
                env_file=a.get("env_file"),
            )
        )
    return archs


def load_prompts_json(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


# def project_exists(project_name: str) -> bool:
#     project_path = pathlib.Path(PROJECTS_PATH) / project_name
#     return project_path.exists()


def build_cmd(arch: Architecture, sensei_project: str, user_prompt: str, verbose: bool, run_id: str) -> List[str]:
    # Monta: <cmd base> -v -pp ... -up ... -lf ... (sin -cid)

    project_path = pathlib.Path(arch.cwd) / "sensei_projects" / sensei_project
    user_path = pathlib.Path(arch.cwd) / "users" / "user_1"
    logs_folder = pathlib.Path(arch.cwd) / "logs_folder"

    if not project_path.exists():
        message = f"Sensei project folder does not exist: {project_path}"
        logging.error(message)
        raise FileNotFoundError(message)

    cmd = (
        arch.cmd
        + [
            "-cid",
            str(run_id),
            "-pp",
            str(project_path),
            "-up",
            str(user_path),
            "-lf",
            str(logs_folder),
            "-stp",
            user_prompt.rstrip(),
        ]
    )

    if verbose:
        cmd.append("-v")

    return cmd


def parse_env_file(path: str) -> Dict[str, str]:
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
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


def ensure_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def build_env(
    arch: Architecture,
    timestamp: str,
    *,
    model_label: str | None = None,
) -> Dict[str, str]:
    env = os.environ.copy()
    if arch.env_file:
        env.update(parse_env_file(arch.env_file))
    if arch.env:
        env.update(arch.env)
    # Force UTF-8 for child Python processes to avoid locale-dependent mojibake.
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    env["AUTOMATION_RUN_TIMESTAMP"] = timestamp
    if model_label:
        env["AUTOMATION_MODEL_LABEL"] = model_label
        env["AUTOMATION_MODEL_SLUG"] = sanitize_path_component(model_label)

    langsmith_project = env.get("LANGSMITH_PROJECT")
    if langsmith_project:
        env["LANGSMITH_PROJECT"] = f"{langsmith_project}_{timestamp}"
    return env
