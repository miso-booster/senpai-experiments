import json
import os
import re
import time
import uuid
import pathlib
import subprocess
import argparse
import logging

from app.setup_configuration import *

from app.architecture import Architecture

from typing import Dict, Any

from app.setup_logger import setup_logging


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


def run_one(
    arch: Architecture,
    prompt_id: str,
    prompt_text: str,
    sensei_project: str,
    cid: int,
    timeout_s: int,
    run_group_id: str,
) -> Dict[str, Any]:
    cmd = build_cmd(arch, cid, sensei_project)
    run_id = f"{arch.id}__{prompt_id}__{sensei_project}__{cid}__{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_group_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
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
        "run_group_id": run_group_id,
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

    archs = load_architectures(str(pathlib.Path(__file__).parent.parent / "configs" / "architectures.json"))
    prompts = load_prompts_json(str(pathlib.Path(__file__).parent.parent / "configs" / "prompts.json"))

    timeout_s = 60
    # CID base para ir incrementando y asegurar unicidad si tu sistema espera int.
    cid_counter = 1000
    now = time.time()
    run_group_id = time.strftime("%Y%m%d_%H%M%S", time.localtime(now)) + f"_{int((now % 1) * 1000):03d}"

    # Limpia results.jsonl si quieres empezar de cero
    # RESULTS_PATH.unlink(missing_ok=True)

    for arch in archs:
        logging.info("Architecture start id=%s", arch.id)
        for p in prompts:
            cid_counter += 1
            try:
                res = run_one(
                    arch=arch,
                    prompt_id=p["id"],
                    prompt_text=p["text"],
                    sensei_project=p["project"],
                    cid=cid_counter,
                    timeout_s=timeout_s,
                    run_group_id=run_group_id,
                )
                append_jsonl(RESULTS_PATH, res)
                logging.info(
                    "[OK] %s %s latency=%.3fs timed_out=%s",
                    res["arch_id"],
                    res["prompt_id"],
                    res["latency_s"],
                    res["timed_out"],
                )
            except FileNotFoundError as e:
                logging.warning("Skipping prompt_id=%s project=%s: %s", p.get("id"), p.get("project"), e)
        logging.info("Architecture end id=%s", arch.id)

if __name__ == "__main__":
    main()
