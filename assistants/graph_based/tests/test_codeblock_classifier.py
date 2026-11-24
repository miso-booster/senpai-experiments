"""Tests for classifying Sensei code blocks."""

from __future__ import annotations

from textwrap import dedent

import pytest

from app.assistant.codeblock_classifier import classify_code_block


def test_classify_rule_block_detects_rules() -> None:
    content = dedent(
        """
        name: toppings_monotonicity
        description: More toppings increases price
        conversations: 2
        when: conv[0].size == conv[1].size
        oracle: extract_float(conv[0].price) <= extract_float(conv[1].price)
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "rule"
    assert classification.document_types == ["rule"]


def test_classify_profile_block_detects_profiles() -> None:
    content = dedent(
        """
        test_name: rental_car_quote_smoke
        llm:
          model: gpt-4o
        user:
          language: English
        chatbot:
          is_starter: false
        conversation:
          number: 1
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "profile"
    assert classification.document_types == ["profile"]


def test_classify_connector_block_detects_connectors() -> None:
    content = dedent(
        """
        name: my_connector
        base_url: https://example.com
        send_message:
          path: /api/messages
          method: POST
          payload_template:
            text: "{user_msg}"
        response_path: messages.0.content
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "connector"
    assert classification.document_types == ["connector"]


def test_classify_block_with_multiple_documents() -> None:
    content = dedent(
        """
        name: rule_one
        description: First rule
        oracle: True

        ---

        name: rule_two
        description: Second rule
        oracle: False
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "error"
    assert classification.document_types == ["error", "error"]


def test_classify_block_with_mixed_documents_returns_error() -> None:
    content = dedent(
        """
        name: rule_one
        description: First rule
        oracle: True

        ---

        test_name: example_profile
        user:
          language: Spanish
        conversation:
          number: 1
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "error"
    assert classification.document_types == ["error", "error"]


@pytest.mark.parametrize(
    ("snippet", "expected_documents"),
    [
        ("", []),
        ("some text that is not yaml: :::", ["unknown"]),
        ("12345", ["unknown"]),
    ],
)
def test_classify_unknown_content(snippet: str, expected_documents: list[str]) -> None:
    classification = classify_code_block(snippet)

    assert classification.block_type == "unknown"
    assert classification.document_types == expected_documents
