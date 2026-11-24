"""Script for loading the project context."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal, overload

import yaml

log = logging.getLogger(__name__)

YAML_EXTENSIONS = {".yaml", ".yml"}


class SenseiProjectError(ValueError):
    """Raised when a project path is missing the expected Sensei structure."""


@dataclass(frozen=True)
class ProjectContextStats:
    """Metadata describing the parsed project context."""

    root: Path | None
    profiles: tuple[Path, ...]
    rules: tuple[Path, ...]


@dataclass(frozen=True)
class UserContextStats:
    """Metadata describing the parsed user context."""

    root: Path | None
    files: tuple[Path, ...]


def _iter_yaml_files(folder: Path) -> Iterator[Path]:
    for file in sorted(folder.iterdir()):
        if file.is_file() and file.suffix.lower() in YAML_EXTENSIONS:
            yield file


def _load_yaml(folder: Path) -> tuple[list[object], list[Path]]:
    """Load all YAML files from a given folder into a list of dictionaries.

    Args:
        folder: Folder containing YAML files to load.

    Returns:
        tuple[list, list]: Parsed YAML objects and the originating file paths.
    """
    yaml_list: list[object] = []
    files: list[Path] = []
    for file in _iter_yaml_files(folder):
        raw_text = file.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            data = {"__raw_text__": raw_text, "__parse_error__": str(exc)}
        else:
            if not isinstance(data, dict):
                data = {
                    "__raw_text__": raw_text,
                    "__parse_error__": "YAML file must contain a mapping at the top level",
                }
        yaml_list.append(data)
        files.append(file)

    return yaml_list, files


def _flatten_yaml_list(yaml_list: Iterable[object]) -> str:
    """Convert a list of YAML objects into a single formatted YAML string."""
    return "\n---\n".join(yaml.dump(y, sort_keys=True, default_flow_style=True) for y in yaml_list)


def _iter_yaml_files_recursive(folder: Path) -> Iterator[Path]:
    for file in sorted(folder.rglob("*")):
        if not file.is_file():
            continue
        if file.suffix.lower() in YAML_EXTENSIONS:
            yield file


def _resolve_user_context_root(root: Path) -> Path:
    """Prefer the connectors subtree when a full user folder is provided."""
    connectors_root = root / "connectors"
    if connectors_root.is_dir():
        return connectors_root
    return root


def _build_structure_lines(root: Path, files: Iterable[Path]) -> list[str]:
    """Build a stable, human-readable structure summary for prompt injection."""
    structure_entries: set[str] = set()
    for file in files:
        relative_file = file.relative_to(root).as_posix()
        structure_entries.add(relative_file)

        current = file.parent
        while current != root:
            structure_entries.add(f"{current.relative_to(root).as_posix()}/")
            current = current.parent

    return sorted(structure_entries)


@overload
def parse_project_context(
    project_path: Path | str = "",
    *,
    include_stats: Literal[False] = False,
) -> str: ...


@overload
def parse_project_context(
    project_path: Path | str = "",
    *,
    include_stats: Literal[True],
) -> tuple[str, ProjectContextStats]: ...


def parse_project_context(
    project_path: Path | str = "",
    *,
    include_stats: bool = False,
) -> str | tuple[str, ProjectContextStats]:
    """Load and flatten YAML data from a project's profiles and rules directories."""
    if not project_path:
        empty_stats = ProjectContextStats(root=None, profiles=tuple(), rules=tuple())
        return ("", empty_stats) if include_stats else ""

    root = Path(project_path) if isinstance(project_path, str) else project_path
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Sensei project path does not exist: {root}")

    required_folders = {"profiles": root / "profiles", "rules": root / "rules"}
    missing = [name for name, folder in required_folders.items() if not folder.is_dir()]
    if missing:
        raise SenseiProjectError(f"Sensei project at {root} is missing required folders: {', '.join(sorted(missing))}")

    sections: list[str] = []
    profile_docs, profile_files = _load_yaml(required_folders["profiles"])
    rule_docs, rule_files = _load_yaml(required_folders["rules"])

    if not profile_docs and not rule_docs:
        raise SenseiProjectError(
            f"No YAML files found under {required_folders['profiles']} or {required_folders['rules']}."
        )

    if profile_docs:
        sections.append(_flatten_yaml_list(profile_docs))
    if rule_docs:
        sections.append(_flatten_yaml_list(rule_docs))

    context = "\n---\n".join(sections)
    stats = ProjectContextStats(
        root=root,
        profiles=tuple(profile_files),
        rules=tuple(rule_files),
    )

    if include_stats:
        return context, stats
    return context


