"""Helpers for loading project and user prompt context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal, overload

import yaml

YAML_EXTENSIONS = {".yaml", ".yml"}


class SenseiProjectError(ValueError):
    """Raised when a path is missing the expected Sensei structure."""


@dataclass(frozen=True)
class ContextEntry:
    """A single YAML document and the metadata needed to render it in prompts."""

    name: str
    path: Path
    content: str


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
    connectors_root: Path | None
    connectors: tuple[Path, ...]


PromptContextMap = dict[str, str]


def _iter_yaml_files(folder: Path) -> Iterator[Path]:
    for file in sorted(folder.iterdir()):
        if file.is_file() and file.suffix.lower() in YAML_EXTENSIONS:
            yield file


def _render_yaml_item(item: object) -> str:
    if isinstance(item, str):
        return item.rstrip()
    return yaml.dump(item, sort_keys=True, default_flow_style=True).rstrip()


def _load_yaml(folder: Path) -> tuple[list[object], list[Path]]:
    """Load all YAML files from a given folder."""
    yaml_list: list[object] = []
    files: list[Path] = []
    for file in _iter_yaml_files(folder):
        raw_text = file.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            error_line = str(exc).splitlines()[0].strip()
            header = [
                f"# INVALID YAML (failed to parse): {file.name}",
                f"# Error: {error_line}",
            ]
            data = "\n".join(header + ["", raw_text.rstrip()])
        yaml_list.append(data)
        files.append(file)

    return yaml_list, files


def _flatten_yaml_list(yaml_list: Iterable[object]) -> str:
    """Convert a list of YAML objects into a single formatted YAML string."""
    parts = [_render_yaml_item(item) for item in yaml_list]
    return "\n---\n".join(parts)


def _resolve_existing_directory(path_value: Path | str, *, label: str) -> Path:
    root = Path(path_value) if isinstance(path_value, str) else path_value
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"{label} path does not exist: {root}")
    return root


def _extract_entry_name(item: object, file: Path, *, preferred_fields: tuple[str, ...]) -> str:
    if isinstance(item, dict):
        for field in preferred_fields:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return file.stem


def _build_context_entries(
    documents: Iterable[object],
    files: Iterable[Path],
    *,
    preferred_fields: tuple[str, ...],
) -> tuple[ContextEntry, ...]:
    return tuple(
        ContextEntry(
            name=_extract_entry_name(document, file, preferred_fields=preferred_fields),
            path=file,
            content=_render_yaml_item(document),
        )
        for document, file in zip(documents, files, strict=True)
    )


def _load_project_entries(
    project_path: Path | str = "",
) -> tuple[tuple[ContextEntry, ...], tuple[ContextEntry, ...], ProjectContextStats]:
    if not project_path:
        return tuple(), tuple(), ProjectContextStats(root=None, profiles=tuple(), rules=tuple())

    root = _resolve_existing_directory(project_path, label="Sensei project")
    required_folders = {"profiles": root / "profiles", "rules": root / "rules"}
    missing = [name for name, folder in required_folders.items() if not folder.is_dir()]
    if missing:
        raise SenseiProjectError(f"Sensei project at {root} is missing required folders: {', '.join(sorted(missing))}")

    profile_docs, profile_files = _load_yaml(required_folders["profiles"])
    rule_docs, rule_files = _load_yaml(required_folders["rules"])

    if not profile_docs and not rule_docs:
        raise SenseiProjectError(
            f"No YAML files found under {required_folders['profiles']} or {required_folders['rules']}."
        )

    stats = ProjectContextStats(root=root, profiles=tuple(profile_files), rules=tuple(rule_files))
    profile_entries = _build_context_entries(profile_docs, profile_files, preferred_fields=("test_name", "name"))
    rule_entries = _build_context_entries(rule_docs, rule_files, preferred_fields=("name", "test_name"))
    return profile_entries, rule_entries, stats


def _resolve_connectors_folder(root: Path) -> Path:
    connectors_folder = root / "connectors"
    if connectors_folder.is_dir():
        return connectors_folder
    return root


def _load_user_entries(user_path: Path | str = "") -> tuple[tuple[ContextEntry, ...], UserContextStats]:
    if not user_path:
        return tuple(), UserContextStats(root=None, connectors_root=None, connectors=tuple())

    root = _resolve_existing_directory(user_path, label="User")
    connectors_root = _resolve_connectors_folder(root)
    connector_docs, connector_files = _load_yaml(connectors_root)

    if not connector_docs:
        raise SenseiProjectError(f"No connector YAML files found under {connectors_root}.")

    stats = UserContextStats(
        root=root,
        connectors_root=connectors_root,
        connectors=tuple(connector_files),
    )
    connector_entries = _build_context_entries(connector_docs, connector_files, preferred_fields=("name", "test_name"))
    return connector_entries, stats


def _join_entry_contents(entries: Iterable[ContextEntry]) -> str:
    return "\n---\n".join(entry.content for entry in entries)


def _format_section_prompt(
    *,
    title: str,
    description: str,
    metadata_lines: Iterable[str],
    names_label: str,
    files_label: str,
    entries: Iterable[ContextEntry],
) -> str:
    entries = tuple(entries)
    if not entries:
        return ""

    lines = [title, description]
    lines.extend(metadata_lines)
    lines.append(f"{names_label}: {', '.join(entry.name for entry in entries) or 'none'}")
    lines.append(f"{files_label}: {', '.join(entry.path.name for entry in entries) or 'none'}")
    lines.append("")

    for index, entry in enumerate(entries):
        lines.append(f"# Source: {entry.path.name}")
        lines.append(entry.content)
        if index < len(entries) - 1:
            lines.append("---")

    return "\n".join(lines)


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
    profile_entries, rule_entries, stats = _load_project_entries(project_path)
    context = _join_entry_contents((*profile_entries, *rule_entries))
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
    """Load and flatten YAML data from a user's connector folder."""
    connector_entries, stats = _load_user_entries(user_path)
    context = _join_entry_contents(connector_entries)
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

    header_lines.append(raw_context)
    return "\n".join(header_lines)


