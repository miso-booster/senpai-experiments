"""Utilities for building and maintaining the project-level embeddings index."""

import logging
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from app.embeddings.get_embedding import get_embedding, get_embeddings_batch
from app.embeddings.hashing import hash_text
from app.embeddings.manage_embeddings import get_index_path, load_index, save_index
from app.embeddings.search_content import find_project_files, get_files_state
from app.embeddings.types import _FILE_TYPES, FileType

EmbeddingIndex = dict[FileType, dict[str, object]]

logger = logging.getLogger(__name__)


FloatArray = NDArray[np.floating[Any]]


def _normalize_embeddings(embeddings: FloatArray) -> FloatArray:
    """Normalize embedding vectors to unit length for efficient cosine similarity.

    Pre-normalizing embeddings during index build avoids redundant normalization
    during each search query.

    Args:
        embeddings: Matrix of shape (N, D) containing embedding vectors.

    Returns:
        Normalized embeddings matrix of the same shape.
    """
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    # Avoid division by zero for zero vectors
    norms = np.where(norms == 0, 1.0, norms)
    return cast(FloatArray, embeddings / norms)


def _get_embedding_content(files: list[Path]) -> dict[str, Any]:
    """Build embedding records, vectors, and file state for a list of YAML files.

    This produces a dict with:
      - records: filename/path/yaml_text entries for each file
      - embeddings: a pre-normalized matrix for cosine similarity
      - file_state: mapping of file paths to mtimes and content hashes plus filenames

    For empty inputs, a single dummy embedding is created and file_state is
    still present with empty structures so downstream logic is consistent.

    Args:
        files: List of YAML file paths to embed.

    Returns:
        Dict containing records, embeddings, and file_state for the given files.
    """
    records: list[dict[str, str]] = []
    contents_by_path: dict[str, str] = {}
    texts_to_embed: list[str] = []

    if files:
        for path in files:
            yaml_file_text = path.read_text(encoding="utf-8")
            records.append(
                {
                    "filename": path.name,
                    "path": str(path),
                    "yaml_text": yaml_file_text,
                }
            )
            contents_by_path[str(path)] = yaml_file_text
            texts_to_embed.append(yaml_file_text)
        # Use batch embedding for better performance
        embeddings_matrix = get_embeddings_batch(texts_to_embed)
    else:
        embeddings_matrix = get_embedding("").reshape(1, -1)

    # Pre-normalize embeddings for efficient cosine similarity during search
    embeddings_matrix = _normalize_embeddings(embeddings_matrix)
    files_state = get_files_state(files, contents_by_path=contents_by_path)

    return {
        "records": records,
        "embeddings": embeddings_matrix,
        "file_state": files_state,
    }


def _get_index_file_types(root_dir: Path) -> tuple[FileType, ...]:
    """Return the file types stored under the given root.

    For project roots, this includes profiles and rules. For the connectors
    directory, only connectors are indexed.

    Args:
        root_dir: Root directory of the project or connectors folder.

    Returns:
        Tuple of file types to index under the root.
    """
    if root_dir.name == "connectors":
        return ("connectors",)
    return tuple(x for x in _FILE_TYPES if x != "connectors")


def _build_index_content(root_dir: Path, file_types: tuple[FileType, ...]) -> EmbeddingIndex:
    """Build embedding content for the requested file types.

    Args:
        root_dir: Root directory of the project or connectors folder.
        file_types: File types to index under the root.

    Returns:
        Dict keyed by file type containing records/embeddings/file_state.
    """
    embedding_content: EmbeddingIndex = {}
    for f_type in file_types:
        project_files = find_project_files(root_dir, file_type=f_type)
        embedding_content[f_type] = _get_embedding_content(project_files)
    return embedding_content


