from __future__ import annotations

from textwrap import dedent
from typing import Any

import pytest
from senpai_validators import ValidationResult

import app.assistant.validation as validation
from app.assistant.validation import MAX_VALIDATION_ATTEMPTS


def test_validate_code_blocks_skips_unsupported_language() -> None:
    """Skips validation and marks a block when the language is unsupported."""
    blocks = [
        {
            "language": "json",
            "block_type": "rule",
            "documents": [{}],
            "content": '{"foo": "bar"}',
        }
    ]

    result = validation.validate_code_blocks(blocks)

    assert result["needs_retry"] is False
    assert result["validation_attempts"] == 0
    assert result["invalid_snippets"] == []
    assert result["validation_feedback"] is None
    skipped = result["validation_results"][0]
    assert skipped["skipped"] is True
    assert skipped["reason"] == "unsupported_language"
    assert skipped["block_type"] == "rule"


def test_validate_code_blocks_handles_block_errors_and_feedback() -> None:
    """Treats an error-marked block as invalid and surfaces feedback text."""
    blocks = [
        {
            "language": "yaml",
            "block_type": "error",
            "documents": [],
            "error_reason": "syntax explode",
            "content": "bad: [yaml",
        }
    ]

    result = validation.validate_code_blocks(blocks)

    assert result["needs_retry"] is True
    assert result["retry_action"] == "fix_blocks"
    assert result["validation_attempts"] == 1
    invalid = result["invalid_snippets"]
    assert len(invalid) == 1
    snippet = invalid[0]
    assert snippet["block_index"] == 0
    assert snippet["language"] == "yaml"
    assert snippet["block_type"] == "error"
    assert snippet["snippet_kind"] == "block"
    assert snippet["snippet_number"] is None
    assert "syntax explode" in snippet["errors"][0]
    assert any("get_docs tool" in e for e in snippet["errors"])
    assert snippet["warnings"] == []
    feedback = result["validation_feedback"]
    assert isinstance(feedback, str)
    assert "Validation repair summary:" in feedback
    assert "- invalid blocks: 1" in feedback
    assert "- valid blocks: none" in feedback
    assert "- issue: syntax explode" in feedback
    assert "- docs hint:" in feedback


def test_validate_code_blocks_final_failure_context_after_max_attempts() -> None:
    """Stops retrying at the max attempt threshold and returns final failure context."""
    blocks = [
        {
            "language": "yaml",
            "block_type": "rule",
            "documents": [],
            "content": "name: still bad",
        }
    ]

    result = validation.validate_code_blocks(
        blocks,
        attempts_so_far=MAX_VALIDATION_ATTEMPTS - 1,
        intent="create",
    )

    assert result["needs_retry"] is False
    assert result["retry_action"] == "final_failure"
    assert result["validation_attempts"] == MAX_VALIDATION_ATTEMPTS
    assert result["final_failure_context"] == {
        "attempts": MAX_VALIDATION_ATTEMPTS,
        "feedback": result["validation_feedback"],
        "intent": "create",
    }
    feedback = result["validation_feedback"] or ""
    assert "Each code block must contain exactly one YAML document." in feedback
    assert (
        "All blocks are invalid. Rewrite the full reply, keeping the same number of blocks but changing all of them."
        in feedback
    )


def test_validate_code_blocks_unknown_block_gets_hint_and_errors() -> None:
    """Unknown classifier result should surface an error and get_docs hint."""
    blocks = [
        {
            "language": "yaml",
            "block_type": "unknown",
            "documents": [{}],
            "content": "foo: bar",
        }
    ]

    result = validation.validate_code_blocks(blocks)

    assert result["needs_retry"] is True
    assert result["invalid_snippets"][0]["snippet_kind"] == "unknown"
    errors = result["invalid_snippets"][0]["errors"]
    assert any("Could not classify this YAML block" in e for e in errors)
    assert any("intentionally generic" in e for e in errors)
    assert any("one-line" in e or "tiny" in e for e in errors)
    assert any("get_docs tool" in e for e in errors)


