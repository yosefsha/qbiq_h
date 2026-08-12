"""Structured JSON logging configuration.

Configures the root logger (and uvicorn's loggers) to emit one JSON object
per line, carrying `timestamp`, `level`, `message`, and `request_id` fields.
"""

from __future__ import annotations

import logging

# `pythonjsonlogger.jsonlogger` is the pre-3.1 path and is deprecated; the
# package now lives at `pythonjsonlogger.json`. Importing the old path emits a
# DeprecationWarning today and breaks outright once the shim is dropped — a
# failure that would first appear in a freshly built image, never on a machine
# with an older version already resolved. requirements.txt floors the version
# accordingly.
from pythonjsonlogger.json import JsonFormatter

from app.request_context import RequestIdLogFilter
from app.settings import settings

_UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")

_LOG_FORMAT = "%(levelname)s %(name)s %(message)s %(request_id)s"


def configure_logging(level: str | None = None) -> None:
    """Configures process-wide structured JSON logging.

    Level defaults to `LOG_LEVEL` from the environment, so third-party log
    volume can be turned down in production without a code change.

    Idempotent: safe to call more than once (e.g. once at module import and
    again from a test), since it always replaces the root logger's handlers
    rather than appending to them.
    """
    level = level or settings.log_level
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
