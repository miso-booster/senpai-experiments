"""Classification utilities for YAML code blocks produced by the assistant."""

from __future__ import annotations

from collections.abc import Mapping as ABCMapping
from dataclasses import dataclass
from typing import Iterable, List, Literal, Mapping, Sequence, TypedDict

from app.assistant.codeblocks import YamlDocument, extract_code_blocks, split_yaml_documents

SnippetKind = Literal["rule", "profile", "connector", "unknown", "error"]
CodeBlockKind = Literal["rule", "profile", "connector", "unknown", "error"]

_MIN_SCORE = 1

_RULE_WEIGHTS: Mapping[str, int] = {
    "name": 1,
    "description": 1,
    "conversations": 3,
    "oracle": 3,
    "if": 3,
    "then": 3,
    "on-error": 2,
    "yields": 2,
    "active": 1,
    "when": 2,
}

_PROFILE_WEIGHTS: Mapping[str, int] = {
    "test_name": 4,
    "llm": 3,
    "user": 3,
    "chatbot": 3,
    "conversation": 3,
    "goals": 2,
    "interaction_style": 1,
    "goal_style": 1,
    "output": 1,
    "fallback": 1,
    "types": 1,
    "project_folder": 1,
    "execution_parameters": 1,
}

_CONNECTOR_WEIGHTS: Mapping[str, int] = {
    "name": 1,
    "base_url": 3,
    "send_message": 2,
    "send_message.path": 3,
    "send_message.method": 2,
    "send_message.headers": 2,
    "send_message.payload_template": 4,
    "response_path": 3,
}


@dataclass(frozen=True)
class ClassifierSpec:
    """Generic classifier definition to avoid ad-hoc heuristics per type."""

    kind: SnippetKind
    weights: Mapping[str, int]
    min_score: int = _MIN_SCORE

    def score(self, flat_keys: frozenset[str]) -> int:
        """Return a numeric score; 0 means this classifier should be ignored."""
        return _score_keys(flat_keys, self.weights)


_CLASSIFIERS: tuple[ClassifierSpec, ...] = (
    ClassifierSpec(
        kind="rule",
        weights=_RULE_WEIGHTS,
    ),
    ClassifierSpec(
        kind="profile",
        weights=_PROFILE_WEIGHTS,
    ),
    ClassifierSpec(
        kind="connector",
        weights=_CONNECTOR_WEIGHTS,
    ),
)


