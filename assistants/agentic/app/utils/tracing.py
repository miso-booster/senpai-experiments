"""Helpers to configure LangSmith tracing for observability."""

from __future__ import annotations

import logging
import os
from typing import Final

DEFAULT_PROJECT: Final[str] = "senpai-assistant"
LANGSMITH_ENDPOINT: Final[str] = "https://api.smith.langchain.com"


def enable_langsmith_tracing(enabled: bool, project_name: str | None = None, api_key: str | None = None) -> None:
    """Enable LangSmith tracing by configuring environment variables.

    Args:
        enabled: Whether tracing should be turned on for the current run.
        project_name: Optional project to group traces under. Defaults to DEFAULT_PROJECT.
        api_key: Optional override for the LangSmith API key.
    """
    if not enabled:
        return

    logger = logging.getLogger(__name__)
    env = os.environ

    if api_key:
        env["LANGSMITH_API_KEY"] = api_key
        env["LANGCHAIN_API_KEY"] = api_key

    resolved_api_key = env.get("LANGCHAIN_API_KEY") or env.get("LANGSMITH_API_KEY")

    env.setdefault("LANGSMITH_TRACING", "true")
    env.setdefault("LANGCHAIN_ENDPOINT", env.get("LANGSMITH_ENDPOINT", LANGSMITH_ENDPOINT))

    project_value = project_name or env.get("LANGCHAIN_PROJECT") or DEFAULT_PROJECT
    env.setdefault("LANGCHAIN_PROJECT", project_value)
    env.setdefault("LANGSMITH_PROJECT", project_value)

    if resolved_api_key:
        required_langsmith_vars = [
            "LANGSMITH_API_KEY",
            "LANGSMITH_TRACING",
            "LANGSMITH_PROJECT",
            "LANGSMITH_ENDPOINT",
        ]

        missing_vars = [var for var in required_langsmith_vars if not env.get(var)]

        if missing_vars:
            logger.warning(
                "Some LangSmith environment variables are missing: %s",
                ", ".join(missing_vars),
            )
        else:
            logger.info(
                "All LangSmith environment variables are set. LangSmith tracing enabled for project '%s'.",
                project_value,
            )

    else:
        logger.warning(
            "LangSmith tracing requested but no API key found. "
            "Set LANGSMITH_API_KEY or LANGCHAIN_API_KEY so traces can be sent."
        )
