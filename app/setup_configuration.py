import os
import re
import json
import pathlib
import logging
import string


from typing import Any, List, Dict
from app.architecture import Architecture


# Comando de salida del chat. Cambia si tu CLI usa otro (por ej. "exit", "/quit", etc.)
EXIT_COMMAND = "exit"

OUT_DIR = pathlib.Path(__file__).parent.parent / "out"
RUNS_DIR = OUT_DIR / "runs"
RESULTS_PATH = OUT_DIR / "results.jsonl"

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
    if not model_label:
        return RUNS_DIR / experiment_dirname
    return RUNS_DIR / sanitize_path_component(model_label) / experiment_dirname


def resolve_model_output_dir(base_dir: pathlib.Path, model_label: str | None = None) -> pathlib.Path:
    if not model_label:
        return base_dir
    return base_dir / sanitize_path_component(model_label)


def load_architecture_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Architecture config must be a JSON object: {path}")
    return data


def load_default_model_label(path: str) -> str | None:
    data = load_architecture_config(path)
    value = data.get("model_label")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_object(name: str, value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Architecture config field '{name}' must be a JSON object.")
    return value


def _format_string_template(template: str, context: Dict[str, Any], *, field_name: str) -> str:
    formatter = string.Formatter()
    referenced_keys = [name for _, name, _, _ in formatter.parse(template) if name]
    missing = sorted({key for key in referenced_keys if key not in context or context[key] is None})
    if missing:
        raise ValueError(
            f"Missing template values for field '{field_name}': {', '.join(missing)}"
        )
    return template.format_map(context)


def _render_config_value(value: Any, context: Dict[str, Any], *, field_name: str) -> Any:
    if isinstance(value, str):
        return _format_string_template(value, context, field_name=field_name)
    if isinstance(value, list):
        return [
            _render_config_value(item, context, field_name=field_name)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _render_config_value(item, context, field_name=f"{field_name}.{key}")
            for key, item in value.items()
        }
    return value


def load_architectures(path: str) -> List[Architecture]:
    data = load_architecture_config(path)
    variables = _validate_object("variables", data.get("variables"))
    defaults = _validate_object("defaults", data.get("defaults"))
    archs = []
    for a in data["architectures"]:
        if not isinstance(a, dict):
            raise ValueError("Each architecture entry must be a JSON object.")
        merged: Dict[str, Any] = dict(defaults)
        merged.update(a)
        merged_context: Dict[str, Any] = dict(variables)
        merged_context.update(merged)

        resolved_cwd = _render_config_value(merged.get("cwd"), merged_context, field_name="cwd")
        if resolved_cwd is not None:
            merged_context["cwd"] = resolved_cwd
        resolved_cmd = _render_config_value(merged.get("cmd"), merged_context, field_name="cmd")
        resolved_env = _render_config_value(merged.get("env"), merged_context, field_name="env")
        resolved_env_file = _render_config_value(
            merged.get("env_file"),
            merged_context,
            field_name="env_file",
        )

        archs.append(
            Architecture(
                id=str(merged["id"]),
                cmd=resolved_cmd,
                cwd=resolved_cwd,
                env=resolved_env,
                env_file=resolved_env_file,
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