@dataclass(slots=True)
class CodeBlockClassification:
    """Structured payload describing how a fenced code block was classified."""

    block_type: CodeBlockKind
    document_types: List[SnippetKind]

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serialisable version of the classification."""
        return {
            "block_type": self.block_type,
            "document_types": self.document_types,
        }


def classify_code_block(content: str) -> CodeBlockClassification:
    """Split `content` into YAML documents and classify each one."""
    documents = split_yaml_documents(content)
    return classify_documents(documents)


def classify_documents(documents: Sequence[object]) -> CodeBlockClassification:
    """Classify a collection of YAML documents (raw or `YamlDocument`)."""
    raw_documents = list(documents)

    if not raw_documents:
        return CodeBlockClassification("unknown", [])

    if len(raw_documents) > 1:
        return CodeBlockClassification("error", ["error"] * len(raw_documents))

    document_types: List[SnippetKind] = [_classify_document(document) for document in raw_documents]

    known_types = {doc_type for doc_type in document_types if doc_type != "unknown"}
    block_type: CodeBlockKind = next(iter(known_types)) if known_types else "unknown"

    return CodeBlockClassification(block_type, document_types)


def split_and_classify_yaml(content: str) -> tuple[CodeBlockClassification, list[str]]:
    """Split YAML content and return its classification plus raw document texts."""
    documents = split_yaml_documents(content)
    classification = classify_documents(documents)
    doc_texts = [doc.text for doc in documents] if documents else []
    return classification, doc_texts


class YamlBlockPayload(TypedDict):
    """Return type for YAML fenced code blocks."""

    language: str | None
    content: str
    block_type: CodeBlockKind
    documents: list[str]


def extract_yaml_blocks(text: str | None) -> list[YamlBlockPayload]:
    """Extract YAML fenced code blocks and return validator-friendly payloads."""
    if not text:
        return []

    blocks: list[YamlBlockPayload] = []
    for block in extract_code_blocks(text):
        language = (block.language or "").lower()
        if language not in {"yaml", "yml"}:
            continue

        classification, doc_texts = split_and_classify_yaml(block.content)
        block_payload: YamlBlockPayload = {
            "language": block.language,
            "content": block.content,
            "block_type": classification.block_type,
            "documents": doc_texts or [block.content],
        }
        blocks.append(block_payload)

    return blocks


def _classify_document(document: object) -> SnippetKind:
    """Classify a single YAML document.

    Uses a small registry of classifier specs to keep heuristics DRY and extendable.
    """
    mapping: ABCMapping[str, object] | None = None
    text: str | None = None

    if isinstance(document, YamlDocument):
        if isinstance(document.data, ABCMapping):
            mapping = document.data
        text = document.text
    elif isinstance(document, ABCMapping):
        mapping = document
    elif isinstance(document, str):
        text = document

    if mapping is not None:
        mapped = _classify_mapping(mapping)
        if mapped != "unknown":
            return mapped

    if text:
        fallback_keys = _extract_keys_from_text(text)
        fallback_kind = _classify_flat_keys(fallback_keys)
        if fallback_kind != "unknown":
            return fallback_kind

    return "unknown"


def _classify_mapping(document: ABCMapping[str, object]) -> SnippetKind:
    """Classify a mapping-based document; fall back to unknown on low scores."""
    flat_keys = _flatten_keys(document)
    best_kind = _classify_flat_keys(flat_keys)
    if best_kind != "unknown":
        return best_kind

    # Some snippets are wrapped under a single key (e.g. "<name>: {oracle: ...}").
    # Try unwrapping that layer so we still classify them correctly.
    if len(document) == 1:
        ((_, nested_value),) = document.items()
        if isinstance(nested_value, ABCMapping):
            nested_keys = _flatten_keys(nested_value)
            nested_kind = _classify_flat_keys(nested_keys)
            if nested_kind != "unknown":
                return nested_kind

    return "unknown"


def _flatten_keys(node: ABCMapping[str, object], prefix: tuple[str, ...] = ()) -> frozenset[str]:
    """Return lower-cased dotted paths for all mapping keys."""
    keys: set[str] = set()
    for raw_key, value in node.items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip().lower()
        if not key:
            continue
        path = prefix + (key,)
        dotted = ".".join(path)
        keys.add(dotted)
        if isinstance(value, ABCMapping):
            keys |= set(_flatten_keys(value, path))
    return frozenset(keys)


def _extract_keys_from_text(text: str) -> frozenset[str]:
    """Best-effort extraction of YAML-like keys from raw text when parsing fails."""
    keys: set[str] = set()
    stack: list[tuple[int, str]] = []

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip()
        if stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(stripped)
        if stripped.startswith("-"):
            # Treat list items as one indent level deeper so nested keys become dotted.
            stripped = stripped[1:].lstrip()
            indent += 1

        if ":" not in stripped:
            continue

        key_part = stripped.split(":", 1)[0].strip().strip("\"'`")
        if not key_part:
            continue

        key = key_part.lower()

        while stack and indent <= stack[-1][0]:
            stack.pop()

        path = [k for _, k in stack] + [key]
        dotted = ".".join(path)
        keys.add(key)
        keys.add(dotted)
        stack.append((indent, key))

    return frozenset(keys)


def _score_keys(keys: Iterable[str], score_table: Mapping[str, int]) -> int:
    """Score the flattened keys using the provided weight table.

    Uses set intersection to efficiently identify matching keys,
    avoiding unnecessary iteration over the entire score table.
    """
    if isinstance(keys, frozenset):
        # Fast path: use frozenset.intersection which is more efficient
        # as it directly iterates the smaller set
        matching_keys = keys.intersection(score_table)
        return sum(score_table[key] for key in matching_keys)
    # Fallback for non-frozenset iterables
    return sum(score for key, score in score_table.items() if key in keys)


def _classify_flat_keys(flat_keys: frozenset[str]) -> SnippetKind:
    """Return the best-matching snippet kind for the given flattened keys."""
    if not flat_keys:
        return "unknown"

    best_kind: SnippetKind = "unknown"
    best_score = 0
    for spec in _CLASSIFIERS:
        score = spec.score(flat_keys)
        if score > best_score and score >= spec.min_score:
            best_kind = spec.kind
            best_score = score

    return best_kind


__all__ = [
    "CodeBlockClassification",
    "CodeBlockKind",
    "SnippetKind",
    "YamlBlockPayload",
    "classify_code_block",
    "classify_documents",
    "split_and_classify_yaml",
    "extract_yaml_blocks",
]
