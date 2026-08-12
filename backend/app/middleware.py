"""Request id middleware.

Assigns every incoming request a unique id (or reuses a well-formed inbound
`X-Request-Id` header), makes it available to structured logging via
`app.request_context`, echoes it back on the response, and logs the request
lifecycle including failures.
"""

from __future__ import annotations

import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.request_context import generate_request_id, reset_request_id, set_request_id

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-Id"

# An inbound request id is client-controlled input that we copy into every log
# line for the request and echo back in a response header. Constrain it so a
# caller cannot inject newlines into the log stream or make each request carry
# kilobytes of attacker-chosen text into CloudWatch.
_MAX_REQUEST_ID_LENGTH = 128
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{1,%d}$" % _MAX_REQUEST_ID_LENGTH)


def _resolve_request_id(request: Request) -> str:
    """Returns a safe request id, preferring a well-formed inbound header."""
    inbound = request.headers.get(REQUEST_ID_HEADER)
    if inbound is not None and _REQUEST_ID_PATTERN.match(inbound):
        return inbound
    return generate_request_id()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attaches a request id to each request and logs its lifecycle."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = _resolve_request_id(request)
        token = set_request_id(request_id)
        try:
            logger.info(
                "request started",
                extra={"method": request.method, "path": request.url.path},
            )
            try:
                response = await call_next(request)
            except Exception:
                # Log the failure ourselves and convert it into a response here,
                # rather than re-raising. Two reasons: an unhandled exception
                # that escapes this middleware is turned into a bare 500 by
                # Starlette's outermost error handler without ever passing back
                # through CORSMiddleware, and it would otherwise leave a
                # "request started" line with no matching outcome — so the
                # CloudWatch 5xx alarm fires with nothing to diagnose it.
                logger.exception(
                    "request failed",
                    extra={"method": request.method, "path": request.url.path},
                )
                response = JSONResponse(
                    status_code=500, content={"detail": "Internal Server Error"}
                )
                response.headers[REQUEST_ID_HEADER] = request_id
                return response

            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )
            return response
        finally:
            reset_request_id(token)
