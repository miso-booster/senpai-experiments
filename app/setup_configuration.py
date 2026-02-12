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

SENPAI_PREFIX_RE = re.compile(r"Senpai:\s*(.*)$")


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


def build_cmd(arch: Architecture, sensei_project: str, user_prompt: str, verbose: bool, tracing_dir: pathlib.Path) -> List[str]:
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
            "-pp",
            str(project_path),
            "-up",
            str(user_path),
            "-lf",
            str(logs_folder),
            "-stp",
            user_prompt.rstrip(),
            "-tp",
            tracing_dir
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


def build_env(arch: Architecture, timestamp: str) -> Dict[str, str]:
    env = os.environ.copy()
    if arch.env_file:
        env.update(parse_env_file(arch.env_file))
    if arch.env:
        env.update(arch.env)
    env["AUTOMATION_RUN_TIMESTAMP"] = timestamp

    langsmith_project = env.get("LANGSMITH_PROJECT")
    if langsmith_project:
        env["LANGSMITH_PROJECT"] = f"{langsmith_project}_{timestamp}"
    return env
