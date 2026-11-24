from __future__ import annotations

from textwrap import dedent

from app.assistant.codeblock_classifier import (
    CodeBlockClassification,
    classify_code_block,
    classify_documents,
    extract_yaml_blocks,
)


def test_classify_connector_by_core_keys() -> None:
    """Classify connector-shaped YAML using its core fields."""
    content = dedent(
        """
        base_url: https://api.example.com
        send_message:
          path: /chat
          payload_template:
            message: "{user_msg}"
        response_path: data.message.text
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "connector"
    assert classification.document_types == ["connector"]


def test_extract_yaml_blocks_marks_connector_type() -> None:
    """extract_yaml_blocks should propagate connector classification to the payload."""
    connector_yaml = dedent(
        """
        base_url: https://chat.example.com
        send_message:
          path: /messages
          payload_template:
            text: "{user_msg}"
        response_path: result.reply
        """
    ).strip()
    text = f"Here is your connector:\n```yaml\n{connector_yaml}\n```"

    blocks = extract_yaml_blocks(text)

    assert len(blocks) == 1
    block = blocks[0]
    assert block["block_type"] == "connector"
    assert block["language"] == "yaml"
    assert block["documents"] == [connector_yaml]


def test_classify_connector_when_yaml_parse_fails() -> None:
    """Fallback to text-based heuristics when YAML parsing fails."""
    # Missing closing quote in payload_template should break YAML parsing.
    broken_connector = dedent(
        """
        base_url: https://api.example.com
        send_message:
          path: /chat
          payload_template:
            message: "{user_msg
        response_path: data.message.text
        """
    ).strip()

    classification = classify_code_block(broken_connector)

    assert classification.block_type == "connector"
    assert classification.document_types == ["connector"]


def test_classify_rule_by_core_keys() -> None:
    """Classify rule-shaped YAML using its core fields."""
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

    classification = classify_code_block(rule_yaml)

    assert classification.block_type == "rule"
    assert classification.document_types == ["rule"]


def test_classify_rule_wrapped_with_name_key() -> None:
    """Rules wrapped under a single top-level key should still classify as rules."""
    content = dedent(
        """
        rule_check_opening_time:
          oracle: opening_time_check
          if:
            - conv[0].opening_hours == "10:00 AM"
          then:
            - respond: "The shop opens at 10:00 AM."
          else:
            - respond: "The shop does not open at 10:00 AM."
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "rule"
    assert classification.document_types == ["rule"]


def test_classify_profile_wrapped_with_name_key() -> None:
    """Profiles wrapped under a single key should still classify as profiles."""
    content = dedent(
        """
        appointment_profile:
          test_name: appointment
          chatbot:
            fallback: sorry
          user:
            language: English
            role: customer
          conversation:
            number: 1
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "profile"
    assert classification.document_types == ["profile"]


def test_classify_connector_wrapped_with_name_key() -> None:
    """Connectors wrapped under a single key should still classify as connectors."""
    content = dedent(
        """
        weather_connector:
          base_url: https://api.example.com
          send_message:
            path: /chat
            payload_template:
              message: "{user_msg}"
          response_path: data.message.text
        """
    ).strip()

    classification = classify_code_block(content)

    assert classification.block_type == "connector"
    assert classification.document_types == ["connector"]


def test_extract_yaml_blocks_marks_rule_type() -> None:
    """extract_yaml_blocks should propagate rule classification to the payload."""
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
    text = f"```yaml\n{rule_yaml}\n```"

    blocks = extract_yaml_blocks(text)

    assert len(blocks) == 1
    block = blocks[0]
    assert block["block_type"] == "rule"
    assert block["language"] == "yaml"
    assert block["documents"] == [rule_yaml]


def test_classify_profile_by_core_keys() -> None:
    """Classify profile-shaped YAML using its core fields."""
    profile_yaml = dedent(
        """
        test_name: appointment
        llm:
          temperature: 0.0
          model: gpt-4o-mini

        user:
          language: English
          role:
            you have to act as a user talking to a virtual assistant of a bike shop
          context:
            - You are interested in setting an appointment for your bike
          goals:
            - "Setting an appointment for {{ap_date}}, at {{hour}}, for a {{service}} of my bike"
            - ap_date:
                function: forward(service)
                type: string
                data:
                  - tomorrow
                  - November 6th, 2024
            - hour:
                function: another()
                type: string
                data:
                  - "10:00"
                  - "14:00"
                  - "13:00"
                  - "15:30"
            - service:
                function: forward()
                type: string
                data:
                  - tune-up
                  - repair

        chatbot:
          is_starter: True
          fallback: I'm sorry it's a little loud in my shop, can you say that again?
          output:
            - confirmed_date:
                type: date
                description: the date of the appointment, confirmed by the assistant
            - confirmed_time:
                type: str
                description: the hour of the appointment, confirmed by the assistant
            - confirmed_service:
                type: str
                description: the service to be done in the appointment, confirmed by the assistant

        conversation:
          number: 4
          goal_style:
            all_answered:
              export: True
              limit: 5
          interaction_style:
              - default
        """
    ).strip()

    classification = classify_code_block(profile_yaml)

    assert classification.block_type == "profile"
    assert classification.document_types == ["profile"]


def test_extract_yaml_blocks_marks_profile_type() -> None:
    """extract_yaml_blocks should propagate profile classification to the payload."""
    profile_yaml = dedent(
        """
        test_name: appointment
        llm:
          temperature: 0.0
          model: gpt-4o-mini

        user:
          language: English
          role:
            you have to act as a user talking to a virtual assistant of a bike shop
          context:
            - You are interested in setting an appointment for your bike
          goals:
            - "Setting an appointment for {{ap_date}}, at {{hour}}, for a {{service}} of my bike"
            - ap_date:
                function: forward(service)
                type: string
                data:
                  - tomorrow
                  - November 6th, 2024
            - hour:
                function: another()
                type: string
                data:
                  - "10:00"
                  - "14:00"
                  - "13:00"
                  - "15:30"
            - service:
                function: forward()
                type: string
                data:
                  - tune-up
                  - repair

        chatbot:
          is_starter: True
          fallback: I'm sorry it's a little loud in my shop, can you say that again?
          output:
            - confirmed_date:
                type: date
                description: the date of the appointment, confirmed by the assistant
            - confirmed_time:
                type: str
                description: the hour of the appointment, confirmed by the assistant
            - confirmed_service:
                type: str
                description: the service to be done in the appointment, confirmed by the assistant

        conversation:
          number: 4
          goal_style:
            all_answered:
              export: True
              limit: 5
          interaction_style:
              - default
        """
    ).strip()
    text = f"```yaml\n{profile_yaml}\n```"

    blocks = extract_yaml_blocks(text)

    assert len(blocks) == 1
    block = blocks[0]
    assert block["block_type"] == "profile"
    assert block["language"] == "yaml"
    assert block["documents"] == [profile_yaml]


def test_to_payload_serialises_classification() -> None:
    """CodeBlockClassification.to_payload should surface its fields cleanly."""
    payload = CodeBlockClassification(block_type="rule", document_types=["rule"]).to_payload()

    assert payload == {"block_type": "rule", "document_types": ["rule"]}


def test_classify_documents_empty_returns_unknown() -> None:
    """Empty document collections should classify as unknown with no document types."""
    classification = classify_documents([])

    assert classification.block_type == "unknown"
    assert classification.document_types == []


def test_classify_documents_multiple_documents_flag_error() -> None:
    """Multiple YAML documents in a block are treated as an error."""
    classification = classify_documents([{"one": 1}, {"two": 2}])

    assert classification.block_type == "error"
    assert classification.document_types == ["error", "error"]


def test_classify_documents_accepts_plain_mapping_input() -> None:
    """Non-YamlDocument mappings should still be classified."""
    classification = classify_documents([{"name": "r", "description": "d", "then": "do"}])

    assert classification.block_type == "rule"
    assert classification.document_types == ["rule"]


def test_classify_document_empty_mapping_returns_unknown() -> None:
    """An empty mapping should not be classified as a known type."""
    classification = classify_documents([{}])

    assert classification.block_type == "unknown"
    assert classification.document_types == ["unknown"]


def test_flatten_skips_non_string_and_empty_keys() -> None:
    """Non-string and empty keys should be ignored without breaking scoring."""
    payload = {1: "ignored", "": "also ignored", "name": "n", "description": "d", "then": "do"}

    classification = classify_documents([payload])

    assert classification.block_type == "rule"
    assert classification.document_types == ["rule"]


def test_extract_yaml_blocks_handles_empty_and_non_yaml() -> None:
    """Empty input and non-YAML fences should yield no extracted blocks."""
    assert extract_yaml_blocks("") == []

    non_yaml_text = '```json\n{"foo": "bar"}\n```'
    assert extract_yaml_blocks(non_yaml_text) == []
