"""Shared types and constants for embedding utilities."""

from typing import Dict, List, Literal, TypedDict, get_args

FileType = Literal["profiles", "rules", "connectors"]
_FILE_TYPES: tuple[FileType, ...] = get_args(FileType)


class FileStateEntry(TypedDict):
    """Represents the tracked state for a single file."""

    mtime: float
    hash: str


class FilesState(TypedDict):
    """Represents the on-disk state of project files."""

    state: Dict[str, FileStateEntry]
    files: List[str]
