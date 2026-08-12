"""FastAPI application entry point.

Route handlers here are intentionally thin — they delegate to business
logic classes (e.g. `HealthCheck`) and are only responsible for wiring HTTP
concerns (status codes, response models) to that logic.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cart import router as cart_router
from app.api.deps import get_sql_product_repository
from app.api.products import router as products_router
from app.api.providers import get_product_repository
from app.health import HealthCheck
from app.logging_config import configure_logging
from app.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.models import HealthResponse
from app.session import SessionCookieMiddleware
from app.settings import settings

configure_logging()

app = FastAPI(title="qbiq_h API")

# Middleware order matters, and `add_middleware` prepends: the LAST one added
# is the OUTERMOST layer. `CORSMiddleware` must therefore be added last, so that
# error responses produced further in still pass back out through it. Registered
# the other way round, a 500 reaches the browser stripped of its CORS headers
# and the SPA sees an opaque network failure it cannot distinguish from an
# unreachable server.
app.add_middleware(RequestIdMiddleware)
# Outside RequestIdMiddleware, deliberately. That middleware converts an
# unhandled exception into a 500 response, so from here the failure looks like
# an ordinary response and the session cookie can still be attached to it.
# Registered inside it instead, an exception would propagate straight past this
# layer and a first-time Shopper would lose their session on any error.
app.add_middleware(SessionCookieMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser hides X-Request-Id from JavaScript on any
    # cross-origin response, which defeats the point of echoing it back:
    # correlating a client-side failure with the server log that explains it.
    expose_headers=[REQUEST_ID_HEADER],
)

# One override, deliberately: both routers depend on the same
# `app.api.providers.get_product_repository` key, so the catalogue and the Cart
# are guaranteed to resolve a product id through the same repository. Bound
# here rather than inside either router module so neither imports SQLAlchemy.
app.dependency_overrides[get_product_repository] = get_sql_product_repository

app.include_router(products_router)
app.include_router(cart_router)

_health_check = HealthCheck()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe used by the ALB health check."""
    return _health_check.status()
