"""Extract structured metadata from fenced code blocks emitted by the LLM."""

from typing import Any, Dict, List

from langchain_core.messages import AIMessage

from app.assistant.codeblock_classifier import classify_documents
from app.assistant.codeblocks import extract_code_blocks, split_yaml_documents
from app.assistant.state import ChatState
from app.utils.utilities import normalise_message_content


def extract_code_blocks_metadata(state: ChatState) -> Dict[str, Any]:  # noqa: ANN401
    """Extract fenced code blocks from the latest AI message."""
    messages = state.get("messages", [])
    last_ai = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
    if last_ai is None:
        return {"code_blocks": []}

    text = normalise_message_content(last_ai.content)
    blocks = extract_code_blocks(text)
    payload: List[Dict[str, Any]] = []
    for block in blocks:
        documents = split_yaml_documents(block.content)
        classification = classify_documents(documents)
        multiple_documents = len(documents) > 1
        document_payloads: List[Dict[str, Any]] = []
        for index, document in enumerate(documents):
            kind = classification.document_types[index] if index < len(classification.document_types) else "unknown"
            document_payloads.append(
                {
                    **document.to_payload(),
                    "kind": kind,
                }
            )

        block_payload = block.to_payload()
        block_payload.update(classification.to_payload())
        block_payload["documents"] = document_payloads
        if multiple_documents:
            block_payload["error_reason"] = "multiple_documents_not_supported"
        payload.append(block_payload)
    return {"code_blocks": payload}