def _refresh_index_content(
    root_dir: Path,
    file_type: FileType,
    existing_data: dict[str, Any] | None,
) -> dict[str, object]:
    """Refresh embedding content for a single file type, reusing unchanged files.

    Args:
        root_dir: Root directory of the project or connectors folder.
        file_type: File type to refresh.
        existing_data: Previously stored embedding data for the file type.

    Returns:
        Dict containing updated records, embeddings, and file_state.
    """
    current_files = find_project_files(root_dir, file_type=file_type)

    if not existing_data:
        return _get_embedding_content(current_files)

    old_state = existing_data.get("file_state", {}).get("state", {})
    old_records = existing_data.get("records", [])
    old_embeddings = existing_data.get("embeddings")

    if not isinstance(old_state, dict) or old_embeddings is None or not isinstance(old_records, list):
        return _get_embedding_content(current_files)

    record_by_path: dict[str, dict[str, Any]] = {}
    index_by_path: dict[str, int] = {}
    for idx, record in enumerate(old_records):
        if not isinstance(record, dict):
            continue
        path_str = record.get("path")
        if not isinstance(path_str, str) or not path_str:
            continue
        record_by_path[path_str] = record
        index_by_path[path_str] = idx

    vectors: list[FloatArray] = []
    records: list[dict[str, Any]] = []
    file_state: dict[str, dict[str, Any]] = {}
    filenames: list[str] = []

    for path in current_files:
        path_str = str(path)
        filenames.append(path.name)
        current_mtime = path.stat().st_mtime
        record = record_by_path.get(path_str)
        record_index = index_by_path.get(path_str)

        old_entry = old_state.get(path_str)
        old_mtime: float | None = None
        old_hash: str | None = None
        if isinstance(old_entry, dict):
            old_mtime = old_entry.get("mtime")
            old_hash = old_entry.get("hash")

        content: str | None = None
        content_hash: str | None = None
        reuse_record = False

        if record is not None and record_index is not None and old_mtime is not None:
            if abs(old_mtime - current_mtime) <= 1e-6:
                reuse_record = True
            else:
                content = path.read_text(encoding="utf-8")
                content_hash = hash_text(content)
                if old_hash is not None and content_hash == old_hash:
                    reuse_record = True
                elif record.get("yaml_text") == content:
                    reuse_record = True

        if reuse_record:
            if content_hash is None and isinstance(old_hash, str):
                content_hash = old_hash
            if content_hash is None:
                content = path.read_text(encoding="utf-8")
                content_hash = hash_text(content)
            if content is not None and record.get("yaml_text") != content:
                reuse_record = False
            else:
                try:
                    vectors.append(old_embeddings[record_index])
                    records.append(record)
                    file_state[path_str] = {"mtime": current_mtime, "hash": content_hash}
                    continue
                except Exception:  # noqa: BLE001
                    # Fallback to rebuilding this entry if lookup fails.
                    pass

        if content is None:
            content = path.read_text(encoding="utf-8")
            content_hash = hash_text(content)

        emb = get_embedding(content)
        records.append(
            {
                "filename": path.name,
                "path": path_str,
                "yaml_text": content,
            }
        )
        vectors.append(emb)
        file_state[path_str] = {"mtime": current_mtime, "hash": content_hash}

    if not vectors:
        vectors.append(get_embedding(""))

    embeddings_matrix = np.vstack(vectors)
    embeddings_matrix = _normalize_embeddings(embeddings_matrix)

    return {
        "records": records,
        "embeddings": embeddings_matrix,
        "file_state": {"state": file_state, "files": filenames},
    }


def _build_index(root_dir: Path) -> Path:
    """Build the embeddings index for all YAML files under the root and save it.

    Args:
        root_dir: Root directory of the project or connectors folder.

    Returns:
        Path to the saved embeddings index.
    """
    file_types = _get_index_file_types(root_dir)
    embedding_content = _build_index_content(root_dir, file_types)
    return save_index(root_dir, embedding_content)


