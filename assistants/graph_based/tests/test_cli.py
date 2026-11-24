"""Tests for the CLI argument parser."""

from __future__ import annotations

from app.CLI.cli import parse_conversation_arguments


def test_parse_conversation_arguments_defaults() -> None:
    args = parse_conversation_arguments([])

    assert args.conversation_id is None
    assert args.verbose is False
    assert args.project_path == ""
    assert args.user_path == ""
    assert args.single_turn_prompt is None


def test_parse_conversation_arguments_custom_id() -> None:
    args = parse_conversation_arguments(["--conversation-id", "my-session"])

    assert args.conversation_id == "my-session"


def test_parse_conversation_arguments_verbose_flag() -> None:
    args = parse_conversation_arguments(["--verbose"])

    assert args.verbose is True


def test_parse_conversation_arguments_single_turn_prompt() -> None:
    args = parse_conversation_arguments(["--single-turn-prompt", "hola"])

    assert args.single_turn_prompt == "hola"


def test_parse_conversation_arguments_user_path() -> None:
    args = parse_conversation_arguments(["--user-path", "/tmp/demo-user"])

    assert args.user_path == "/tmp/demo-user"
