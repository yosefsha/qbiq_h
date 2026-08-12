"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response body for `GET /health`."""

    status: str