def test_validate_code_blocks_uses_profile_and_rule_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delegates to profile/rule validators and propagates their results/feedback."""

    def fake_profile_validator(content: str) -> tuple[dict[str, object], list[dict[str, object]]]:
        block_result = {
            "is_valid": True,
            "errors": [],
            "warnings": ["profile warning"],
            "data": {"content": content},
            "profile": {
                "is_valid": True,
                "errors": [],
                "warnings": ["profile warning"],
                "data": {"content": content},
            },
        }
        return block_result, []

    def fake_rule_validator(content: str) -> tuple[dict[str, object], list[dict[str, object]]]:
        block_result = {
            "is_valid": False,
            "errors": ["bad rule"],
            "warnings": ["rule warn"],
            "data": None,
            "rules": [],
        }
        invalid_entries = [
            {
                "snippet_kind": "rule",
                "snippet_number": 2,
                "errors": ["bad rule"],
                "warnings": ["rule warn"],
            }
        ]
        return block_result, invalid_entries

    monkeypatch.setattr(validation, "_validate_profile_block", fake_profile_validator)
    monkeypatch.setattr(validation, "_validate_rule_block", fake_rule_validator)

    blocks = [
        {"language": "YML", "block_type": "PROFILE", "documents": [{"doc": 1}], "content": "profile-yaml"},
        {"language": "yaml", "block_type": "rule", "documents": [{"doc": 1}], "content": "rule-yaml"},
    ]

    result = validation.validate_code_blocks(blocks)

    first, second = result["validation_results"]
    assert first["block_type"] == "profile"
    assert first["warnings"] == ["profile warning"]
    assert second["block_type"] == "rule"
    assert second["errors"] == ["bad rule"]
    assert result["invalid_snippets"] == [
        {
            "block_index": 1,
            "language": "yaml",
            "block_type": "rule",
            "snippet_kind": "rule",
            "snippet_number": 2,
            "errors": ["bad rule"],
            "warnings": ["rule warn"],
        }
    ]
    assert result["needs_retry"] is True
    feedback = result["validation_feedback"]
    assert isinstance(feedback, str)
    assert "- invalid blocks: 2" in feedback
    assert "- valid blocks: 1" in feedback
    assert "Block 2 (rule 2) (yaml)" in feedback
    assert "- issue: bad rule" in feedback


def test_format_validation_feedback_formats_sections() -> None:
    """Formats invalid snippets into repair-oriented sections with block guidance."""
    invalid: list[dict[str, Any]] = [
        {
            "block_index": 0,
            "language": "yaml",
            "block_type": "rule",
            "snippet_kind": "rule",
            "snippet_number": 1,
            "errors": [
                'Rule is not valid YAML: mapping values are not allowed here\n  in "<unicode string>", line 6, column 29'
            ],
            "warnings": ["unused field"],
        },
        {
            "block_index": 2,
            "language": None,
            "block_type": "profile",
            "snippet_kind": "profile",
            "snippet_number": 3,
            "errors": ["bad profile"],
            "warnings": [],
        },
    ]

    formatted = validation._format_validation_feedback(invalid, total_blocks=3)

    assert "Validation repair summary:" in formatted
    assert "- invalid blocks: 1, 3" in formatted
    assert "- valid blocks: 2" in formatted
    assert "Block 1 (rule 1) (yaml)" in formatted
    assert "- issue: Rule is not valid YAML: mapping values are not allowed here" in formatted
    assert "- warnings: unused field" in formatted
    assert "Block 3 (item 3)" in formatted
    assert "- issue: bad profile" in formatted
    assert "Final instruction:" in formatted
    assert (
        "Keep blocks 2 unchanged. Rewrite the full reply, but only modify blocks 1, 3 and any prose that references them."
        in formatted
    )


def test_format_validation_feedback_surfaces_structured_validator_metadata() -> None:
    """Structured validator metadata should be rendered without assistant-side inference."""
    invalid: list[dict[str, Any]] = [
        {
            "block_index": 1,
            "language": "yaml",
            "block_type": "rule",
            "snippet_kind": "rule",
            "snippet_number": 1,
            "errors": ["Rule is not valid YAML"],
            "warnings": [],
            "error_class": "yaml syntax",
            "line": 5,
            "column": 37,
            "area": "oracle",
            "repair_instruction": "Rewrite the oracle value as valid YAML while preserving its logic.",
        }
    ]

    formatted = validation._format_validation_feedback(invalid, total_blocks=2)

    assert "Block 2 (rule 1) (yaml)" in formatted
    assert "- error class: yaml syntax" in formatted
    assert "- area: oracle" in formatted
    assert "- line: 5" in formatted
    assert "- column: 37" in formatted
    assert "- what to do: Rewrite the oracle value as valid YAML while preserving its logic." in formatted


def test_validate_code_blocks_uses_connector_validator() -> None:
    """Delegates to connector validator and marks block as valid."""
    connector_yaml = dedent(
        """
        base_url: https://api.example.com
        send_message:
          path: /chat
          payload_template:
            message: "{user_msg}"
        response_path: data.message.text
        """
    ).strip()

    result = validation.validate_code_blocks(
        [
            {"language": "yaml", "block_type": "connector", "documents": [{"doc": 1}], "content": connector_yaml},
        ]
    )

    block = result["validation_results"][0]
    assert block["block_type"] == "connector"
    assert block["is_valid"] is True
    assert result["invalid_snippets"] == []
    assert result["needs_retry"] is False


def test_validate_code_blocks_rejects_invalid_connector() -> None:
    """Surface connector validation errors and feedback."""
    connector_yaml = dedent(
        """
        base_url: https://api.example.com
        send_message:
          path: /chat
          payload_template:
            message: "{user_msg}"
        """
    ).strip()  # missing response_path

    result = validation.validate_code_blocks(
        [
            {"language": "yaml", "block_type": "connector", "documents": [{"doc": 1}], "content": connector_yaml},
        ]
    )

    block = result["validation_results"][0]
    assert block["block_type"] == "connector"
    assert block["is_valid"] is False
    assert "Missing required fields" in block["errors"][0]
    invalid = result["invalid_snippets"][0]
    assert invalid["snippet_kind"] == "connector"
    assert invalid["block_index"] == 0
    assert result["needs_retry"] is True


def test_validate_code_blocks_accepts_valid_rule() -> None:
    """Delegates to rule validator and marks block as valid."""
    rule_yaml = dedent(
        """
        name: division
        description: Checks the operation
        active: False
        conversations: 1
        when: operation[0]=='dividing'
        oracle: abs(number1[0]/number2[0] - result) < 1e-03
        yields: |
          f"Wrong result for dividing {number1} and {number2}: expected {number1[0]/number2[0]} but got {result}"
        """
    ).strip()

    result = validation.validate_code_blocks(
        [
            {"language": "yaml", "block_type": "rule", "documents": [{"doc": 1}], "content": rule_yaml},
        ]
    )

    block = result["validation_results"][0]
    assert block["block_type"] == "rule"
    assert block["is_valid"] is True
    assert result["invalid_snippets"] == []
    assert result["needs_retry"] is False


def test_validate_code_blocks_rejects_invalid_rule() -> None:
    """Surface rule validation errors and feedback."""
    invalid_rule = "name: only-name"  # missing required fields

    result = validation.validate_code_blocks(
        [
            {"language": "yaml", "block_type": "rule", "documents": [{"doc": 1}], "content": invalid_rule},
        ]
    )

    block = result["validation_results"][0]
    assert block["block_type"] == "rule"
    assert block["is_valid"] is False
    assert block["errors"]
    invalid = result["invalid_snippets"][0]
    assert invalid["snippet_kind"] == "rule"
    assert invalid["block_index"] == 0
    assert result["needs_retry"] is True


def test_validate_code_blocks_accepts_valid_profile() -> None:
    """Delegates to profile validator and marks block as valid."""
    profile_yaml = dedent(
        """
        test_name: Demo
        llm:
          temperature: 0.3
          model: gpt-4o
        user:
          language: English
          role: customer
          goals:
            - Find a product
        chatbot:
          is_starter: true
          fallback: Sorry, I didn't get that.
          output:
            - result:
                type: string
                description: Final result
        conversation:
          number: 1
          goal_style:
            steps: 3
          interaction_style:
            - default
        """
    ).strip()

    result = validation.validate_code_blocks(
        [
            {"language": "yaml", "block_type": "profile", "documents": [{"doc": 1}], "content": profile_yaml},
        ]
    )

    block = result["validation_results"][0]
    assert block["block_type"] == "profile"
    assert block["is_valid"] is True
    assert result["invalid_snippets"] == []
    assert result["needs_retry"] is False


def test_validate_code_blocks_rejects_invalid_profile() -> None:
    """Surface profile validation errors and feedback."""
    invalid_profile = "test_name: appointment"  # missing required sections

    result = validation.validate_code_blocks(
        [
            {"language": "yaml", "block_type": "profile", "documents": [{"doc": 1}], "content": invalid_profile},
        ]
    )

    block = result["validation_results"][0]
    assert block["block_type"] == "profile"
    assert block["is_valid"] is False
    assert block["errors"]
    invalid = result["invalid_snippets"][0]
    assert invalid["snippet_kind"] == "profile"
    assert invalid["block_index"] == 0
    assert result["needs_retry"] is True


def test_validate_code_blocks_rejects_multiple_rules_in_one_block() -> None:
    """Rejects a code block containing multiple rule entries in one document."""
    content = dedent(
        """
        - name: first
          description: one
        - name: second
          description: two
        """
    ).strip()

    result = validation.validate_code_blocks(
        [
            {
                "language": "yaml",
                "block_type": "rule",
                "documents": [{"doc": 1}],
                "content": content,
            }
        ]
    )

    block_result = result["validation_results"][0]
    assert block_result["is_valid"] is False
    assert block_result["errors"][0] == "Rule must parse into a mapping."
    assert any("get_docs tool for rules" in e for e in block_result["errors"])
    invalid = result["invalid_snippets"][0]
    assert invalid["errors"][0] == "Rule must parse into a mapping."
    assert any("get_docs tool for rules" in e for e in invalid["errors"])
    assert invalid["block_index"] == 0
    assert invalid["block_type"] == "rule"
    assert invalid["snippet_number"] == 1
    assert result["needs_retry"] is True


def test_validate_rule_block_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aggregates metadata for a single valid rule without errors."""
    monkeypatch.setattr(
        validation,
        "validate_rule",
        lambda text: ValidationResult(True, [], ["warn-good"], data={"name": text}),
    )

    block_result, invalid = validation._validate_rule_block("good")

    assert block_result["is_valid"] is True
    assert block_result["errors"] == []
    assert block_result["warnings"] == ["warn-good"]
    assert block_result["data"] == {"name": "good"}
    assert block_result["rule"]["is_valid"] is True
    assert invalid == []


