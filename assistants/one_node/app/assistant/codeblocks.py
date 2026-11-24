"""Utilities for extracting and segmenting code blocks from LLM outputs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List

import yaml

_CODE_BLOCK_PATTERN = re.compile(
    r"```(?P<info>[^\n\r]*)\r?\n(?P<body>.*?)(?:\r?\n)?```",
    re.DOTALL,
)


@dataclass(slots=True)
class CodeBlock:
    """Represents a fenced code block extracted from text."""

    language: str | None
    content: str
    start: int
    end: int

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the block."""
        return {
            "language": self.language,
            "content": self.content,
            "start": self.start,
            "end": self.end,
        }


@dataclass(slots=True)
class YamlDocument:
    """Represents a YAML document extracted from a code block."""

    text: str
    start: int
    end: int
    data: Any

    def to_payload(self) -> dict[str, Any]:
        """Return the document segment as a serialisable payload."""
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
        }


def extract_code_blocks(text: str | None) -> List[CodeBlock]:
    """Extract Markdown fenced code blocks from the provided text."""
    if not text:
        return []

    blocks: List[CodeBlock] = []

    for match in _CODE_BLOCK_PATTERN.finditer(text):
        info = match.group("info") or ""
        language = info.strip() or None
        body = match.group("body") or ""
        content = body.rstrip("\r\n")
        start, end = match.span()
        blocks.append(CodeBlock(language=language, content=content, start=start, end=end))

    return blocks


def split_yaml_documents(content: str) -> List[YamlDocument]:
    """Split ``content`` into YAML documents, preserving text and offsets."""
    if not content.strip():
        return []

    try:
        nodes = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
        data_items = list(yaml.safe_load_all(content))
    except yaml.YAMLError:
        return [YamlDocument(text=content, start=0, end=len(content), data=None)]

    documents: List[YamlDocument] = []
    for node, data in zip(nodes, data_items, strict=False):
        start = node.start_mark.index
        end = node.end_mark.index
        text = content[start:end]
        documents.append(YamlDocument(text=text, start=start, end=end, data=data))

    if not documents:
        return [YamlDocument(text=content, start=0, end=len(content), data=None)]

    return documents


__all__ = ["CodeBlock", "YamlDocument", "extract_code_blocks", "split_yaml_documents"]
