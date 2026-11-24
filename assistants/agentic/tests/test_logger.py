import io
import logging
import re
import sys
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Iterator

import pytest
from _pytest.monkeypatch import MonkeyPatch

from app.utils.logger import COLORS, RESET, ColoredFormatter, logging_config


@pytest.fixture(autouse=True)
def restore_logging_state() -> Iterator[None]:
    logger = logging.getLogger()
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_disable = logger.manager.disable
    yield
    for handler in logger.handlers:
        if handler not in original_handlers:
            if not hasattr(handler, "lock"):
                handler.lock = None
            handler.close()
    logger.handlers.clear()
    logger.handlers.extend(original_handlers)
    logger.setLevel(original_level)
    logger.manager.disable = original_disable


def test_colored_formatter_applies_colors_and_preserves_record() -> None:
    formatter = ColoredFormatter("%(levelname)s - %(message)s")
    record = logging.LogRecord(
        name="dojo",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg="something broke",
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)

    color = COLORS[logging.ERROR]
    assert f"{color}ERROR{RESET}" in formatted
    assert f"{color}something broke{RESET}" in formatted
    assert record.levelname == "ERROR"
    assert record.msg == "something broke"


def test_colored_formatter_falls_back_to_reset_for_unknown_levels() -> None:
    formatter = ColoredFormatter("%(levelname)s:%(message)s")
    record = logging.LogRecord("dojo", 5, __file__, 20, "lower", (), None)

    formatted = formatter.format(record)

    assert formatted.startswith(f"{RESET}Level 5{RESET}:")
    assert f"{RESET}lower{RESET}" in formatted


def test_logging_config_sets_verbose_logging_and_clears_handlers(monkeypatch: MonkeyPatch) -> None:
    logger = logging.getLogger()
    logger.addHandler(logging.NullHandler())

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    logging_config(verbose=True, debug=False)

    assert logger.level == logging.INFO
    assert len(logger.handlers) == 1
    handler = logger.handlers[0]
    assert isinstance(handler.formatter, ColoredFormatter)
    assert not any(isinstance(h, logging.NullHandler) for h in logger.handlers)

    logger.info("hello")

    output = stream.getvalue()
    color = COLORS[logging.INFO]
    assert "Verbose enabled." in output
    assert f"{color}hello{RESET}" in output


def test_logging_config_sets_debug_logging(monkeypatch: MonkeyPatch) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    logging_config(verbose=False, debug=True)

    logger = logging.getLogger()
    assert logger.level == logging.DEBUG
    logger.debug("extra debug line")

    output = stream.getvalue()
    debug_color = COLORS[logging.DEBUG]
    info_color = COLORS[logging.INFO]
    assert f"{info_color}Debug enabled.{RESET}" in output
    assert f"{debug_color}extra debug line{RESET}" in output
    assert "Verbose enabled." not in output


def test_logging_config_disables_logging_when_flags_false() -> None:
    logger = logging.getLogger()
    logger.addHandler(logging.NullHandler())

    logging_config(verbose=False, debug=False)

    assert logger.handlers == []
    assert logger.manager.disable == logging.CRITICAL
    assert not logger.isEnabledFor(logging.CRITICAL)


def test_logging_config_creates_timestamped_log_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FixedDateTime":
            if tz is None:
                return cls(2024, 1, 2, 3, 4, 5)
            return cls(2024, 1, 2, 3, 4, 5, tzinfo=tz)

    logger_module = sys.modules[logging_config.__module__]
    monkeypatch.setattr(logger_module, "datetime", FixedDateTime)

    logging_config(verbose=False, debug=False, log_file=str(tmp_path))
    logging.getLogger().info("hello")
    logging.shutdown()

    log_files = list(tmp_path.glob("senpai_log_file_*.txt"))
    assert len(log_files) == 1
    assert log_files[0].name == "senpai_log_file_20240102_030405.txt"
    contents = log_files[0].read_text(encoding="utf-8")
    assert "hello" in contents
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[INFO\] \(root\) - hello", contents)


def test_logging_config_logs_error_when_file_handler_fails(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    logger_module = sys.modules[logging_config.__module__]

    def raising_file_handler(*_args: object, **_kwargs: object) -> logging.FileHandler:
        raise OSError("nope")

    monkeypatch.setattr(logger_module.logging, "FileHandler", raising_file_handler)

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    logging_config(verbose=True, debug=False, log_file=str(tmp_path))

    output = stream.getvalue()
    assert "Failed to create log file" in output
    assert "nope" in output


def test_logging_config_writes_console_and_file_when_verbose(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FixedDateTime":
            if tz is None:
                return cls(2024, 1, 2, 3, 4, 6)
            return cls(2024, 1, 2, 3, 4, 6, tzinfo=tz)

    logger_module = sys.modules[logging_config.__module__]
    monkeypatch.setattr(logger_module, "datetime", FixedDateTime)

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    logging_config(verbose=True, debug=False, log_file=str(tmp_path))

    logger = logging.getLogger()
    logger.info("hello")

    assert len(logger.handlers) == 2
    output = stream.getvalue()
    info_color = COLORS[logging.INFO]
    assert f"{info_color}Verbose enabled.{RESET}" in output
    assert f"{info_color}hello{RESET}" in output

    log_path = tmp_path / "senpai_log_file_20240102_030406.txt"
    assert log_path.exists()
    file_contents = log_path.read_text(encoding="utf-8")
    assert "Verbose enabled." in file_contents
    assert "hello" in file_contents


def test_logging_config_writes_console_and_file_when_debug(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FixedDateTime":
            if tz is None:
                return cls(2024, 1, 2, 3, 4, 7)
            return cls(2024, 1, 2, 3, 4, 7, tzinfo=tz)

    logger_module = sys.modules[logging_config.__module__]
    monkeypatch.setattr(logger_module, "datetime", FixedDateTime)

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    logging_config(verbose=False, debug=True, log_file=str(tmp_path))

    logger = logging.getLogger()
    logger.debug("debug line")

    assert len(logger.handlers) == 2
    output = stream.getvalue()
    debug_color = COLORS[logging.DEBUG]
    info_color = COLORS[logging.INFO]
    assert f"{info_color}Debug enabled.{RESET}" in output
    assert f"{debug_color}debug line{RESET}" in output

    log_path = tmp_path / "senpai_log_file_20240102_030407.txt"
    assert log_path.exists()
    file_contents = log_path.read_text(encoding="utf-8")
    assert "Debug enabled." in file_contents
    assert "debug line" in file_contents