def test_validate_rule_block_converts_invalid_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wraps rule validation errors with snippet metadata."""
    monkeypatch.setattr(
        validation,
        "validate_rule",
        lambda text: ValidationResult(False, ["block err"], ["block warn"], data=None),
    )

    block_result, invalid_entries = validation._validate_rule_block("bad rule")

    assert block_result["warnings"] == ["block warn"]
    assert block_result["errors"] == ["block err"]
    assert invalid_entries == [
        {"snippet_kind": "rule", "snippet_number": 1, "errors": ["block err"], "warnings": ["block warn"]}
    ]


def test_validate_profile_block_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collects invalid profile results and preserves payload."""
    monkeypatch.setattr(
        validation,
        "validate_profile",
        lambda content: ValidationResult(False, ["bad profile"], ["profile warn"], data={"content": content}),
    )

    block_result, invalid_entries = validation._validate_profile_block("profile yaml")

    assert block_result["is_valid"] is False
    assert block_result["errors"] == ["bad profile"]
    assert block_result["warnings"] == ["profile warn"]
    assert block_result["data"] is None
    assert block_result["profile"]["data"] == {"content": "profile yaml"}
    assert invalid_entries == [
        {"snippet_kind": "profile", "snippet_number": None, "errors": ["bad profile"], "warnings": ["profile warn"]}
    ]
