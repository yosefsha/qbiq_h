"""Request id middleware.

Assigns every incoming request a unique id (or reuses an inbound
`X-Request-Id` header), makes it available to structured logging via
`app.request_context`, echoes it back on the response, and logs request
start/completion.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.request_context import generate_request_id, reset_request_id, set_request_id

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-Id"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attaches a request id to each request and logs its lifecycle."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER, generate_request_id())
        token = set_request_id(request_id)
        try:
            logger.info(
                "request started",
                extra={"method": request.method, "path": request.url.path},
            )
            response = await call_next(request)
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
