import logging
import os
import sys


_RESET = "\x1b[0m"
_LEVEL_COLORS = {
    "DEBUG": "\x1b[36m",
    "INFO": "\x1b[32m",
    "WARNING": "\x1b[33m",
    "ERROR": "\x1b[31m",
    "CRITICAL": "\x1b[35m",
}


class ColorFormatter(logging.Formatter):
    def __init__(self, fmt: str, datefmt: str, use_color: bool) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        if self.use_color:
            color = _LEVEL_COLORS.get(original_levelname)
            if color:
                record.levelname = f"{color}{original_levelname}{_RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


def _supports_color(stream) -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def setup_logging(verbose: bool = False) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers = []

    if not verbose:
        logging.disable(logging.CRITICAL)
        return

    logging.disable(logging.NOTSET)
    level = logging.DEBUG
    root_logger.setLevel(level)

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = ColorFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
        use_color=_supports_color(sys.stdout),
    )
    handler.setFormatter(formatter)

    root_logger.handlers = [handler]
