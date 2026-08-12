"""Tests for the failure paths through the middleware stack.

These cover behaviour that only shows up when a handler raises: that the
response still carries CORS headers, that the request id survives, and that
the failure is actually logged.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.middleware import REQUEST_ID_HEADER

ORIGIN = "http://localhost:5173"


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    """A client whose app has one route that always raises."""
    if not any(getattr(route, "path", None) == "/boom" for route in app.routes):

        @app.get("/boom")
        def boom() -> None:
            raise RuntimeError("deliberate failure")

    return TestClient(app, raise_server_exceptions=False)


def test_failing_request_still_carries_cors_headers(client: TestClient) -> None:
    """A 500 must remain readable by the SPA.

    If CORSMiddleware is inner to RequestIdMiddleware, the error response
    reaches the browser without `access-control-allow-origin` and the SPA
    cannot tell a server error from an unreachable server.
    """
    response = client.get("/boom", headers={"Origin": ORIGIN})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_failing_request_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/boom", headers={"Origin": ORIGIN})

    assert response.headers[REQUEST_ID_HEADER]


def test_request_id_is_exposed_to_cross_origin_javascript(client: TestClient) -> None:
    """Without expose_headers the browser hides the id from `fetch` callers."""
    response = client.get("/health", headers={"Origin": ORIGIN})

    exposed = response.headers["access-control-expose-headers"]
    assert REQUEST_ID_HEADER.lower() in exposed.lower()


def test_failure_is_logged_with_a_traceback(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """A 5xx alarm is useless without a log line explaining it."""
    with caplog.at_level(logging.ERROR, logger="app.request"):
        client.get("/boom", headers={"Origin": ORIGIN})

    failures = [r for r in caplog.records if r.message == "request failed"]
    assert len(failures) == 1
    assert failures[0].exc_info is not None


def test_well_formed_inbound_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: "abc-123_XYZ.4"})

    assert response.headers[REQUEST_ID_HEADER] == "abc-123_XYZ.4"


@pytest.mark.parametrize(
    "hostile",
    [
        "has spaces",
        "semi;colon,delimited",
        "x" * 129,
        "<script>alert(1)</script>",
        "",
    ],
)
def test_malformed_inbound_request_id_is_replaced(
    client: TestClient, hostile: str
) -> None:
    """Client-controlled input reaches every log line, so it must be constrained."""
    response = client.get("/health", headers={REQUEST_ID_HEADER: hostile})

    assert response.headers[REQUEST_ID_HEADER] != hostile
