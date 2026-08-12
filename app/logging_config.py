"""Structured JSON logging configuration.

Configures the root logger (and uvicorn's loggers) to emit one JSON object
per line, carrying `timestamp`, `level`, `message`, and `request_id` fields.
"""

from __future__ import annotations

import logging

from pythonjsonlogger.jsonlogger import JsonFormatter

from app.request_context import RequestIdLogFilter

_UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")

_LOG_FORMAT = "%(levelname)s %(name)s %(message)s %(request_id)s"


def configure_logging(level: str = "INFO") -> None:
    """Configures process-wide structured JSON logging.

    Idempotent: safe to call more than once (e.g. once at module import and
    again from a test), since it always replaces the root logger's handlers
    rather than appending to them.
    """
    formatter = JsonFormatter(
        _LOG_FORMAT,
        rename_fields={"levelname": "level"},
        timestamp=True,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdLogFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    # Route uvicorn's own logs through the same JSON handler instead of its
    # default human-readable formatter, so every log line — app and server
    # alike — is a single JSON object.
    for logger_name in _UVICORN_LOGGER_NAMES:
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
