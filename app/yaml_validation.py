import logging
import re
import textwrap
from typing import Callable, Protocol

from senpai_validators import validate_connector, validate_profile, validate_rule


class ValidationResult(Protocol):
    is_valid: bool
    errors: list[str] | None


ValidatorFn = Callable[[str], ValidationResult]

_VALIDATORS: dict[str, ValidatorFn] = {
    "connector": validate_connector,
    "profile": validate_profile,
    "rule": validate_rule,
}

_MARKDOWN_FENCE_RE = re.compile(
    r"```(?P<lang>[^\n`]*)\n(?P<code>[\s\S]*?)```",
    re.MULTILINE,
)
_YAML_TOP_LEVEL_KEY_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_-]*\s*:", re.MULTILINE)


def _extract_fenced_code_blocks(answer_text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for match in _MARKDOWN_FENCE_RE.finditer(answer_text):
        language = match.group("lang").strip().lower()
        # Markdown fenced code blocks nested under list items often include a
        # shared indentation prefix in the raw text. Dedent before stripping so
        # valid YAML isn't rejected due to preserved list indentation.
        code = textwrap.dedent(match.group("code")).strip()
        if code:
            blocks.append((language, code))
    return blocks


def _extract_unfenced_yaml_candidates(answer_text: str) -> list[str]:
    cleaned = answer_text.strip()
    if not cleaned:
        return []

    lines = cleaned.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if _YAML_TOP_LEVEL_KEY_RE.match(line):
            start_idx = idx
            break

    if start_idx is None:
        return []

    candidates: list[str] = [cleaned]
    candidate_start = lines[start_idx:]
    candidates.append("\n".join(candidate_start).strip())

    # If the assistant added prose after YAML, try truncating at blank-line boundaries.
    boundary_indices = {len(candidate_start)}
    for idx, line in enumerate(candidate_start, start=1):
        if not line.strip():
            boundary_indices.add(idx)

    for boundary in sorted(boundary_indices, reverse=True):
        if boundary <= 1:
            continue
        snippet = "\n".join(candidate_start[:boundary]).strip()
        if snippet:
            candidates.append(snippet)

    return candidates


def _build_validation_candidates(answer_text: str) -> list[str]:
    blocks = _extract_fenced_code_blocks(answer_text)

    if blocks:
        yaml_blocks = [code for lang, code in blocks if lang in {"yaml", "yml"}]
        maybe_yaml_blocks = [
            code for lang, code in blocks
            if lang not in {"yaml", "yml"} and _YAML_TOP_LEVEL_KEY_RE.search(code)
        ]
        ordered_candidates = yaml_blocks + maybe_yaml_blocks
    else:
        ordered_candidates = _extract_unfenced_yaml_candidates(answer_text)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in ordered_candidates:
        cleaned = candidate.strip()
        if cleaned and cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)
    return deduped


def validate_answer_yaml_status(prompt_type: str, answer_text: str) -> str | None:
    """Return detailed YAML validation status for a prompt answer.

    Returns:
    - "valid": YAML was found and passed validation.
    - "invalid": YAML was found but failed validation.
    - "no_yaml": this prompt type is YAML-validated, but no YAML was found.
    - None: this prompt type has no registered YAML validator.
    """
    validator = _VALIDATORS.get((prompt_type or "").strip().lower())
    if validator is None:
        return None

    candidates = _build_validation_candidates(answer_text)
    if not candidates:
        return "no_yaml"

    collected_errors: list[str] = []
    for candidate in candidates:
        try:
            result = validator(candidate)
        except Exception as exc:
            collected_errors.append(f"{type(exc).__name__}: {exc}")
            logging.debug(
                "YAML validator raised for prompt_type=%s: %s: %s",
                prompt_type,
                type(exc).__name__,
                exc,
            )
            continue
        if result.is_valid:
            return "valid"
        if result.errors:
            collected_errors.extend(result.errors)

    if collected_errors:
        logging.debug(
            "YAML validation failed for prompt_type=%s with errors: %s",
            prompt_type,
            collected_errors[:5],
        )
    return "invalid"


def validate_answer_yaml(prompt_type: str, answer_text: str) -> bool | None:
    """Return YAML validity for supported prompt types.

    Returns:
    - True: YAML was found and validated successfully.
    - False: YAML was found but is invalid.
    - None: prompt type is unsupported or no YAML was found.
    """
    status = validate_answer_yaml_status(prompt_type, answer_text)
    if status is None or status == "no_yaml":
        return None
    if status == "valid":
        return True
    return False