def build_prompt_contexts(
    project_path: Path | str = "",
    user_path: Path | str = "",
) -> tuple[PromptContextMap, ProjectContextStats, UserContextStats]:
    """Build per-intent prompt context blocks from project and user paths."""
    profile_entries, rule_entries, project_stats = _load_project_entries(project_path)
    connector_entries, user_stats = _load_user_entries(user_path)

    project_root_line = [f"Project root: {project_stats.root}"] if project_stats.root else []
    connector_metadata: list[str] = []
    if user_stats.root:
        connector_metadata.append(f"User path: {user_stats.root}")
    if user_stats.connectors_root and user_stats.connectors_root != user_stats.root:
        connector_metadata.append(f"Connectors folder: {user_stats.connectors_root}")

    profile_context = _format_section_prompt(
        title="### User Profile Context",
        description=(
            "The following profile YAML documents come directly from the user's Sensei project. "
            "Review the available profile names first, then use the full YAML bodies as ground truth."
        ),
        metadata_lines=project_root_line,
        names_label="Profile names",
        files_label="Profile files",
        entries=profile_entries,
    )
    rule_context = _format_section_prompt(
        title="### User Rule Context",
        description=(
            "The following rule YAML documents come directly from the user's Sensei project. "
            "Review the available rule names first, then use the full YAML bodies as ground truth."
        ),
        metadata_lines=project_root_line,
        names_label="Rule names",
        files_label="Rule files",
        entries=rule_entries,
    )
    connector_context = _format_section_prompt(
        title="### User Connector Context",
        description=(
            "The following connector YAML documents come directly from the user's connector folder. "
            "Review the available connector names first, then use the full YAML bodies as ground truth."
        ),
        metadata_lines=connector_metadata,
        names_label="Connector names",
        files_label="Connector files",
        entries=connector_entries,
    )

    explain_parts = [part for part in (profile_context, rule_context, connector_context) if part]
    prompt_contexts: PromptContextMap = {
        "profile": profile_context,
        "rule": rule_context,
        "connector": connector_context,
        "explain": "\n\n".join(explain_parts),
    }
    return prompt_contexts, project_stats, user_stats


def resolve_project_context(project_context: Path | str | None = "") -> str:
    """Return a flattened project context when given a directory path."""
    if project_context in ("", None):
        return ""
    if isinstance(project_context, Path):
        raw_context, stats = parse_project_context(project_context, include_stats=True)
        return format_project_context_for_prompt(raw_context, stats)
    project_context = str(project_context)
    candidate = Path(project_context)
    try:
        if candidate.exists() and candidate.is_dir():
            raw_context, stats = parse_project_context(candidate, include_stats=True)
            return format_project_context_for_prompt(raw_context, stats)
    except OSError:
        return project_context
    return project_context
