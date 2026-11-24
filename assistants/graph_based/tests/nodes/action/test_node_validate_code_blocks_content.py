from __future__ import annotations

from textwrap import dedent

from app.assistant.state import ChatState
from app.nodes.action.node_validate_code_blocks_content import validate_code_blocks_content


def test_validate_code_blocks_content_marks_multiple_documents_error() -> None:
    block = {
        "block_type": "error",
        "documents": [{"text": ""}, {"text": ""}],
        "content": "name: rule_one\n---\nname: rule_two",
        "language": "yaml",
        "error_reason": "multiple_documents_not_supported",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is True
    assert result["validation_attempts"] == 1
    assert result["retry_action"] == "fix_blocks"
    assert result["invalid_snippets"]
    feedback = result["validation_feedback"] or ""
    assert "Validation repair summary:" in feedback
    assert "- invalid blocks: 1" in feedback
    assert "Block 1 (yaml)" in feedback
    [validation_result] = result["validation_results"]
    assert validation_result["is_valid"] is False
    assert validation_result["block_type"] == "error"
    assert "exactly one YAML document" in validation_result["errors"][0]


def test_validate_code_blocks_content_applies_profile_validator() -> None:
    profile_yaml = dedent(
        """\
        test_name: sample_profile
        user:
          language: English
          role: Curious person
          goals:
            - Learn more about Sensei
        chatbot:
          is_starter: true
        conversation:
          number: 1
        """
    ).strip()

    block = {
        "block_type": "profile",
        "documents": [{"text": profile_yaml}],
        "content": profile_yaml,
        "language": "yaml",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is False
    assert result["validation_attempts"] == 0
    [validation_result] = result["validation_results"]
    assert validation_result["block_type"] == "profile"
    assert validation_result["is_valid"] is True
    assert validation_result["profile"]["is_valid"] is True


def test_validate_code_blocks_content_reports_profile_errors() -> None:
    faulty_profile = dedent(
        """\
        test_name: incomplete_profile
        user:
          language: English
          role: Test user
          goals:
            - Goal one
        chatbot:
          is_starter: false
        """
    ).strip()

    block = {
        "block_type": "profile",
        "documents": [{"text": faulty_profile}],
        "content": faulty_profile,
        "language": "yaml",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is True
    assert result["validation_attempts"] == 1
    assert result["retry_action"] == "fix_blocks"
    assert result["invalid_snippets"]
    [validation_result] = result["validation_results"]
    assert validation_result["block_type"] == "profile"
    assert validation_result["is_valid"] is False
    assert "Missing required top-level fields" in validation_result["errors"][0]
    feedback = result["validation_feedback"] or ""
    assert "Validation repair summary:" in feedback
    assert "- invalid blocks: 1" in feedback
    assert "Block 1 (yaml)" in feedback


def test_validate_code_blocks_content_rejects_multiple_rules_in_block() -> None:
    multi_rule_yaml = dedent(
        """\
        - name: first_rule
          description: First rule
          conversations: 1
          oracle: "True"
        - name: second_rule
          description: Second rule
          conversations: 2
          oracle: "True"
        """
    ).strip()

    block = {
        "block_type": "unknown",
        "documents": [{"text": multi_rule_yaml}],
        "content": multi_rule_yaml,
        "language": "yaml",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is True
    assert result["validation_attempts"] == 1
    assert result["retry_action"] == "fix_blocks"
    [validation_result] = result["validation_results"]
    assert validation_result["block_type"] == "rule"
    assert validation_result["is_valid"] is False
    assert any("exactly one" in err.lower() for err in validation_result["errors"])


def test_validate_code_blocks_content_applies_rule_validator() -> None:
    rule_yaml = dedent(
        """\
        name: scope_guardrail
        description: Keep responses on-topic
        conversations: 1
        oracle: "True"
        """
    ).strip()

    block = {
        "block_type": "rule",
        "documents": [{"text": rule_yaml}],
        "content": rule_yaml,
        "language": "yaml",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is False
    assert result["validation_attempts"] == 0
    [validation_result] = result["validation_results"]
    assert validation_result["block_type"] == "rule"
    assert validation_result["is_valid"] is True
    assert validation_result["rules"][0]["is_valid"] is True


def test_validate_code_blocks_content_reports_rule_errors() -> None:
    invalid_rule_yaml = "name: only_name"

    block = {
        "block_type": "rule",
        "documents": [{"text": invalid_rule_yaml}],
        "content": invalid_rule_yaml,
        "language": "yaml",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is True
    assert result["validation_attempts"] == 1
    assert result["retry_action"] == "fix_blocks"
    assert result["invalid_snippets"]
    [validation_result] = result["validation_results"]
    assert validation_result["block_type"] == "rule"
    assert validation_result["is_valid"] is False
    assert any("Missing required fields" in err for err in validation_result["errors"])
    assert any("get_docs tool for rules" in err for err in validation_result["errors"])
    feedback = result["validation_feedback"] or ""
    assert "Validation repair summary:" in feedback
    assert "- invalid blocks: 1" in feedback
    assert "Block 2 (rule 1) (yaml)" in feedback or "Block 1 (rule 1) (yaml)" in feedback


def test_validate_code_blocks_content_applies_connector_validator() -> None:
    connector_yaml = dedent(
        """\
        name: demo_connector
        base_url: "https://example.com"
        send_message:
          path: "/api/messages"
          method: "POST"
          payload_template:
            message: "{user_msg}"
        response_path: "messages.0.content"
        """
    ).strip()

    block = {
        "block_type": "connector",
        "documents": [{"text": connector_yaml}],
        "content": connector_yaml,
        "language": "yaml",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is False
    assert result["validation_attempts"] == 0
    [validation_result] = result["validation_results"]
    assert validation_result["block_type"] == "connector"
    assert validation_result["is_valid"] is True
    assert validation_result["connector"]["is_valid"] is True


def test_validate_code_blocks_content_reports_connector_errors() -> None:
    invalid_connector_yaml = dedent(
        """\
        name: bad_connector
        base_url: "https://example.com"
        send_message:
          path: "/api/messages"
          method: "POST"
          payload_template:
            message: "{message}"
        response_path: "messages.0.content"
        """
    ).strip()

    block = {
        "block_type": "connector",
        "documents": [{"text": invalid_connector_yaml}],
        "content": invalid_connector_yaml,
        "language": "yaml",
    }
    state = ChatState(code_blocks=[block], validation_attempts=0)

    result = validate_code_blocks_content(state)

    assert result["needs_retry"] is True
    assert result["validation_attempts"] == 1
    assert result["retry_action"] == "fix_blocks"
    [validation_result] = result["validation_results"]
    assert validation_result["block_type"] == "connector"
    assert validation_result["is_valid"] is False
    assert any("{user_msg}" in err for err in validation_result["errors"])
    feedback = result["validation_feedback"] or ""
    assert "Validation repair summary:" in feedback
    assert "- invalid blocks: 1" in feedback
    assert "Block 1 (yaml)" in feedback
