"""Functions for locating profile files and searching them via embedding similarity."""

from pathlib import Path
from typing import Any, List, cast

import numpy as np

from app.embeddings.embedding_utils import FilesState
from app.embeddings.get_embedding import get_embedding
from app.embeddings.manage_embeddings import load_index


def find_profile_files(project_dir: Path) -> List[Path]:
    """Recursively search for all .yaml / .yml files inside the project.

    If you want to limit the search (e.g., only inside project_dir / 'profiles'),
    adjust the logic here.

    Args:
        project_dir (Path): Root directory of the project.

    Returns:
        List[Path]: List of paths to YAML profile files.
    """
    profiles_dir = project_dir / "profiles"
    return [p for p in profiles_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".yaml", ".yml")]


def get_files_state(files: List[Path]) -> FilesState:
    """Returns a dictionary describing the current file-state structure.

    The returned dictionary has the form:
    {
        "profile_state": {path_str: mtime_float},
        "profiles": [file_names]
    }

    Args:
        files (List[Path]): List of profile file paths.

    Returns:
        Dict[str, object]: Dictionary containing profile modification times
        and filenames.
    """
    profile_state = {}
    profiles = []

    for f in files:
        profile_state[str(f)] = f.stat().st_mtime
        profiles.append(f.name)  # file name without extension

    return {"profile_state": profile_state, "profiles": profiles}


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between a single vector and a matrix of vectors.

    Args:
        a (np.ndarray): Vector of shape (D,).
        b (np.ndarray): Matrix of shape (N, D).

    Returns:
        np.ndarray: Array of similarities of shape (N,).
    """
    a_norm = a / np.linalg.norm(a)
    b_norm = b / np.linalg.norm(b, axis=1, keepdims=True)
    return cast(np.ndarray, np.dot(b_norm, a_norm))


def search_profiles(query: str, embedding_path: Path, top_k: int = 3, state: bool = False) -> dict[str, Any]:
    """Returns the top_k profiles most similar to the query.

    Args:
        query (str): Search query text.
        embedding_path (Path): Path to the embeddings index.
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
    """
    records, embeddings_matrix, file_state = load_index(embedding_path)

    query_emb = get_embedding(query)
    sims = cosine_similarity(query_emb, embeddings_matrix)  # (N,)

    # Indices sorted from highest to lowest similarity
    idx_sorted = np.argsort(sims)[::-1][:top_k]

    results = []
    for idx in idx_sorted:
        rec = records[idx]
        results.append(
            {
                "score": float(sims[idx]),
                **rec,  # filename, path, profile, text
            }
        )

    project_state = file_state if state else None

    output = {"results": results, "project_state": project_state}

    return output
