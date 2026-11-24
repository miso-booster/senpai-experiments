"""Utilities for building and maintaining the project-level embeddings index."""

from pathlib import Path

import numpy as np

from app.config import config
from app.embeddings.embedding_utils import FilesState, load_yaml_file, profile_to_text
from app.embeddings.get_embedding import get_embedding
from app.embeddings.manage_embeddings import get_index_path, load_index, save_index
from app.embeddings.search_profiles import find_profile_files, get_files_state

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _build_profiles_index(project_dir: Path) -> Path:
    """Build the embeddings index for all YAML profiles in the project and save it.

    This function:
    - scans the project for YAML profile files,
    - computes embeddings for each profile,
    - builds the records list and embeddings matrix,
    - computes the file state,
    - and saves everything to disk.

    Args:
        project_dir (Path): Root directory of the project to scan for profiles.

    Returns:
        Path: Path to the saved embeddings index.

    Raises:
        ValueError: If no YAML profiles are found within project_dir.
    """
    profile_files = find_profile_files(project_dir)

    if not profile_files:
        raise ValueError(f"No YAML profiles were found in {project_dir}")

    records = []
    vectors = []

    for path in profile_files:
        profile_yaml = load_yaml_file(path)
        text = profile_to_text(profile_yaml, path.name)
        emb = get_embedding(text)  # np.ndarray

        records.append(
            {
                "filename": path.name,
                "path": str(path),
                "profile": profile_yaml,  # parsed YAML profile
                "text": text,
            }
        )
        vectors.append(emb)

    embeddings_matrix = np.vstack(vectors)
    files_state = get_files_state(profile_files)

    embedding_path = save_index(project_dir, records, embeddings_matrix, files_state)
    return embedding_path


def _is_index_stale(project_dir: Path, old_files_state: FilesState) -> bool:
    """Determine whether a stored index is out of date relative to the current project files.

    The index is considered stale if:
    - there are new files,
    - any file has a different modification time (mtime),
    - or there are files in the old state that no longer exist.

    Args:
        project_dir (Path): Root directory of the project to scan for current profiles.
        old_files_state (Dict[str, object]): Previous file-state dictionary as returned
            by get_files_state (containing the "profile_state" key).

    Returns:
        bool: True if the index is stale and should be rebuilt, False otherwise.
    """
    current_files = find_profile_files(project_dir)
    current_state = get_files_state(current_files)["profile_state"]
    old_state = old_files_state["profile_state"]

    # 1) New or modified files
    for path_str, mtime in current_state.items():
        if path_str not in old_state:
            # New file
            return True
        if not np.isclose(old_state[path_str], mtime):
            # Different mtime -> modified
            return True

    # 2) Deleted files
    for path_str in old_state.keys():
        if path_str not in current_state:
            return True

    return False


def get_or_build_index(project_dir: str | Path) -> Path:
    """Load the project embeddings index if it exists and is up to date; otherwise build it.

    Behavior:
    - If an index exists:
        - attempt to load it and retrieve its stored file state,
        - check if the index is stale compared to the current project files,
        - rebuild the index if it is stale.
    - If an index does not exist:
        - build a new index from the current project profiles.

    Args:
        project_dir (str | Path): Root directory of the project.

    Returns:
        Path: Path to the embeddings index file.
    """
    if isinstance(project_dir, str):
        project_dir = Path(project_dir)

    index_path = get_index_path(project_dir)
    if index_path.exists():
        # Try to load and check if there are any changes
        try:
            _, _, files_state = load_index(index_path)
            # Has anything changed in the project?
            if _is_index_stale(project_dir, files_state):
                # Rebuild
                embedding_path = _build_profiles_index(project_dir)
                if config.VERBOSE:
                    print("[get-or-build-index] Project embedding is stale. Re-building project embedding")
            else:
                embedding_path = get_index_path(project_dir)
                if config.VERBOSE:
                    print(f"[get-or-build-index] Retrieving project embedding from database {embedding_path}")
        except Exception as e:
            # Corrupt / unexpected format -> rebuild
            if config.VERBOSE:
                print(f"[get-or-build-index] Error: {e}. Re-building project embedding")
            embedding_path = _build_profiles_index(project_dir)

    else:
        # No index exists -> build it
        embedding_path = _build_profiles_index(project_dir)
        if config.VERBOSE:
            print("[get-or-build-index] Building new project embedding.")

    return embedding_path
