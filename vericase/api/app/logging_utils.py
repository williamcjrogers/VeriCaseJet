import logging
import re
from typing import Any

_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitize_log_value(value: Any, max_length: int = 512) -> str:
    """
    Normalize user-controlled values before they reach log sinks.

    Replaces newline characters, strips standard control characters, and limits
    the final length so attackers cannot forge multi-line log entries.
    """
    if value is None:
        return "<none>"

    text = str(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    text = _CONTROL_CHAR_PATTERN.sub("?", text)

    if len(text) > max_length:
        text = text[:max_length] + "...[truncated]"

    return text


class LogSanitizerFilter(logging.Filter):
    """Filter that sanitizes log arguments to prevent log injection."""

    def __init__(self, max_length: int = 512):
        super().__init__("vericase-log-sanitizer")
        self.max_length = max_length

    def filter(
        self, record: logging.LogRecord
    ) -> bool:  # pragma: no cover - exercised via logging
        if not record.args:
            record.msg = sanitize_log_value(record.msg, self.max_length)
            return True

        if isinstance(record.args, tuple):
            record.args = tuple(
                sanitize_log_value(arg, self.max_length) for arg in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: sanitize_log_value(val, self.max_length)
                for key, val in record.args.items()
            }
        else:
            try:
                record.args = tuple(
                    sanitize_log_value(arg, self.max_length) for arg in record.args  # type: ignore[arg-type]
                )
            except TypeError:
                record.args = sanitize_log_value(record.args, self.max_length)

        return True


def install_log_sanitizer(
    target_logger: logging.Logger | None = None, max_length: int = 512
) -> None:
    """
    Attach the sanitizer filter to the provided logger (defaults to root).

    This runs once per process; subsequent calls are ignored.
    """
    logger = target_logger or logging.getLogger()
    for existing in logger.filters:
        if isinstance(existing, LogSanitizerFilter):
            return
    logger.addFilter(LogSanitizerFilter(max_length))
