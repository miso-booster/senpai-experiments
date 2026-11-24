"""Tests for the code block extraction utilities."""

from __future__ import annotations

from textwrap import dedent

from app.assistant.codeblocks import extract_code_blocks, split_yaml_documents


def test_extract_code_blocks_detects_multiple_blocks() -> None:
    text = dedent(
        """
        Here is one block:
        ```yaml
        name: sample
        description: Example rule
        conversations: 1
        oracle: True
        ```
        And here is another:
        ```
        plain text block
        ```
        """
    ).strip()

    blocks = extract_code_blocks(text)

    assert len(blocks) == 2
    assert blocks[0].language == "yaml"
    assert "name: sample" in blocks[0].content
    assert blocks[1].language is None
    assert "plain text block" in blocks[1].content


def test_extract_code_blocks_ignores_unclosed_blocks() -> None:
    text = "```yaml\nname: orphan"

    blocks = extract_code_blocks(text)

    assert blocks == []


def test_split_yaml_documents_returns_segments() -> None:
    content = dedent(
        """
        name: hola

        ---

        name: adios
        """
    ).strip()

    documents = split_yaml_documents(content)

    assert len(documents) == 2
    assert documents[0].text.strip() == "name: hola"
    assert documents[1].text.strip() == "name: adios"
    assert documents[0].start == 0
    assert documents[0].end > documents[0].start


def test_split_yaml_documents_handles_invalid_yaml() -> None:
    documents = split_yaml_documents("[unclosed list")

    assert len(documents) == 1
    assert documents[0].data is None
