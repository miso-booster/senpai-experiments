from __future__ import annotations

from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel

from app.assistant.validation_middleware import MessageValidationMiddleware


class _DummyModel:
    pass


def test_retry_instruction_avoids_meta_framing() -> None:
    middleware = MessageValidationMiddleware(model=cast(BaseChatModel, _DummyModel()))

    text = middleware._build_retry_instruction(
        feedback="Errors:\n- missing field",
        block_type="rule",
        block_count=1,
        user_message="please make a rule",
        previous_assistant_message="Here is the corrected rule:\n```yaml\nbad: yaml\n```",
    )

    assert "Rewrite your entire previous assistant message" in text
    assert "Only mention a correction/fix/update if" in text
    assert "Keep every YAML code fence" in text
    assert "User request (for context)" in text
    assert "Previous assistant message to rewrite" in text
