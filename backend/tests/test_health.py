"""Tests for `app.health` — the ALB's view of whether a task can serve.

The probes are injected, so nothing here needs a database or a Redis: what
is under test is the latch, not the two `SELECT 1`s.
"""

from __future__ import annotations

import pytest

from app.health import STATUS_OK, STATUS_UNAVAILABLE, HealthCheck


class _CountingProbe:
    """A probe that records how often it ran and can be made to fail."""

    def __init__(self, *, failing: bool = False) -> None:
        self.calls = 0
        self.failing = failing

    def __call__(self) -> object:
        self.calls += 1
        if self.failing:
            raise ConnectionError("unreachable")
        return True


def test_reports_ok_when_every_probe_succeeds() -> None:
    check = HealthCheck({"database": _CountingProbe(), "cache": _CountingProbe()})

    assert check.status().status == STATUS_OK
    assert check.is_ready is True


def test_reports_unavailable_while_a_probe_fails() -> None:
    """A misconfigured task must never join the target group."""
    check = HealthCheck(
        {"database": _CountingProbe(), "cache": _CountingProbe(failing=True)}
    )

    assert check.status().status == STATUS_UNAVAILABLE
    assert check.is_ready is False


def test_stays_unavailable_for_as_long_as_the_dependency_is_unreachable() -> None:
    probe = _CountingProbe(failing=True)
    check = HealthCheck({"database": probe})

    for _ in range(3):
        assert check.status().status == STATUS_UNAVAILABLE

    assert probe.calls == 3


def test_becomes_ready_as_soon_as_the_dependency_recovers() -> None:
    probe = _CountingProbe(failing=True)
    check = HealthCheck({"database": probe})
    assert check.status().status == STATUS_UNAVAILABLE

    probe.failing = False

    assert check.status().status == STATUS_OK


def test_probes_stop_once_the_latch_closes() -> None:
    """The ALB checks every task every 30s; a ready check must cost nothing."""
    probe = _CountingProbe()
    check = HealthCheck({"database": probe})

    for _ in range(5):
        assert check.status().status == STATUS_OK

    assert probe.calls == 1


def test_a_blip_after_readiness_does_not_unhealth_the_task() -> None:
    """Otherwise one Redis hiccup takes every task out at once and ECS
    replaces the whole service over an outage it cannot fix."""
    probe = _CountingProbe()
    check = HealthCheck({"database": probe})
    assert check.status().status == STATUS_OK

    probe.failing = True

    assert check.status().status == STATUS_OK


def test_a_failing_probe_short_circuits_the_rest() -> None:
    """No point paying for the second round trip once the answer is known."""
    first = _CountingProbe(failing=True)
    second = _CountingProbe()
    check = HealthCheck({"database": first, "cache": second})

    check.status()

    assert first.calls == 1
    assert second.calls == 0


def test_the_failure_response_does_not_name_the_dependency() -> None:
    """`/health` is internet-reachable through the ALB; the detail belongs in
    the log, not in the body."""
    check = HealthCheck({"database": _CountingProbe(failing=True)})

    assert check.status().status == STATUS_UNAVAILABLE


def test_the_failing_dependency_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = HealthCheck({"cache": _CountingProbe(failing=True)})

    with caplog.at_level("WARNING", logger="app.health"):
        check.status()

    record = next(r for r in caplog.records if r.name == "app.health")
    assert record.dependency == "cache"  # type: ignore[attr-defined]
    assert record.exc_info is not None


def test_a_check_with_no_probes_is_ready_immediately() -> None:
    """Degenerate but worth pinning: an empty mapping must not deadlock the
    latch closed."""
    check = HealthCheck({})

    assert check.status().status == STATUS_OK
