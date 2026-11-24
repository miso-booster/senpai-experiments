"""Shared documentation metadata for SENSEI assistant."""

from __future__ import annotations

from typing import Final, Mapping

DOC_METADATA: Final[list[tuple[str, str]]] = [
    ("sensei-check-doc.md", "rules"),
    ("rules-examples.md", "rules"),
    ("sensei-chat-guide.md", "profiles"),
    ("custom-connector-guide.md", "connectors"),
    ("connector-examples.md", "connectors"),
]

SENSEI_DOC_TYPES: Final[frozenset[str]] = frozenset({"rules", "profiles", "connectors"})

DOC_TYPE_BY_BLOCK_TYPE: Final[Mapping[str, str]] = {
    "rule": "rules",
    "profile": "profiles",
    "connector": "connectors",
}
