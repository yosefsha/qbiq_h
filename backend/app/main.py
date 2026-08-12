"""FastAPI application entry point.

Route handlers here are intentionally thin — they delegate to business
logic classes (e.g. `HealthCheck`) and are only responsible for wiring HTTP
concerns (status codes, response models) to that logic.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.health import HealthCheck
from app.logging_config import configure_logging
from app.middleware import RequestIdMiddleware
from app.models import HealthResponse
from app.settings import settings

configure_logging()

app = FastAPI(title="qbiq_h API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)

_health_check = HealthCheck()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe used by the ALB health check."""
    return _health_check.status()
