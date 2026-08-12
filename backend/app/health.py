"""Health check business logic.

`GET /health` is the ALB target group's health check, and ECS replaces any
task the target group calls unhealthy. That gives the check two jobs that
pull in opposite directions:

- It has to be able to fail. A check that returns 200 without ever touching
  Postgres or Redis cannot tell a working task from one that was handed the
  wrong connection details — the task boots, answers 200, joins the target
  group, and returns 500 to every real request. A green health check that
  means nothing is worse than a red one.
- It must not amplify an outage. If every task probed its dependencies on
  every check, a ten-second Redis blip would fail every task at once, ECS
  would replace all of them, and the service would still be cycling long
  after the blip was over.

The resolution is a **latch**: the dependencies are probed until they answer
once, and from then on the check is a constant-time read of a boolean.

That distinguishes exactly the failure that matters. A misconfigured task
never latches, never becomes healthy, and the deployment circuit breaker
rolls the release back with the reason in the log. A task that has already
proven its configuration keeps passing through a dependency blip, because
the blip says nothing about whether *that task* is correctly configured —
and the requests that actually need the dependency fail loudly on their own
account while it lasts.

The probes are injected rather than reached for, so the branch logic here is
tested without a database or a Redis anywhere near it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models import HealthResponse
from app.redis_client import get_sync_redis_client

logger = logging.getLogger("app.health")

#: Body of a passing check. Kept as a constant because the ALB matches on the
#: status code, but the tests and the runbook match on this string.
STATUS_OK = "ok"

#: Body of a failing check. The response deliberately does not name the
#: dependency that failed: `/health` is reachable from the internet through
#: the ALB, and which of two backing stores an anonymous caller can see is
#: not something worth publishing. The name and the traceback go to the log,
#: which is where an operator is looking anyway.
STATUS_UNAVAILABLE = "unavailable"

#: A probe raises to signal failure and returns anything at all to signal
#: success — `Redis.ping()` returns a bool, `Session.execute()` a Result.
Probe = Callable[[], object]


class HealthCheck:
    """Reports whether the service is up and able to serve requests."""

    def __init__(self, probes: Mapping[str, Probe]) -> None:
        self._probes = dict(probes)
        self._ready = False

    @property
    def is_ready(self) -> bool:
        """True once every probe has succeeded at least once."""
        return self._ready

    def status(self) -> HealthResponse:
        """Returns the current health status.

        Once latched this performs no I/O at all, so the ALB's every-30s
        check against every task costs nothing.
        """
        if self._ready:
            return HealthResponse(status=STATUS_OK)

        for name, probe in self._probes.items():
            try:
                probe()
            except Exception:
                # Never fatal: this runs on a request thread serving the ALB,
                # and the useful outcome is a 503 plus a log line naming the
                # dependency, not a 500 with a stack trace the ALB discards.
                logger.warning(
                    "health check dependency unavailable",
                    extra={"dependency": name},
                    exc_info=True,
                )
                return HealthResponse(status=STATUS_UNAVAILABLE)

        self._ready = True
        logger.info("health check dependencies reachable; task is ready")
        return HealthResponse(status=STATUS_OK)


def _probe_database() -> object:
    """Opens a connection from the pool and runs the cheapest possible query."""
    with SessionLocal() as session:
        return session.execute(text("SELECT 1")).scalar_one()


def _probe_cache() -> object:
    """Pings Redis over the process-wide sync client's pool.

    That client carries a 3-second socket timeout (see `app.redis_client`),
    so an unreachable node fails the probe rather than pinning the worker
    that is serving the ALB.
    """
    return get_sync_redis_client().ping()


def default_health_check() -> HealthCheck:
    """Builds the `HealthCheck` the application serves `/health` from.

    Both stores are checked because both are required to serve a request:
    Postgres holds the catalogue and Redis holds Sessions and Carts, which
    ADR-003 treats as state rather than cache. A task that can reach only
    one of them is misconfigured, not degraded.
    """
    return HealthCheck({"database": _probe_database, "cache": _probe_cache})
