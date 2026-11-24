"""Unit tests for the SENSEI-check rule validator."""

from __future__ import annotations

from textwrap import dedent

from app.validator.rules_validator import RuleValidationResult, validate_rule


def test_accepts_valid_oracle_rule() -> None:
    rule_text = dedent(
        """
        name: toppings_monotonicity
        description: More toppings increases total price
        conversations: 2
        when: conv[0].size == conv[1].size
        oracle: extract_float(conv[0].price) > extract_float(conv[1].price)
        """
    ).strip()

    result = validate_rule(rule_text)

    assert result.is_valid
    assert isinstance(result, RuleValidationResult)
    assert result.errors == []
    assert result.warnings == []
    assert result.data is not None
    assert result.data["name"] == "toppings_monotonicity"


def test_rejects_missing_required_fields() -> None:
    rule_text = dedent(
        """
        description: Missing name and conversations
        oracle: some_check()
        """
    ).strip()

    result = validate_rule(rule_text)

    assert not result.is_valid
    joined = " ".join(result.errors)
    assert "Missing required fields" in joined
    assert "name" in joined
    assert "description" not in joined


def test_rejects_missing_relation_components() -> None:
    rule_text = dedent(
        """
        name: size_monotonicity
        description: Larger size should not be cheaper
        conversations: 2
        if: conv[0].size == 'small'
        """
    ).strip()

    result = validate_rule(rule_text)

    assert not result.is_valid
    assert "Rule includes 'if' but missing 'then'." in result.errors[0]


def test_invalid_yaml_is_reported() -> None:
    result = validate_rule("name: [unclosed")

    assert not result.is_valid
    assert any(msg.startswith("Rule is not valid YAML") for msg in result.errors)


def test_warns_on_unexpected_fields() -> None:
    rule_text = dedent(
        """
        name: scope_guardrails
        description: Assistant stays on topic
        conversations: 1
        oracle: only_talks_about('pizza orders')
        extra_field: true
        """
    ).strip()

    result = validate_rule(rule_text)

    assert result.is_valid
    assert result.errors == []
    assert "Unexpected fields present" in " ".join(result.warnings)


def test_empty_rule_early_exit() -> None:
    result = validate_rule("   \n   ")

    assert not result.is_valid
    assert result.errors == ["Rule text is empty."]


def test_rejects_non_mapping_yaml() -> None:
    rule_text = "- just\n- a\n- list"

    result = validate_rule(rule_text)

    assert not result.is_valid
    assert "Rule must parse into a mapping." in result.errors[0]


def test_rejects_blank_description() -> None:
    rule_text = dedent(
        """
        name: missing_description
        description: "   "
        conversations: 1
        oracle: True
        """
    ).strip()

    result = validate_rule(rule_text)
    assert not result.is_valid
    assert "Value error, field 'description' must be a non-empty string." in result.errors[0]


def test_rejects_conversations_lower_than_one() -> None:
    rule_text = dedent(
        """
        name: zero_conversations
        description: Invalid numeric conversations
        conversations: 0
        oracle: True
        """
    ).strip()

    result = validate_rule(rule_text)

    assert not result.is_valid
    assert "Field 'conversations' must be >= 1 when numeric" in result.errors[0]


def test_accepts_all_conversations_string() -> None:
    rule_text = dedent(
        """
        name: all_conversations
        description: Use 'all'
        conversations: all
        oracle: "True"
        """
    ).strip()

    result = validate_rule(rule_text)

    assert result.is_valid
    assert result.data is not None
    assert result.data["conversations"] == "all"


def test_rejects_conversations_string_other_than_all() -> None:
    rule_text = dedent(
        """
        name: invalid_convo_string
        description: Invalid string conversations value
        conversations: pair
        oracle: "True"
        """
    ).strip()

    result = validate_rule(rule_text)

    assert not result.is_valid
    assert "Field 'conversations' must be an integer or 'all'." in result.errors[0]


def test_warns_when_oracle_and_if_defined() -> None:
    rule_text = dedent(
        """
        name: dual_relation
        description: Both oracle and if defined
        conversations: 2
        oracle: "True"
        if: some_condition
        then: some_result
        """
    ).strip()

    result = validate_rule(rule_text)

    assert result.is_valid
    assert result.errors == []
    assert "Rule defines both 'oracle' and 'if'" in " ".join(result.warnings)


def test_rejects_then_without_if() -> None:
    rule_text = dedent(
        """
        name: then_without_if
        description: Invalid relation structure
        conversations: 2
        then: result_condition
        """
    ).strip()

    result = validate_rule(rule_text)

    assert not result.is_valid
    assert "Rule includes 'then' but missing 'if'." in result.errors[0]


def test_non_string_condition_fields_rejected() -> None:
    rule_text = dedent(
        """
        name: non_string_fields
        description: Non-string conditional fields
        conversations: 1
        when: 123
        oracle: True
        """
    ).strip()

    result = validate_rule(rule_text)

    assert not result.is_valid
    assert "Field 'when' must be a string when provided." in result.errors[0]
