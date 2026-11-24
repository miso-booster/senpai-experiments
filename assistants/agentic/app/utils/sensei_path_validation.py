"""Validation helpers for Sensei user and project paths."""

from pathlib import Path
from typing import Literal

_REQUIRED_DIRS = {"project": ["profiles", "rules"], "user": ["connectors"]}


def validate_sensei_path(sensei_path: str | Path, path_type: Literal["user", "project"]) -> Path:
    """Ensure the provided path looks like a Sensei user or project path.

    A valid Sensei user path must be a directory containing at least a 'connectors' subdirectory.
    A valid Sensei project path must be a directory containing `profiles` and `rules`
    subdirectories.
    Raises an exception otherwise.

    Args:
        sensei_path (str | Path): Path to the sensei directory.
        path_type (Literal["user", "project"]): The type of directory being checked.

    Returns:
        Path: Path validated.
    """
    req_dirs = _REQUIRED_DIRS[path_type]

    root = Path(sensei_path).expanduser()

    if not root.exists():
        raise FileNotFoundError(f"SENSEI {path_type} path not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"SENSEI {path_type} path is not a directory: {root}")

    missing = [name for name in req_dirs if not (root / name).is_dir()]
    if missing:
        required = ", ".join(req_dirs)
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Invalid SENSEI {path_type} path at {root}: expected {required}; missing {missing_list}.")

    return root
