"""Helpers for saving, loading, and locating project embedding index files."""

import pickle
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from app.embeddings.embedding_utils import FilesState

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
    records: Sequence[Mapping[str, Any]],
    embeddings_matrix: np.ndarray,
    files_state: FilesState,
) -> Path:
    """Save the embeddings index to disk.

    Args:
        project_dir (Path): Project root directory.
        records (list[Dict[str, object]]): List of metadata dictionaries for each profile.
        embeddings_matrix (np.ndarray): Matrix of embeddings with shape (N, D).
        files_state (Dict[str, object]): Dictionary describing file modification times.

    Returns:
        Path: Path to the saved index file.
    """
    index_path = get_index_path(project_dir)

    data = {
        "records": records,
        "embeddings": embeddings_matrix,
        "files_state": files_state,
    }

    with index_path.open("wb") as f:
        pickle.dump(data, f)

    return index_path


def load_index(index_path: Path) -> tuple[Sequence[Mapping[str, Any]], np.ndarray, FilesState]:
    """Load an existing embeddings index from disk.

    Args:
        index_path (Path): Path to the index file (pickle format).

    Returns:
        tuple:
            - records (list): Profile metadata list.
            - embeddings (np.ndarray): Embeddings matrix (N, D).
            - files_state (dict): File state information used for stale detection.

    Raises:
        FileNotFoundError: If the index file does not exist.
    """
    if not index_path.exists():
        raise FileNotFoundError(f"No index found at {index_path}")

    with index_path.open("rb") as f:
        data = pickle.load(f)

    return data["records"], data["embeddings"], data["files_state"]
