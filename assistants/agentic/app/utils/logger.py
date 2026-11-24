"""Utility helpers for configuring colorful, level-based logging."""

import logging
from datetime import datetime
from pathlib import Path

RESET = "\033[0m"
COLORS = {
    logging.DEBUG: "\033[90m",  # Gray
    logging.INFO: "\033[92m",  # Green
    logging.WARNING: "\033[93m",  # Yellow
    logging.ERROR: "\033[91m",  # Red
    logging.CRITICAL: "\033[95m",  # Magenta / strong
}


class ColoredFormatter(logging.Formatter):
    """A custom logging formatter that colors log messages and level names based on their severity level.

    This formatter injects ANSI color codes into the `levelname` and `msg`
    fields before passing the record to the parent formatter.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record by applying ANSI color codes depending on the log level.

        Args:
            record (logging.LogRecord): The record to format.

        Returns:
            str: The formatted log message with color applied.
        """
        color = COLORS.get(record.levelno, RESET)
        # Make a shallow copy to avoid mutating the original record
        record = logging.makeLogRecord(record.__dict__)
        record.levelname = f"{color}{record.levelname}{RESET}"
        record.msg = f"{color}{record.msg}{RESET}"
        return super().format(record)


def logging_config(verbose: bool, debug: bool, log_file: str | None = None) -> None:
    """Configure global logging settings based on verbosity flags.

    If either `verbose` or `debug` is enabled, logging output will be
    printed to the console with colored formatting. Debug takes priority
    and sets the logging level to DEBUG. If `verbose` is True and `debug`
    is False, the level is set to INFO.

    If both are False, all logging output is disabled.

    Args:
        verbose (bool): Enable INFO-level logging if True (unless debug is True).
        debug (bool): Enable DEBUG-level logging if True, overriding verbose.
        log_file (str | None): Enables logs saving in the specified directory.

    Returns:
        None
    """
    logger = logging.getLogger()

    if logger.handlers:
        logger.handlers.clear()

    enable_logging = verbose or debug or bool(log_file)
    if not enable_logging:
        logging.disable(logging.CRITICAL)
        return

    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    if verbose or debug:
        console = logging.StreamHandler()
        console.setLevel(level)

        formatter = ColoredFormatter("%(asctime)s [%(levelname)s] (%(name)s) - %(message)s")

        console.setFormatter(formatter)
        logger.addHandler(console)

    if log_file:
        log_path = Path(log_file)
        log_dir = log_path if log_path.is_dir() or log_path.suffix == "" else log_path.parent
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = log_dir / f"senpai_log_file_{timestamp}.txt"
        try:
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to create log file '%s': %s", log_path, exc)
        else:
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] (%(name)s) - %(message)s"))
            logger.addHandler(file_handler)

    if verbose:
        logger.info("Verbose enabled.")

    if debug:
        logger.info("Debug enabled.")
