"""Tests for the CLI argument parser."""

from __future__ import annotations

import pytest

from app.CLI.cli import parse_conversation_arguments


def test_parse_conversation_arguments_requires_project_path() -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_conversation_arguments(["--user-path", "users/jane_doe"])

    assert excinfo.value.code == 2


def test_parse_conversation_arguments_requires_user_path() -> None:
    with pytest.raises(SystemExit) as excinfo:
        parse_conversation_arguments(["--project-path", "sensei_projects/pizza_shop"])

    assert excinfo.value.code == 2


def test_parse_conversation_arguments_custom_id() -> None:
    args = parse_conversation_arguments(
        [
            "--conversation-id",
            "my-session",
            "--project-path",
            "sensei_projects/pizza_shop",
            "--user-path",
            "users/jane_doe",
        ]
    )

    assert args.conversation_id == "my-session"


def test_parse_conversation_arguments_missing_id() -> None:
    args = parse_conversation_arguments(
        [
            "--project-path",
            "sensei_projects/pizza_shop",
            "--user-path",
            "users/jane_doe",
        ]
    )

    assert args.conversation_id is None


def test_parse_conversation_arguments_verbose_flag() -> None:
    args = parse_conversation_arguments(
        [
            "--conversation-id",
            "my-session",
            "--project-path",
            "sensei_projects/pizza_shop",
            "--user-path",
            "users/jane_doe",
            "--verbose",
        ]
    )

    assert args.verbose is True


def test_parse_conversation_arguments_log_file_flag() -> None:
    args = parse_conversation_arguments(
        [
            "--conversation-id",
            "my-session",
            "--project-path",
            "sensei_projects/pizza_shop",
            "--user-path",
            "users/jane_doe",
            "--log-file",
            "logs_folder",
        ]
    )

    assert args.log_file == "logs_folder"


def test_parse_conversation_arguments_single_turn_prompt_flag() -> None:
    args = parse_conversation_arguments(
        [
            "--conversation-id",
            "my-session",
            "--project-path",
            "sensei_projects/pizza_shop",
            "--user-path",
            "users/jane_doe",
            "--single-turn-prompt",
            "Hola, Senpai!",
        ]
    )

    assert args.single_turn_prompt == "Hola, Senpai!"


def test_parse_conversation_arguments_single_turn_prompt_default_none() -> None:
    args = parse_conversation_arguments(
        [
            "--conversation-id",
            "my-session",
            "--project-path",
            "sensei_projects/pizza_shop",
            "--user-path",
            "users/jane_doe",
        ]
    )

    assert args.single_turn_prompt is None
