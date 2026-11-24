from __future__ import annotations

from textwrap import dedent
from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.assistant.state import ChatState
from app.nodes.action.node_build_fix_system_prompt import build_fix_system_prompt
from app.nodes.action.node_extract_codeblocks_metadata import extract_code_blocks_metadata
from app.nodes.action.node_fix_invalid_code_blocks import fix_invalid_code_blocks
from tests.helpers import RecordingModel


def test_fix_invalid_code_blocks_replaces_only_target_blocks() -> None:
    original_response = dedent(
        """\
        Aquí tienes los bloques solicitados:
        ```yaml
        status: invalid
        ```

        Texto intermedio.

        ```yaml
        status: ok
        ```
        """
    ).strip()

    ai_message = AIMessage(content=original_response)
    state = ChatState(messages=[ai_message])

    metadata = extract_code_blocks_metadata(state)
    code_blocks = metadata["code_blocks"]

    validation_results = [
        {
            "index": 0,
            "language": "yaml",
            "block_type": "rule",
            "is_valid": False,
            "errors": ["status must be ok"],
            "warnings": [],
        },
        {
            "index": 1,
            "language": "yaml",
            "block_type": "rule",
            "is_valid": True,
            "errors": [],
            "warnings": [],
        },
    ]

    invalid_snippets = [
        {
            "block_index": 0,
            "language": "yaml",
            "block_type": "rule",
            "snippet_kind": "rule",
            "snippet_number": None,
            "errors": ["status must be ok"],
            "warnings": [],
        }
    ]

    state["code_blocks"] = code_blocks
    state["validation_results"] = validation_results
    state["invalid_snippets"] = invalid_snippets

    fixed_block = "```yaml\nstatus: ok\n```"

    responses = [AIMessage(content=fixed_block)]
    model = RecordingModel(lambda: responses.pop(0))

    fix_prompt = build_fix_system_prompt("")

    result = fix_invalid_code_blocks(
        state,
        cast(BaseChatModel, model),
        fix_system_prompt=fix_prompt,
    )

    assert result["retry_action"] == "none"
    assert result["needs_retry"] is False
    [updated_message] = result["messages"]
    assert isinstance(updated_message, AIMessage)
    assert "status: ok" in updated_message.content
    assert updated_message.content.count("```yaml") == 2
    assert "status: invalid" not in updated_message.content

    recorded = model.recorded_messages
    assert isinstance(recorded[0], SystemMessage)
    assert isinstance(recorded[1], HumanMessage)


def test_fix_invalid_code_blocks_does_not_update_when_no_code_block_returned() -> None:
    original_response = dedent(
        """\
        ```yaml
        needs: fixing
        ```
        """
    ).strip()

    ai_message = AIMessage(content=original_response)
    state = ChatState(messages=[ai_message])

    metadata = extract_code_blocks_metadata(state)
    state["code_blocks"] = metadata["code_blocks"]
    state["validation_results"] = [
        {
            "index": 0,
            "language": "yaml",
            "block_type": "rule",
            "is_valid": False,
            "errors": ["Example error"],
            "warnings": [],
        }
    ]
    state["invalid_snippets"] = [
        {
            "block_index": 0,
            "language": "yaml",
            "block_type": "rule",
            "snippet_kind": "rule",
            "snippet_number": None,
            "errors": ["Example error"],
            "warnings": [],
        }
    ]

    model = RecordingModel("Sin bloque de código")
    fix_prompt = build_fix_system_prompt("")

    result = fix_invalid_code_blocks(
        state,
        cast(BaseChatModel, model),
        fix_system_prompt=fix_prompt,
    )

    assert result["retry_action"] == "none"
    assert result["needs_retry"] is False
    assert "messages" not in result


def test_fix_invalid_code_blocks_handles_multiple_blocks() -> None:
    original_response = dedent(
        """\
        Intro line.

        ```yaml
        name: first_rule
        ```

        ```yaml
        name: ok
        ```

        Tail text.

        ```yaml
        name: last_rule
        ```
        """
    ).strip()

    ai_message = AIMessage(content=original_response)
    state = ChatState(messages=[ai_message])

    metadata = extract_code_blocks_metadata(state)
    state["code_blocks"] = metadata["code_blocks"]

    state["validation_results"] = [
        {
            "index": 0,
            "language": "yaml",
            "block_type": "rule",
            "is_valid": False,
            "errors": ["first rule invalid"],
            "warnings": [],
        },
        {
            "index": 1,
            "language": "yaml",
            "block_type": "rule",
            "is_valid": True,
            "errors": [],
            "warnings": [],
        },
        {
            "index": 2,
            "language": "yaml",
            "block_type": "rule",
            "is_valid": False,
            "errors": ["last rule invalid"],
            "warnings": [],
        },
    ]
    state["invalid_snippets"] = [
        {
            "block_index": 0,
            "language": "yaml",
            "block_type": "rule",
            "snippet_kind": "rule",
            "snippet_number": None,
            "errors": ["first rule invalid"],
            "warnings": [],
        },
        {
            "block_index": 2,
            "language": "yaml",
            "block_type": "rule",
            "snippet_kind": "rule",
            "snippet_number": None,
            "errors": ["last rule invalid"],
            "warnings": [],
        },
    ]

    responses = [
        AIMessage(content="```yaml\nname: fixed_last_rule\nextra: true\n```"),
        AIMessage(content="```yaml\nname: fixed_first_rule\n```"),
    ]

    model = RecordingModel(lambda: responses.pop(0))
    fix_prompt = build_fix_system_prompt("")

    result = fix_invalid_code_blocks(
        state,
        cast(BaseChatModel, model),
        fix_system_prompt=fix_prompt,
    )

    assert result["retry_action"] == "none"
    assert result["needs_retry"] is False
    updated_message = result["messages"][0]
    assert isinstance(updated_message, AIMessage)
    assert isinstance(updated_message.content, str)

    updated_content = updated_message.content
    assert updated_content.count("```yaml") == 3
    assert "name: fixed_first_rule" in updated_content
    assert "name: fixed_last_rule" in updated_content
    assert "extra: true" in updated_content
    assert "name: ok" in updated_content  # middle block untouched
    assert "name: first_rule" not in updated_content
    assert "name: last_rule" not in updated_content

    assert updated_content.startswith("Intro line.")
    assert "Tail text." in updated_content
    assert len(model.recorded_messages) == 4
    assert all(isinstance(model.recorded_messages[i], SystemMessage) for i in (0, 2))
    assert all(isinstance(model.recorded_messages[i], HumanMessage) for i in (1, 3))