def _is_file_type_stale(root_dir: Path, project_embedding: EmbeddingIndex, file_type: FileType) -> bool:
    """Determine whether a stored file-type index is out of date.

    A file type is stale when:
      - files were added or removed, or
      - any file mtime has changed.

    Args:
        root_dir: Root directory of the project or connectors folder.
        project_embedding: Loaded embeddings index data.
        file_type: File type to check for staleness.

    Returns:
        True if the file type needs rebuilding; False otherwise.
    """
    file_group = cast(dict[str, Any], project_embedding[file_type])
    current_files = find_project_files(root_dir, file_type)
    file_state = file_group.get("file_state")
    if not isinstance(file_state, dict):
        return True
    old_state = file_state.get("state")
    if not isinstance(old_state, dict):
        return True
    # Quick check: if file counts differ, index is definitely stale
    if len(current_files) != len(old_state):
        return True
    # Check for new or modified files
    for path in current_files:
        path_str = str(path)
        current_mtime = path.stat().st_mtime
        old_entry = old_state.get(path_str)
        if old_entry is None:
            # New file (shouldn't happen if lengths match, but be defensive)
            return True
        if isinstance(old_entry, dict):
            old_mtime = old_entry.get("mtime")
            if not isinstance(old_mtime, (int, float)):
                return True
            if abs(old_mtime - current_mtime) > 1e-6:
                # Different mtime -> refresh to verify content hash
                return True
        else:
            return True
    return False


def _get_stale_file_types(root_dir: Path, project_embedding: EmbeddingIndex) -> set[FileType]:
    """Return the file types that need to be rebuilt for the given root.

    If the stored index is missing expected keys or has incompatible shape,
    the corresponding file type is treated as stale.

    Args:
        root_dir: Root directory of the project or connectors folder.
        project_embedding: Loaded embeddings index data.

    Returns:
        Set of file types that should be rebuilt.
    """
    file_types = _get_index_file_types(root_dir)
    stale: set[FileType] = set()
    for file_type in file_types:
        try:
            if _is_file_type_stale(root_dir, project_embedding, file_type):
                stale.add(file_type)
        except (KeyError, TypeError):
            stale.add(file_type)
    return stale


def get_or_build_index(root_dir: Path) -> Path:
    """Load the embeddings index if it exists and is up to date; otherwise build it.

    Behavior:
    - If an index exists:
        - attempt to load it and retrieve its stored file state,
        - check which file types are stale compared to the current files,
        - rebuild only the stale sections and persist the merged index.
    - If an index does not exist:
        - build a new index from the current project profiles.

    Args:
        root_dir (Path): Root directory of the project or connectors folder.

    Returns:
        Path: Path to the embeddings index file.
    """
    index_path = get_index_path(root_dir)
    file_types = _get_index_file_types(root_dir)
    file_types_label = ", ".join(file_types)
    if index_path.exists():
        # Try to load and check if there are any changes
        try:
            embedding = cast(EmbeddingIndex, load_index(index_path))
            # Has anything changed in the project?
            stale_types = _get_stale_file_types(root_dir, embedding)
            if stale_types:
                refreshed: EmbeddingIndex = {}
                for file_type in sorted(stale_types):
                    refreshed[file_type] = _refresh_index_content(
                        root_dir,
                        file_type,
                        embedding.get(file_type),
                    )
                embedding.update(refreshed)
                embedding_path = save_index(root_dir, embedding)
                joined = ", ".join(sorted(stale_types))
                logger.warning("Embedding index stale for: %s. Rebuilding sections.", joined)
            else:
                embedding_path = get_index_path(root_dir)
                logger.info("Embedding index up to date (%s): %s", file_types_label, embedding_path)
        except Exception as exc:
            # Corrupt / unexpected format -> rebuild
            logger.error(
                "Embedding index load failed: %s. Rebuilding full index (%s).",
                exc,
                file_types_label,
            )
            embedding_path = _build_index(root_dir)

    else:
        # No index exists -> build it
        embedding_path = _build_index(root_dir)
        logger.info("Building new embedding index (%s).", file_types_label)

    return embedding_path
