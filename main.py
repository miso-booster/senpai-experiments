import json
import os
import re
import time
import uuid
import pathlib
import subprocess
import argparse
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from logger import setup_logging

# ====== CONFIGURA ESTO ======
PROJECT_PATH = r"E:\ESCRITORIO\Py_projects\Senpai-Assistant\sensei_projects\pizza_shop"
USER_PATH    = r"E:\ESCRITORIO\Py_projects\Senpai-Assistant\users\user_1"
LOGS_FOLDER  = r"E:\ESCRITORIO\Py_projects\Senpai-Assistant\logs_folder"

# Comando de salida del chat. Cambia si tu CLI usa otro (por ej. "exit", "/quit", etc.)
EXIT_COMMAND = "exit"

OUT_DIR = pathlib.Path(__file__).parent / "out"
RUNS_DIR = OUT_DIR / "runs"
RESULTS_PATH = OUT_DIR / "results.jsonl"

SENPAI_PREFIX_RE = re.compile(r"Senpai:\s*(.*)$")

@dataclass
class Architecture:
    id: str
    cmd: List[str]  # comando base, ej: ["C:\\path\\to\\venv\\python.exe","-m","tu_cli_modulo"]
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    env_file: Optional[str] = None

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

def load_prompts_jsonl(path: str) -> List[Dict[str, str]]:
    prompts = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            prompts.append(json.loads(line))
    return prompts

def extract_senpai_answer(stdout: str) -> str:
    """
    Extrae todas las líneas que contengan 'Senpai:' y las concatena.
    Si no encuentra nada, devuelve stdout completo (fallback).
    """
    answers = []
    for line in stdout.splitlines():
        m = SENPAI_PREFIX_RE.search(line)
        if m:
            answers.append(m.group(1).strip())
    if answers:
        return "\n".join(answers).strip()
    return stdout.strip()

def ensure_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

def build_cmd(arch: Architecture, cid: int) -> List[str]:
    # Monta: <cmd base> -cid <cid> -v -pp ... -up ... -lf ...
    return (
        arch.cmd
        + ["-cid", str(cid), "-v", "-pp", PROJECT_PATH, "-up", USER_PATH, "-lf", LOGS_FOLDER]
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

def build_env(arch: Architecture) -> Dict[str, str]:
    env = os.environ.copy()
    if arch.env_file:
        env.update(parse_env_file(arch.env_file))
    if arch.env:
        env.update(arch.env)
    return env

def run_one(arch: Architecture, prompt_id: str, prompt_text: str, cid: int, timeout_s: int) -> Dict[str, Any]:
    run_id = f"{arch.id}__{prompt_id}__{cid}__{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cmd = build_cmd(arch, cid)
    logging.info("Run start arch=%s prompt=%s cid=%s", arch.id, prompt_id, cid)
    logging.debug("Cmd: %s", cmd)
    if arch.cwd:
        logging.debug("CWD: %s", arch.cwd)

    # Alimentamos stdin con prompt + comando de salida para que el loop termine
    stdin_payload = prompt_text.rstrip() + "\n" + EXIT_COMMAND + "\n"

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=build_env(arch),
            cwd=arch.cwd,
        )
        timed_out = False
    except subprocess.TimeoutExpired as e:
        proc = None
        timed_out = True
        stdout = (e.stdout or "") if hasattr(e, "stdout") else ""
        stderr = (e.stderr or "") if hasattr(e, "stderr") else ""
    t1 = time.perf_counter()

    if proc is not None:
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        returncode = proc.returncode
    else:
        returncode = None

    answer = extract_senpai_answer(stdout)
    logging.info(
        "Run end arch=%s prompt=%s cid=%s rc=%s timed_out=%s latency=%.3fs",
        arch.id,
        prompt_id,
        cid,
        returncode,
        timed_out,
        t1 - t0,
    )

    # Guardar artefactos
    (run_dir / "cmd.json").write_text(json.dumps(cmd, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "stdin.txt").write_text(stdin_payload, encoding="utf-8")
    (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8", errors="ignore")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8", errors="ignore")
    (run_dir / "answer.txt").write_text(answer, encoding="utf-8", errors="ignore")

    result = {
        "run_id": run_id,
        "arch_id": arch.id,
        "prompt_id": prompt_id,
        "cid": cid,
        "timeout_s": timeout_s,
        "timed_out": timed_out,
        "returncode": returncode,
        "latency_s": round(t1 - t0, 6),
        "answer": answer,
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
        "answer_chars": len(answer),
        "run_dir": str(run_dir),
    }
    return result

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

    archs = load_architectures(str(pathlib.Path(__file__).parent / "configs" / "architectures.json"))
    prompts = load_prompts_jsonl(str(pathlib.Path(__file__).parent / "configs" / "prompts.jsonl"))

    timeout_s = 60
    # CID base para ir incrementando y asegurar unicidad si tu sistema espera int.
    cid_counter = 1000

    # Limpia results.jsonl si quieres empezar de cero
    # RESULTS_PATH.unlink(missing_ok=True)

    for arch in archs:
        logging.info("Architecture start id=%s", arch.id)
        for p in prompts:
            cid_counter += 1
            res = run_one(
                arch=arch,
                prompt_id=p["id"],
                prompt_text=p["text"],
                cid=cid_counter,
                timeout_s=timeout_s,
            )
            append_jsonl(RESULTS_PATH, res)
            logging.info(
                "[OK] %s %s latency=%.3fs timed_out=%s",
                res["arch_id"],
                res["prompt_id"],
                res["latency_s"],
                res["timed_out"],
            )
        logging.info("Architecture end id=%s", arch.id)

if __name__ == "__main__":
    main()
