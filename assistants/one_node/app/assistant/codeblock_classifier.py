"""Classification utilities for YAML code blocks produced by the assistant."""

from __future__ import annotations

from collections.abc import Mapping as ABCMapping
from dataclasses import dataclass
from typing import Iterable, List, Literal, Mapping, Sequence

from app.assistant.codeblocks import YamlDocument, split_yaml_documents

SnippetKind = Literal["rule", "profile", "unknown", "error"]
CodeBlockKind = Literal["rule", "profile", "unknown", "error"]

_RULE_STRONG_KEYS: frozenset[str] = frozenset({"oracle", "if", "then", "conversations"})
_PROFILE_STRONG_KEYS: frozenset[str] = frozenset({"test_name", "llm", "user", "chatbot"})

_RULE_SCORE: Mapping[str, int] = {
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

_PROFILE_SCORE: Mapping[str, int] = {
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

    parsed_documents: List[object] = []
    for document in raw_documents:
        if isinstance(document, YamlDocument):
            parsed_documents.append(document.data)
        else:
            parsed_documents.append(document)

    document_types: List[SnippetKind] = [_classify_document(document) for document in parsed_documents]

    known_types = {doc_type for doc_type in document_types if doc_type != "unknown"}
    if not known_types:
        block_type: CodeBlockKind = "unknown"
    elif len(known_types) == 1:
        block_type = next(iter(known_types))
    else:
        block_type = "error"

    return CodeBlockClassification(block_type, document_types)


def _classify_document(document: object) -> SnippetKind:
    """Classify a single YAML document.

    The heuristic analyzes the shape of the YAML:
      * rules: `name` + `description` + (oracle / conversations / if-then),
      * profiles: dominant keys like `test_name`, `llm`, `user`, `chatbot`,
      * in ambiguous cases, uses scoring based on `_RULE_SCORE` and `_PROFILE_SCORE`.
    """
    if not isinstance(document, ABCMapping):
        return "unknown"

    keys = _normalise_keys(document)
    if not keys:
        return "unknown"

    if {"name", "description"} <= keys and (
        "oracle" in keys or "conversations" in keys or "if" in keys or "then" in keys
    ):
        return "rule"

    if "test_name" in keys:
        return "profile"

    rule_strong = bool(keys & _RULE_STRONG_KEYS)
    profile_strong = bool(keys & _PROFILE_STRONG_KEYS)

    rule_score = _score_keys(keys, document, _RULE_SCORE)
    profile_score = _score_keys(keys, document, _PROFILE_SCORE)

    if rule_strong and not profile_strong:
        return "rule"
    if profile_strong and not rule_strong:
        return "profile"

    if rule_score == profile_score == 0:
        return "unknown"

    # Bias towards the larger score when there is no tie
    if rule_score > profile_score and rule_score >= 2:
        return "rule"
    if profile_score > rule_score and profile_score >= 2:
        return "profile"

    return "unknown"


def _normalise_keys(document: ABCMapping[str, object]) -> frozenset[str]:
    """Return a lower-cased snapshot of the string keys present in the document."""
    return frozenset(str(key).strip().lower() for key in document.keys() if isinstance(key, str))


def _score_keys(keys: Iterable[str], document: ABCMapping[str, object], score_table: Mapping[str, int]) -> int:
    """Score the document keys using the provided scoring table."""
    score = 0
    for key in keys:
        base_score = score_table.get(key, 0)
        if base_score:
            score += base_score

    # Increase confidence when the key maps to a structured object (common in profiles).
    if "user" in score_table and "user" in keys and isinstance(document.get("user"), ABCMapping):
        score += 1
    if "chatbot" in score_table and "chatbot" in keys and isinstance(document.get("chatbot"), ABCMapping):
        score += 1
    if (
        "conversation" in score_table
        and "conversation" in keys
        and isinstance(document.get("conversation"), ABCMapping)
    ):
        score += 1

    return score


__all__ = [
    "CodeBlockClassification",
    "CodeBlockKind",
    "SnippetKind",
    "classify_code_block",
    "classify_documents",
]
