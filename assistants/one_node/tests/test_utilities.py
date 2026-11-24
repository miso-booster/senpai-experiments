from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage

from app.utils.utilities import normalise_message_content


def test_normalise_string_returns_trimmed_text() -> None:
    assert normalise_message_content("  hello world  ") == "hello world"


def test_normalise_ai_and_base_messages_recurse() -> None:
    ai_message = AIMessage(content="  hola  ")
    assert normalise_message_content(ai_message) == "hola"

    system_message = SystemMessage(content="  dojo  ")
    assert normalise_message_content(system_message) == "dojo"


def test_normalise_iterables_extracts_text_parts() -> None:
    structured_content = [
        "  first  ",
        {"text": " second "},
        {"text": 123},
        {"text": None},
        456,
        ["nested", "list"],
    ]

    assert normalise_message_content(structured_content) == "first second 123 456 ['nested', 'list']"


def test_normalise_iterables_preserve_blank_entries_as_spacing() -> None:
    structured_content = ["first", "", " ", "second"]
    assert normalise_message_content(structured_content) == "first  second"


def test_normalise_none_and_objects() -> None:
    class WithStr:
        def __str__(self) -> str:
            return "custom"

    assert normalise_message_content(None) == ""
    assert normalise_message_content(WithStr()) == "custom"
