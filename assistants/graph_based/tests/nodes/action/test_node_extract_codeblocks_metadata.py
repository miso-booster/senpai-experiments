from __future__ import annotations

from textwrap import dedent

from langchain_core.messages import AIMessage

from app.assistant.state import ChatState
from app.nodes.action.node_extract_codeblocks_metadata import extract_code_blocks_metadata


def test_extract_code_blocks_metadata_returns_document_metadata() -> None:
    ai_message = AIMessage(
        content=dedent(
            """
            Here is the configuration you asked for:
            ```yaml
            name: toppings_monotonicity
            description: More toppings increases price
            conversations: 2
            oracle: extract_float(conv[0].price) <= extract_float(conv[1].price)

            ---

            test_name: sample_profile
            llm:
              model: gpt-4o
            user:
              language: English
            chatbot:
              is_starter: false
            ```
            """
        ).strip()
    )

    state = ChatState(messages=[ai_message])
    result = extract_code_blocks_metadata(state)
    blocks = result["code_blocks"]

    assert len(blocks) == 1
    block = blocks[0]
    assert block["block_type"] == "error"
    assert block["document_types"] == ["error", "error"]
    assert block["error_reason"] == "multiple_documents_not_supported"

    documents = block["documents"]
    assert len(documents) == 2
    assert documents[0]["kind"] == "error"
    assert documents[1]["kind"] == "error"
    assert "toppings_monotonicity" in documents[0]["text"]
    assert "test_name: sample_profile" in documents[1]["text"]
