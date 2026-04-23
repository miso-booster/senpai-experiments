import os
import re
import json
import uuid
import sys
import time
import logging
import threading
import subprocess
import pathlib

from typing import Dict, Any
from app.architecture import Architecture
from app.setup_configuration import build_cmd, build_env, parse_env_file
from app.fallback_detector import detect_fallback
from app.yaml_validation import validate_answer_yaml


EXIT_COMMAND = "exit"


def extract_senpai_answer(stdout: str) -> str:
    """
    Extrae texto entre delimitadores $$$ ... $$$.
    """
    block_re = re.compile(r"(?s)\$\$\$\s*(.*?)\s*\$\$\$")
    blocks = [b.strip() for b in block_re.findall(stdout) if b.strip()]
    if blocks:
        return "\\n\\n".join(blocks).strip()
    return stdout.strip()


def count_fenced_code_lines(text: str) -> int:
    """
    Count lines inside Markdown fenced code blocks delimited by triple backticks.
    Fence marker lines themselves are excluded.
    """
    total_lines = 0
    in_fence = False
    for line in text.splitlines():
        stripped_left = line.lstrip()
        if not in_fence and stripped_left.startswith("```"):
            in_fence = True
            continue
        if in_fence and stripped_left.startswith("```"):
            in_fence = False
            continue
        if in_fence:
            total_lines += 1
    return total_lines


def count_words(text: str) -> int:
    """Count words in free text using whitespace tokenization."""
    return len(text.split())


def extract_conversation_id(stdout: str) -> str | None:
    """Extract conversation ID printed by Senpai main."""
    match = re.search(r"conversation ID:\s*([A-Za-z0-9_-]+)", stdout)
    if not match:
        return None
    return match.group(1)


def run_one(
        arch: Architecture,
        prompt_id: str,
        prompt_text: str,
        sensei_project: str,
        prompt_type: str,
        timeout_s: int,
        run_group_id: str,
        verbose: bool,
        runs_root_dir: pathlib.Path,
        model_label: str | None = None,
        model_slug: str = "",
) -> Dict[str, Any]:
    run_id = f"{arch.id}__{prompt_id}__{sensei_project}__{prompt_type}__{uuid.uuid4().hex[:8]}"
    run_dir = runs_root_dir / run_group_id / "run_register" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_cmd(arch, sensei_project, prompt_text, verbose, run_id)
    run_env = build_env(arch, run_group_id, model_label=model_label)
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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=run_env,
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
            logging.warning(f"Process timed out: {run_id}")
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
    answer_code_lines = count_fenced_code_lines(answer)
    answer_word_count = count_words(answer)
    conversation_id = extract_conversation_id(stdout)
    # Load only OPENAI_API_KEY from env file into os.environ for fallback detection.
    if arch.env_file and "OPENAI_API_KEY" not in os.environ:
        try:
            env_from_file = parse_env_file(arch.env_file)
            api_key = env_from_file.get("OPENAI_API_KEY")
            if api_key:
                os.environ["OPENAI_API_KEY"] = api_key
        except FileNotFoundError:
            logging.warning("Env file not found for fallback detection: %s", arch.env_file)
    fallback = detect_fallback(prompt_text, answer)
    is_yaml_valid = validate_answer_yaml(prompt_type, answer)
    logging.info(
        "Run end arch=%s prompt=%s rc=%s timed_out=%s latency=%.3fs",
        arch.id,
        prompt_id,
        returncode,
        timed_out,
        t1 - t0,
    )

    # Save artifacts
    (run_dir / "cmd.json").write_text(
        json.dumps(cmd, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (run_dir / "stdin.txt").write_text(stdin_payload, encoding="utf-8")
    (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8", errors="ignore")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8", errors="ignore")
    (run_dir / "answer.txt").write_text(answer, encoding="utf-8", errors="ignore")

    result_json = {
        "run_id": run_id,
        "run_group_id": run_group_id,
        "arch_id": arch.id,
        "prompt_id": prompt_id,
        "prompt": prompt_text,
        "timeout_s": timeout_s,
        "timed_out": timed_out,
        "returncode": returncode,
        "latency_s": round(t1 - t0, 6),
        "answer": answer,
        "fallback": fallback,
        "is_yaml_valid": is_yaml_valid,
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
        "answer_chars": len(answer),
        "answer_word_count": answer_word_count,
        "answer_code_lines": answer_code_lines,
        "llm_call_count": None,
        "total_input_tokens": None,
        "model_label": model_label or "",
        "model_slug": model_slug or "",
        "conversation_id": conversation_id,
        "run_dir": str(run_dir),
    }

    return result_json