@overload
def parse_user_context(
    user_path: Path | str = "",
    *,
    include_stats: Literal[False] = False,
) -> str: ...


@overload
def parse_user_context(
    user_path: Path | str = "",
    *,
    include_stats: Literal[True],
) -> tuple[str, UserContextStats]: ...


def parse_user_context(
    user_path: Path | str = "",
    *,
    include_stats: bool = False,
) -> str | tuple[str, UserContextStats]:
    """Load and flatten YAML files from a user directory."""
    if not user_path:
        empty_stats = UserContextStats(root=None, files=tuple())
        return ("", empty_stats) if include_stats else ""

    root = Path(user_path) if isinstance(user_path, str) else user_path
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"User folder path does not exist: {root}")

    context_root = _resolve_user_context_root(root)
    sections: list[str] = []
    files: list[Path] = []
    for file in _iter_yaml_files_recursive(context_root):
        try:
            content = file.read_text(encoding="utf-8").strip()
        except (PermissionError, UnicodeDecodeError) as exc:
            content = f"(Unable to read file: {exc})"
        if not content:
            continue
        relative_path = file.relative_to(root).as_posix()
        sections.append(f"### {relative_path}\n{content}")
        files.append(file)

    if not sections:
        raise SenseiProjectError(f"No readable YAML files found under user folder {root}.")

    context = "\n\n".join(sections)
    stats = UserContextStats(root=root, files=tuple(files))
    if include_stats:
        return context, stats
    return context


def format_project_context_for_prompt(
    raw_context: str,
    stats: ProjectContextStats | None = None,
) -> str:
    """Add guidance and metadata around the raw YAML project context."""
    raw_context = raw_context.strip()
    if not raw_context:
        return ""

    header_lines = [
        "### User Project Context",
        (
            "The following YAML documents come directly from the user's Sensei project. "
            "Treat them as ground truth when answering questions about their profiles and rules."
        ),
    ]

    if stats:
        if stats.root:
            header_lines.append(f"Project root: {stats.root}")
        profile_list = ", ".join(file.name for file in stats.profiles) or "none"
        rule_list = ", ".join(file.name for file in stats.rules) or "none"
        header_lines.append(f"Profile files: {profile_list}")
        header_lines.append(f"Rule files: {rule_list}")
        if stats.root:
            structure_lines = _build_structure_lines(stats.root, [*stats.profiles, *stats.rules])
            if structure_lines:
                header_lines.append("Project structure:")
                header_lines.extend(structure_lines)

    header_lines.append(raw_context)
    return "\n".join(header_lines)


def format_user_context_for_prompt(
    raw_context: str,
    stats: UserContextStats | None = None,
) -> str:
    """Add guidance and metadata around the raw user context."""
    raw_context = raw_context.strip()
    if not raw_context:
        return ""

    header_lines = [
        "### User Folder Context",
        (
            "The following files come directly from the user's selected user folder. "
            "Treat them as ground truth when answering questions about user-specific connectors or configuration."
        ),
    ]

    if stats:
        if stats.root:
            header_lines.append(f"User root: {stats.root}")
        file_list = ", ".join(file.name for file in stats.files) or "none"
        header_lines.append(f"User files: {file_list}")
        if stats.root:
            structure_lines = _build_structure_lines(stats.root, stats.files)
            if structure_lines:
                header_lines.append("User structure:")
                header_lines.extend(structure_lines)

    header_lines.append(raw_context)
    return "\n".join(header_lines)


def resolve_project_context(
    messages: Sequence[object], project_path: Path | str | None = None, state: bool = False
) -> str:
    """Return the full project context formatted for prompt injection."""
    del messages, state
    if project_path:
        raw_context, stats = parse_project_context(project_path, include_stats=True)
        return format_project_context_for_prompt(raw_context, stats)
    return ""


def resolve_user_context(messages: Sequence[object], user_path: Path | str | None = None, state: bool = False) -> str:
    """Return the full user-folder context formatted for prompt injection."""
    del messages, state
    if user_path:
        raw_context, stats = parse_user_context(user_path, include_stats=True)
        return format_user_context_for_prompt(raw_context, stats)
    return ""
