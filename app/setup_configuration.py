import os
import re
import json
import pathlib
import logging

from typing import List, Dict
from app.architecture import Architecture




# ====== CONFIGURA ESTO ======
PROJECTS_PATH = r"E:\ESCRITORIO\Py_projects\Senpai-Assistant\sensei_projects"
USER_PATH    = r"E:\ESCRITORIO\Py_projects\Senpai-Assistant\users\user_1"
LOGS_FOLDER  = r"E:\ESCRITORIO\Py_projects\Senpai-Assistant\logs_folder"

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


def project_exists(project_name: str) -> bool:
    project_path = pathlib.Path(PROJECTS_PATH) / project_name
    return project_path.exists()


def build_cmd(arch: Architecture, sensei_project: str) -> List[str]:
    # Monta: <cmd base> -v -pp ... -up ... -lf ... (sin -cid)

    project_path = pathlib.Path(PROJECTS_PATH) / sensei_project
    if not project_path.exists():
        message = f"Sensei project folder does not exist: {project_path}"
        logging.error(message)
        raise FileNotFoundError(message)
    return (
        arch.cmd
        + ["-v", "-pp", str(project_path), "-up", USER_PATH, "-lf", LOGS_FOLDER]
    )


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


def build_env(arch: Architecture) -> Dict[str, str]:
    env = os.environ.copy()
    if arch.env_file:
        env.update(parse_env_file(arch.env_file))
    if arch.env:
        env.update(arch.env)
    return env
