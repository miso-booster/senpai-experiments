"""Functions for locating profile files and searching them via embedding similarity."""

from pathlib import Path
from typing import Any, List, cast

import numpy as np

from app.embeddings.get_embedding import get_embedding
from app.embeddings.hashing import hash_text
from app.embeddings.manage_embeddings import load_index
from app.embeddings.types import _FILE_TYPES, FilesState, FileStateEntry, FileType


def find_project_files(root_dir: Path, file_type: str) -> List[Path]:
    """Recursively search for YAML files inside the project.

    Args:
        root_dir (Path): Root directory of the project or connectors folder.
        file_type (str): Files type to find (profiles/rules/connectors).

    Returns:
        List[Path]: List of YAML file paths for the given type.
    """
    if file_type == "connectors":
        files_dir = root_dir
    elif file_type == "profiles":
        files_dir = root_dir / "profiles"
    elif file_type == "rules":
        files_dir = root_dir / "rules"
    else:
        return []

    return [f for f in files_dir.rglob("*") if f.is_file() and f.suffix.lower() in (".yaml", ".yml")]


def get_files_state(files_list: List[Path], *, contents_by_path: dict[str, str] | None = None) -> FilesState:
    """Returns a dictionary describing the current file-state structure.

    The returned dictionary has the form:
    {
        "state": {path_str: {"mtime": mtime_float, "hash": sha256}},
        "files": [file_names]
    }

    Args:
        files_list (List[Path]): List of file paths for a given type.
        contents_by_path (dict[str, str] | None): Optional preloaded contents keyed by path.

    Returns:
        Dict[str, object]: Dictionary containing modification times and filenames.
    """
    file_state: dict[str, FileStateEntry] = {}
    files = []

    for f in files_list:
        path_str = str(f)
        content = None
        if contents_by_path is not None:
            content = contents_by_path.get(path_str)
        if content is None:
            content = f.read_text(encoding="utf-8")
        file_state[path_str] = {
            "mtime": f.stat().st_mtime,
            "hash": hash_text(content),
        }
        files.append(f.name)  # file name without extension

    return {"state": file_state, "files": files}


def cosine_similarity(a: np.ndarray, b: np.ndarray, b_normalized: bool = True) -> np.ndarray:
    """Compute cosine similarity between a single vector and a matrix of vectors.

    Args:
        a (np.ndarray): Vector of shape (D,).
        b (np.ndarray): Matrix of shape (N, D).
        b_normalized (bool): If True, assumes b is already normalized (default).
            This optimization avoids redundant normalization when embeddings
            are pre-normalized during index build.

    Returns:
        np.ndarray: Array of similarities of shape (N,).
    """
    a_norm = np.linalg.norm(a)
    if a_norm == 0:
        return np.zeros(b.shape[0], dtype=a.dtype)
    a_normalized = a / a_norm

    if b_normalized:
        # Embeddings are pre-normalized during index build, skip redundant normalization
        return cast(np.ndarray, np.dot(b, a_normalized))
    else:
        b_norms = np.linalg.norm(b, axis=1, keepdims=True)
        b_norms = np.where(b_norms == 0, 1, b_norms)
        b_normalized_matrix = b / b_norms
        return cast(np.ndarray, np.dot(b_normalized_matrix, a_normalized))


def search_files(
    query: str, embedding_path: Path, file_types: FileType, top_k: int = 3, state: bool = False
) -> dict[str, Any]:
    """Return the top_k files most similar to the query.

    Args:
        query (str): Search query text.
        embedding_path (Path): Path to the embeddings index.
        file_types (FileType): Type of the files to search (profiles/rules/connectors).
        top_k (int, optional): Number of similar profiles to return. Defaults to 3.
        state (bool, optional): Whether to include project/file state in the output.
                                Defaults to False.

    Returns:
        dict: {
            "results": [
                {
                    "score": float,
                    ...record_fields
                }
            ],
            "project_state": dict | None
        }

    Notes:
        If the index has no records for the requested type, this returns an
        empty results list and optionally the stored file_state.
    """
    if file_types not in _FILE_TYPES:
        raise TypeError(f"Invalid file type: {file_types}")

    index = load_index(embedding_path)
    data = index[file_types]

    if not data["records"]:
        results: list[Any] = []
        project_state = data["file_state"] if state else None
        output = {"results": results, "project_state": project_state}
        return output

    query_emb = get_embedding(query)
    # Embeddings are pre-normalized during index build, so we use b_normalized=True
    sims = cosine_similarity(query_emb, data["embeddings"], b_normalized=True)  # (N,)

    # Use argpartition for O(n) top-k selection instead of O(n log n) full sort
    n_results = min(top_k, len(sims))
    if n_results == len(sims):
        # When requesting all results, use full argsort
        idx_top_k = np.argsort(sims)[::-1]
    else:
        # Use argpartition to efficiently find the top-k indices
        # -sims because argpartition finds smallest, but we want largest
        idx_partitioned = np.argpartition(-sims, n_results - 1)[:n_results]
        # Sort only the top-k indices by their similarity scores
        idx_top_k = idx_partitioned[np.argsort(-sims[idx_partitioned])]

    results = []
    for idx in idx_top_k:
        rec = data["records"][idx]
        results.append(
            {
                "score": float(sims[idx]),
                **rec,  # filename, path, file_content, text
            }
        )

    project_state = data["file_state"] if state else None

    output = {"results": results, "project_state": project_state}

    return output
