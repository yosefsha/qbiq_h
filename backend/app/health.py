"""Liveness check business logic."""

from __future__ import annotations

from app.models import HealthResponse


class HealthCheck:
    """Reports whether the service is up and able to serve requests."""

    def status(self) -> HealthResponse:
        """Returns the current health status."""
        return HealthResponse(status="ok")
