"""Tests for `app.logging_config` — one JSON object per log line."""

from __future__ import annotations

import io
import json
import logging

from app.logging_config import configure_logging
from app.request_context import reset_request_id, set_request_id


def test_logs_are_single_line_json_with_required_fields() -> None:
    configure_logging()

    root_logger = logging.getLogger()
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream

    token = set_request_id("test-request-id")
    try:
        logging.getLogger("app.test").info("hello world")
    finally:
        reset_request_id(token)

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["message"] == "hello world"
    assert record["level"] == "INFO"
    assert record["request_id"] == "test-request-id"
    assert "timestamp" in record


def test_request_id_defaults_to_placeholder_outside_request_context() -> None:
    configure_logging()

    root_logger = logging.getLogger()
    stream = io.StringIO()
    root_logger.handlers[0].stream = stream

    logging.getLogger("app.test").info("no request in flight")

    record = json.loads(stream.getvalue().splitlines()[0])
    assert record["request_id"] == "-"
