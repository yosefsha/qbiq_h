"""Per-request context propagation for structured logging.

Holds the current request id in a `contextvars.ContextVar` so any log
statement emitted while handling a request — regardless of call depth — can
be tagged with that request's id without threading it through every
function signature.
"""

from __future__ import annotations

import contextvars
import logging
import uuid

_NO_REQUEST_ID = "-"

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=_NO_REQUEST_ID
)


def generate_request_id() -> str:
    """Generates a new opaque request id."""
    return str(uuid.uuid4())


def set_request_id(request_id: str) -> contextvars.Token[str]:
    """Sets the current request id, returning a token for `reset_request_id`."""
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Restores the request id that was current before `set_request_id`."""
    _request_id_var.reset(token)


def get_request_id() -> str:
    """Returns the current request id, or `-` outside of a request context."""
    return _request_id_var.get()


class RequestIdLogFilter(logging.Filter):
    """Injects the current request id into every log record as `request_id`."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True
