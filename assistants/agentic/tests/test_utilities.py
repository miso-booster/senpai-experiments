from __future__ import annotations

import sqlite3

from langchain_core.messages import AIMessage, SystemMessage

from app.utils.utilities import normalise_message_content, safe_close


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


def test_safe_close_calls_close_successfully() -> None:
    class Closeable:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    resource = Closeable()

    safe_close(resource)

    assert resource.closed is True


def test_safe_close_swallows_oserror() -> None:
    class Closeable:
        def close(self) -> None:
            raise OSError("nope")

    safe_close(Closeable())


def test_safe_close_swallows_runtimeerror() -> None:
    class Closeable:
        def close(self) -> None:
            raise RuntimeError("nope")

    safe_close(Closeable())


def test_safe_close_swallows_sqlite_programming_error() -> None:
    class Closeable:
        def close(self) -> None:
            raise sqlite3.ProgrammingError("nope")

    safe_close(Closeable())
