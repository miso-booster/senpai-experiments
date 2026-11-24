"""Utility tools exposed to the agent."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.assistant.docs_metadata import DOC_METADATA, SENSEI_DOC_TYPES
from app.assistant.status_messages import register_tool_status
from app.embeddings.embedding_build import get_or_build_index
from app.embeddings.search_content import search_files

YAML_EXTENSIONS = {".yaml", ".yml"}
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _list_yaml_files(folder: Path) -> list[str]:
    """Return sorted YAML filenames within a folder."""
    if not folder.exists():
        return [f"Directory not found: {folder}"]
    if not folder.is_dir():
        return [f"Not a directory: {folder}"]

    return sorted(file.name for file in folder.iterdir() if file.is_file() and file.suffix.lower() in YAML_EXTENSIONS)


def _read_yaml_file(folder: Path, filename: str) -> str:
    """Read a YAML file from a folder while preventing path traversal."""
    safe_name = Path(filename).name
    target = (folder / safe_name).resolve()

    try:
        folder_resolved = folder.resolve()
    except OSError:
        folder_resolved = folder

    if not target.is_relative_to(folder_resolved):
        return f"Invalid path: {filename}"

    if not target.exists():
        return f"File not found: {target}"
    if not target.is_file():
        return f"Not a file: {target}"
    if target.suffix.lower() not in YAML_EXTENSIONS:
        return f"Unsupported file type: {target.suffix}"

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Unable to decode file: {target}"
    except OSError as exc:  # pragma: no cover - defensive guard
        return f"Error reading file {target}: {exc}"


def _write_yaml_file(folder: Path, filename: str, content: str, *, overwrite: bool = False) -> dict[str, str]:
    """Write a YAML file to a folder while preventing path traversal.

    Args:
        folder: Destination directory for the YAML file.
        filename: YAML filename to write within the folder.
        content: YAML payload to persist (written with a trailing newline).
        overwrite: Allow replacing an existing file when True.

    Returns:
        Dict containing either:
        - {"error": "..."} on validation or write failure, or
        - {"status": "created" | "overwritten", "filename": "<name>"} on success.
    """
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        return {"error": "Invalid filename."}

    if not folder.exists():
        return {"error": f"Directory not found: {folder}"}
    if not folder.is_dir():
        return {"error": f"Not a directory: {folder}"}

    target = (folder / safe_name).resolve()

    try:
        folder_resolved = folder.resolve()
    except OSError:
        folder_resolved = folder

    if not target.is_relative_to(folder_resolved):
        return {"error": f"Invalid path: {filename}"}

    if target.suffix.lower() not in YAML_EXTENSIONS:
        suffix = target.suffix or "(none)"
        return {"error": f"Unsupported file type: {suffix}"}

    if not content or not content.strip():
        return {"error": "Content is empty."}

    existed = target.exists()
    if existed and not overwrite:
        return {"error": f"File already exists: {target.name}. Set overwrite=True to replace it."}

    try:
        payload = content.rstrip() + "\n"
        target.write_text(payload, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - defensive guard
        return {"error": f"Error writing file {target}: {exc}"}

    status = "overwritten" if existed else "created"
    return {"status": status, "filename": target.name}


def _delete_yaml_file(folder: Path, filename: str) -> dict[str, str]:
    """Delete a YAML file from a folder while preventing path traversal.

    Args:
        folder: Directory containing the YAML file.
        filename: YAML filename to delete within the folder.

    Returns:
        Dict containing either:
        - {"error": "..."} on validation or delete failure, or
        - {"status": "deleted", "filename": "<name>"} on success.
    """
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        return {"error": "Invalid filename."}

    if not folder.exists():
        return {"error": f"Directory not found: {folder}"}
    if not folder.is_dir():
        return {"error": f"Not a directory: {folder}"}

    target = (folder / safe_name).resolve()

    try:
        folder_resolved = folder.resolve()
    except OSError:
        folder_resolved = folder

    if not target.is_relative_to(folder_resolved):
        return {"error": f"Invalid path: {filename}"}

    if target.suffix.lower() not in YAML_EXTENSIONS:
        suffix = target.suffix or "(none)"
        return {"error": f"Unsupported file type: {suffix}"}

    if not target.exists():
        return {"error": f"File not found: {target}"}
    if not target.is_file():
        return {"error": f"Not a file: {target}"}

    try:
        target.unlink()
    except OSError as exc:  # pragma: no cover - defensive guard
        return {"error": f"Error deleting file {target}: {exc}"}

    return {"status": "deleted", "filename": target.name}


def _read_doc(path: Path) -> str:
    """Read a documentation file and return its stripped contents."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:  # pragma: no cover - defensive guard
        return f"(Unable to read {path.name}: {exc})"


