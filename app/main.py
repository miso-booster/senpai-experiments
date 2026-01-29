import json
import os
import re
import time
import uuid
import pathlib
import subprocess
import argparse
import logging
import sys
import threading

from app.setup_configuration import *

from app.architecture import Architecture

from typing import Dict, Any

from app.setup_logger import setup_logging


def extract_senpai_answer(stdout: str) -> str:
    """
    Extrae texto entre delimitadores $$$ ... $$$.
    """
    block_re = re.compile(r"(?s)\$\$\$\s*(.*?)\s*\$\$\$")
    blocks = [b.strip() for b in block_re.findall(stdout) if b.strip()]
    if blocks:
        return "\\n\\n".join(blocks).strip()
    return stdout.strip()


def run_one(
    arch: Architecture,
    prompt_id: str,
    prompt_text: str,
    sensei_project: str,
    prompt_type: str,
    timeout_s: int,
    run_group_id: str,
    verbose: bool
) -> Dict[str, Any]:
    cmd = build_cmd(arch, sensei_project, prompt_text, verbose)
    run_id = f"{arch.id}__{prompt_id}__{sensei_project}__{prompt_type}__{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_group_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.info("Run start arch=%s prompt=%s", arch.id, prompt_id)
    logging.debug("Cmd: %s", cmd)
    if arch.cwd:
        logging.debug("CWD: %s", arch.cwd)

    # Alimentamos stdin con prompt + comando de salida para que el loop termine
    stdin_payload = prompt_text.rstrip() + "\n" + EXIT_COMMAND + "\n"

    t0 = time.perf_counter()
    try:
        proc = subprocess.Popen(
            cmd,
            # stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=build_env(arch),
            cwd=arch.cwd,
        )

        stdout_lines = []
        stderr_lines = []

        def _tee(stream, sink, collector):
            for line in stream:
                collector.append(line)
                sink.write(line)
                sink.flush()

        t_out = threading.Thread(target=_tee, args=(proc.stdout, sys.stdout, stdout_lines), daemon=True)
        t_err = threading.Thread(target=_tee, args=(proc.stderr, sys.stderr, stderr_lines), daemon=True)
        t_out.start()
        t_err.start()

        try:
            proc.wait(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()

        t_out.join(timeout=1)
        t_err.join(timeout=1)

        stdout = "".join(stdout_lines)
        stderr = "".join(stderr_lines)
    except subprocess.TimeoutExpired as e:
        proc = None
        timed_out = True
        stdout = (e.stdout or "") if hasattr(e, "stdout") else ""
        stderr = (e.stderr or "") if hasattr(e, "stderr") else ""
    t1 = time.perf_counter()

    if proc is not None:
        returncode = proc.returncode
    else:
        returncode = None

    answer = extract_senpai_answer(stdout)
    logging.info(
        "Run end arch=%s prompt=%s rc=%s timed_out=%s latency=%.3fs",
        arch.id,
        prompt_id,
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
    now = time.time()
    run_group_id = time.strftime("%Y%m%d_%H%M%S", time.localtime(now)) + f"_{int((now % 1) * 1000):03d}"

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

if __name__ == "__main__":
    main()

