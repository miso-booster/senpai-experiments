"""Helpers for saving, loading, and locating project embedding index files."""

import pickle
from pathlib import Path
from typing import Any, Dict, cast

from app.embeddings.types import FileType

SENPAI_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_index_path(project_dir: str | Path) -> Path:
    """Return the path to the project's main embeddings index file.

    The index is stored under:
        SENPAI_PROJECT_ROOT/app/embedding_files/<project_name>/<project_name>.pkl

    Args:
        project_dir (str | Path): Root directory of the project.

    Returns:
        Path: Path to the pickle file that stores the project index.
    """
    if isinstance(project_dir, str):
        project_dir = Path(project_dir)

    project_name = project_dir.name
    embedding_files_dir = SENPAI_PROJECT_ROOT / "app" / "embedding_files" / project_name
    embedding_files_dir.mkdir(parents=True, exist_ok=True)

    return embedding_files_dir / f"{project_name}.pkl"


def save_index(
    project_dir: Path,
    embedding_content: Dict[FileType, dict[str, object]],
) -> Path:
    """Save the embeddings index to disk.

    Args:
        project_dir (Path): Project root directory.
        embedding_content (Dict[str, Any]): Project content embedded

    Returns:
        Path: Path to the saved index file.
    """
    index_path = get_index_path(project_dir)

    with index_path.open("wb") as f:
        pickle.dump(embedding_content, f)

    return index_path


def load_index(index_path: Path) -> Dict[str, Any]:
    """Load an existing embeddings index from disk.

    Args:
        index_path (Path): Path to the index file (pickle format).

    Returns:
        Dict[str, Any]

    Raises:
        FileNotFoundError: If the index file does not exist.
    """
    if not index_path.exists():
        raise FileNotFoundError(f"No index found at {index_path}")

    with index_path.open("rb") as f:
        data = pickle.load(f)

    return cast(Dict[str, Any], data)
