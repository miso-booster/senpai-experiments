from __future__ import annotations

from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from app.assistant.validation_middleware import MessageValidationMiddleware


class _DummyModel:
    pass


def test_build_reference_docs_message_fetches_rules_docs() -> None:
    middleware = MessageValidationMiddleware(model=cast(BaseChatModel, _DummyModel()))

    msg = middleware._build_reference_docs_message(
        [{"language": "yaml", "content": "x: 1", "block_type": "rule", "documents": ["x: 1"]}]
    )

    assert isinstance(msg, SystemMessage)
    assert "Reference documentation" in msg.content
    assert "## sensei-check-doc.md" in msg.content


def test_build_reference_docs_message_unions_doc_types() -> None:
    middleware = MessageValidationMiddleware(model=cast(BaseChatModel, _DummyModel()))

    msg = middleware._build_reference_docs_message(
        [
            {"language": "yaml", "content": "x: 1", "block_type": "rule", "documents": ["x: 1"]},
            {"language": "yaml", "content": "x: 1", "block_type": "profile", "documents": ["x: 1"]},
        ]
    )

    assert isinstance(msg, SystemMessage)
    assert "## sensei-check-doc.md" in msg.content
    assert "## sensei-chat-guide.md" in msg.content


def test_build_reference_docs_message_unknown_block_includes_all_doc_types() -> None:
    middleware = MessageValidationMiddleware(model=cast(BaseChatModel, _DummyModel()))

    msg = middleware._build_reference_docs_message(
        [
            {"language": "yaml", "content": "x: 1", "block_type": "unknown", "documents": ["x: 1"]},
        ]
    )

    assert isinstance(msg, SystemMessage)
    assert "## sensei-check-doc.md" in msg.content
    assert "## sensei-chat-guide.md" in msg.content
    assert "## custom-connector-guide.md" in msg.content