@lru_cache(maxsize=1)
def _load_docs() -> tuple[dict[str, str], ...]:
    """Load full documentation files.

    Results are cached to avoid repeated disk I/O when the tool is invoked multiple times.
    Returns a tuple (immutable) so it can be cached by lru_cache.
    """
    docs: list[dict[str, str]] = []
    for name, doc_type in DOC_METADATA:
        path = DOCS_DIR / name
        content = _read_doc(path)
        if content.startswith("(Unable to read"):
            continue
        docs.append(
            {
                "filename": name,
                "content": content,
                "doc_type": doc_type,
            }
        )
    return tuple(docs)


def build_project_tools(
    project_path: Path | None,
    connectors_path: Path | None,
    embedding_path: Path | str | None = None,
    connectors_embedding_path: Path | None = None,
    *,
    include_create_tools: bool = True,
) -> list[BaseTool]:
    """Create assistant tools, adding project-aware utilities when a project path exists."""
    tools: list[BaseTool] = []

    class GetDocsInput(BaseModel):
        """Input schema for loading full documentation files."""

        doc_types: list[str] = Field(
            ...,
            description=(
                "Always call this tool first when working on rules/profiles/connectors. "
                "Provide one or more of: rules, profiles, connectors."
            ),
        )

    @tool(args_schema=GetDocsInput)
    def get_docs(doc_types: list[str]) -> list[dict[str, object]]:
        """Return full documentation files filtered by type. Call this before any other tool or YAML generation for rules/profiles/connectors."""
        normalized = [doc_type.strip().lower() for doc_type in doc_types]
        allowed = SENSEI_DOC_TYPES

        if not normalized:
            return [dict(error="Provide at least one doc_type: rules, profiles, connectors.")]

        invalid = [doc_type for doc_type in normalized if doc_type not in allowed]
        if invalid:
            return [dict(error=f"Invalid doc_type values: {', '.join(sorted(set(invalid)))}.")]

        docs = _load_docs()  # Returns cached tuple
        if not docs:
            return [dict(error="No documentation files available.")]

        requested = set(normalized)

        selected = [doc for doc in docs if doc["doc_type"] in requested]
        if not selected:
            return [dict(error=f"No docs matched '{', '.join(sorted(requested))}'.")]

        return [
            {
                "filename": doc["filename"],
                "content": doc["content"],
                "doc_type": doc["doc_type"],
            }
            for doc in selected
        ]

    register_tool_status(get_docs.name, "Reading docs")
    tools.append(get_docs)

    if project_path:
        profiles_dir = project_path / "profiles"
        rules_dir = project_path / "rules"

        @tool
        def list_profiles() -> list[str]:
            """List YAML profile files (alphabetical) in the project's profiles directory."""
            return _list_yaml_files(profiles_dir)

        @tool
        def list_rules() -> list[str]:
            """List YAML rule files (alphabetical) in the project's rules directory."""
            return _list_yaml_files(rules_dir)

        @tool
        def read_profile(filename: str) -> str:
            """Read a YAML profile file by name from the project's profiles directory.

            Args:
                filename: Profile filename, e.g., 'profile.yml'.
            """
            return _read_yaml_file(profiles_dir, filename)

        @tool
        def read_rule(filename: str) -> str:
            """Read a YAML rule file by name from the project's rules directory.

            Args:
                filename: Rule filename, e.g., 'rule.yml'.
            """
            return _read_yaml_file(rules_dir, filename)

        class SearchProfilesInput(BaseModel):
            """Input for semantic profile search."""

            query: str = Field(description="User request to match against profile embeddings.")
            top_k: int = Field(default=3, description="Maximum number of results to return. Default: 3.")

        class SearchRulesInput(BaseModel):
            """Input for semantic rules search."""

            query: str = Field(description="User request to match against rule embeddings.")
            top_k: int = Field(default=3, description="Maximum number of results to return. Default: 3.")

        @tool(args_schema=SearchProfilesInput)
        def search_project_profiles(query: str, top_k: int = 3) -> list[dict[str, object]]:
            """Semantic search over project profiles using the embeddings index.

            Use when the user asks to find or get a profile.
            """
            results: list[dict[str, object]] = []
            try:
                # Rebuild if the on-disk profiles have changed.
                latest_index = get_or_build_index(project_path)
                output = search_files(query, latest_index, file_types="profiles", top_k=top_k, state=False)
            except Exception as exc:  # noqa: BLE001
                return [dict(error=f"Search failed: {exc}")]

            for item in output.get("results", []):
                filename = item.get("filename", "")
                score = item.get("score", 0.0)
                results.append({"filename": filename, "score": score})
            return results

        @tool(args_schema=SearchRulesInput)
        def search_project_rules(query: str, top_k: int = 3) -> list[dict[str, object]]:
            """Semantic search over project rules using the embeddings index.

            Use when the user asks to find or get a rule.
            """
            results: list[dict[str, object]] = []
            try:
                # Rebuild if the on-disk profiles have changed.
                latest_index = get_or_build_index(project_path)
                output = search_files(query, latest_index, file_types="rules", top_k=top_k, state=False)
            except Exception as exc:  # noqa: BLE001
                return [dict(error=f"Search failed: {exc}")]

            for item in output.get("results", []):
                filename = item.get("filename", "")
                score = item.get("score", 0.0)
                results.append({"filename": filename, "score": score})
            return results

        class SaveProfileInput(BaseModel):
            """Input for saving a profile file to disk."""

            filename: str = Field(description="Profile filename to save, e.g., 'profile.yml'.")
            content: str = Field(description="Full YAML content to persist for the profile.")
            overwrite: bool = Field(default=False, description="Overwrite the file if it already exists.")

        class SaveRuleInput(BaseModel):
            """Input for saving a rule file to disk."""

            filename: str = Field(description="Rule filename to save, e.g., 'rule.yml'.")
            content: str = Field(description="Full YAML content to persist for the rule.")
            overwrite: bool = Field(default=False, description="Overwrite the file if it already exists.")

        class DeleteProfileInput(BaseModel):
            """Input for deleting a profile file."""

            filename: str = Field(description="Profile filename, e.g., 'profile.yml'.")

        class DeleteRuleInput(BaseModel):
            """Input for deleting a rule file."""

            filename: str = Field(description="Rule filename, e.g., 'rule.yml'.")

        @tool(args_schema=SaveProfileInput)
        def save_profile(filename: str, content: str, overwrite: bool = False) -> dict[str, str]:
            """Save a profile YAML file in the project's profiles directory."""
            return _write_yaml_file(profiles_dir, filename, content, overwrite=overwrite)

        @tool(args_schema=SaveRuleInput)
        def save_rule(filename: str, content: str, overwrite: bool = False) -> dict[str, str]:
            """Save a rule YAML file in the project's rules directory."""
            return _write_yaml_file(rules_dir, filename, content, overwrite=overwrite)

        @tool(args_schema=DeleteProfileInput)
        def delete_profile(filename: str) -> dict[str, str]:
            """Delete a profile from the project's profiles directory."""
            return _delete_yaml_file(profiles_dir, filename)

        @tool(args_schema=DeleteRuleInput)
        def delete_rule(filename: str) -> dict[str, str]:
            """Delete a rule from the project's rules directory."""
            return _delete_yaml_file(rules_dir, filename)

        register_tool_status(list_profiles.name, "Reading profiles")
        register_tool_status(list_rules.name, "Reading rules")
        register_tool_status(read_profile.name, "Reading profile")
        register_tool_status(read_rule.name, "Reading rule")
        register_tool_status(search_project_profiles.name, "Searching profiles")
        register_tool_status(search_project_rules.name, "Searching rules")
        register_tool_status(delete_profile.name, "Deleting profile")
        register_tool_status(delete_rule.name, "Deleting rule")

        if include_create_tools:
            register_tool_status(save_profile.name, "Saving profile")
            register_tool_status(save_rule.name, "Saving rule")

        tools.extend(
            [
                list_profiles,
                list_rules,
                read_profile,
                read_rule,
                search_project_profiles,
                search_project_rules,
                delete_profile,
                delete_rule,
            ]
        )

        if include_create_tools:
            tools.extend([save_profile, save_rule])

    if connectors_path:

        @tool
        def list_connectors() -> list[str]:
            """List YAML connector files (alphabetical) in the user's connectors directory."""
            return _list_yaml_files(connectors_path)

        @tool
        def read_connector(filename: str) -> str:
            """Read a YAML connector file by name from the user's connectors directory.

            Args:
                filename: Connector filename, e.g., 'connector.yml'.
            """
            return _read_yaml_file(connectors_path, filename)

        class SearchConnectorsInput(BaseModel):
            """Input for semantic connector search."""

            query: str = Field(description="User request to match against connectors embeddings.")
            top_k: int = Field(default=3, description="Maximum number of results to return. Default: 3.")

        @tool(args_schema=SearchConnectorsInput)
        def search_connectors(query: str, top_k: int = 3) -> list[dict[str, object]]:
            """Semantic search over connector files using the embeddings index.

            Use when the user asks to find or get a connector.
            """
            results: list[dict[str, object]] = []
            try:
                # Rebuild if the on-disk connectors have changed.
                latest_index = get_or_build_index(connectors_path)
                output = search_files(query, latest_index, file_types="connectors", top_k=top_k, state=False)
            except Exception as exc:  # noqa: BLE001
                return [dict(error=f"Search failed: {exc}")]

            for item in output.get("results", []):
                filename = item.get("filename", "")
                score = item.get("score", 0.0)
                results.append({"filename": filename, "score": score})
            return results

        class SaveConnectorInput(BaseModel):
            """Input for saving a connector file to disk."""

            filename: str = Field(description="Connector filename to save, e.g., 'connector.yml'.")
            content: str = Field(description="Full YAML content to persist for the connector.")
            overwrite: bool = Field(default=False, description="Overwrite the file if it already exists.")

        class DeleteConnectorInput(BaseModel):
            """Input for deleting a connector file."""

            filename: str = Field(description="Connector filename, e.g., 'connector.yml'.")

        @tool(args_schema=SaveConnectorInput)
        def save_connector(filename: str, content: str, overwrite: bool = False) -> dict[str, str]:
            """Save a connector YAML file in the user's connectors directory."""
            return _write_yaml_file(connectors_path, filename, content, overwrite=overwrite)

        @tool(args_schema=DeleteConnectorInput)
        def delete_connector(filename: str) -> dict[str, str]:
            """Delete a connector from the user's connectors directory."""
            return _delete_yaml_file(connectors_path, filename)

        register_tool_status(list_connectors.name, "Reading connectors")
        register_tool_status(read_connector.name, "Reading connector")
        register_tool_status(search_connectors.name, "Searching connectors")
        register_tool_status(delete_connector.name, "Deleting connector")

        if include_create_tools:
            register_tool_status(save_connector.name, "Saving connector")

        tools.extend(
            [
                list_connectors,
                read_connector,
                search_connectors,
                delete_connector,
            ]
        )

        if include_create_tools:
            tools.append(save_connector)

    return tools
