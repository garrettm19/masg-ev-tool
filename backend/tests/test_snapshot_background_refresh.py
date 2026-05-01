"""
Tests for the background-refresh path on POST /api/opportunities/refresh.

Covers:
  - POST returns 202 with the new status fields
  - start_background_refresh() returns immediately even with a slow pipeline
  - Concurrent calls do not spawn duplicate refreshes
  - /status exposes refresh_started_at, last_refresh_error, duration, last_trigger
  - Background errors are captured in last_refresh_error, not raised to client

Note: FastAPI's TestClient drains pending asyncio tasks before returning, so
"in-flight" assertions on the HTTP endpoint don't work — those concurrency
tests exercise start_background_refresh() directly via asyncio.run().
"""
import asyncio
import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from services.snapshot import (
    store_snapshot,
    clear_snapshot,
    is_refreshing,
    start_background_refresh,
)
from services import snapshot as _snap_mod
from services.opportunities import EvaluatedOpportunity

client = TestClient(app)


def _make_opp() -> EvaluatedOpportunity:
    return EvaluatedOpportunity(
        platform="polymarket",
        sport="tennis_atp",
        event="A vs B",
        event_url=None,
        tournament="ATP",
        start_time="2026-06-01T12:00:00Z",
        market_id="m1",
        market_type="h2h",
        side="A",
        line=None,
        pm_price=0.55,
        fd_odds=-180,
        p_true=0.65,
        edge=0.08,
        recommended_kelly=0.02,
        kelly_full=0.10,
        fanduel_overround=0.02,
        fanduel_line_width=0.20,
        fanduel_line_width_label="Moderate",
        fanduel_confidence_label="High",
        event_match_confidence=0.95,
        match_quality="verified",
        matched_event_id="ev1",
        second_best_event_id="",
        confidence_gap=1.0,
        competing_matches=1,
        has_shared_last_name=False,
        status="BUY",
        reject_reasons=[],
        downgrade_reasons=[],
        home_tokens=("a",),
        away_tokens=("b",),
        name_match_score=1.0,
        date_score=1.0,
        date_delta_hours=2.0,
        rule_evaluations=[],
    )


def _wait_until(condition, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _wait_until_idle(timeout: float = 5.0) -> bool:
    return _wait_until(lambda: not is_refreshing(), timeout=timeout)


@pytest.fixture(autouse=True)
def _clean():
    clear_snapshot()
    yield
    _wait_until_idle(timeout=3.0)
    clear_snapshot()


# ---------------------------------------------------------------------------
# Non-blocking POST /refresh
# ---------------------------------------------------------------------------

class TestPostRefreshEndpoint:
    def test_returns_202_with_extended_status_shape(self):
        """POST /refresh returns 202 with all the new status fields populated."""
        async def quick(trigger="manual", **kwargs):
            return store_snapshot([_make_opp()], {"status_counts": {"BUY": 1}}, trigger=trigger)

        with patch("services.snapshot.refresh_snapshot", side_effect=quick):
            resp = client.post("/api/opportunities/refresh")
            assert _wait_until_idle(timeout=3.0)

        assert resp.status_code == 202
        body = resp.json()
        assert "refresh_started_at" in body
        assert "last_refresh_error" in body
        assert "last_refresh_duration_seconds" in body
        assert "last_trigger" in body
        assert body["last_trigger"] == "manual"


# ---------------------------------------------------------------------------
# Background spawn — tested directly via asyncio.run because TestClient
# drains pending tasks before returning, so HTTP-level timing tests don't
# observe the in-flight state.
# ---------------------------------------------------------------------------

class TestStartBackgroundRefresh:
    def test_returns_immediately_even_with_slow_pipeline(self):
        """start_background_refresh awaits only the spawn, not the pipeline."""
        async def slow(trigger="manual", **kwargs):
            await asyncio.sleep(0.5)
            return store_snapshot([_make_opp()], {"status_counts": {}}, trigger=trigger)

        async def run():
            with patch("services.snapshot.refresh_snapshot", side_effect=slow):
                t0 = time.time()
                state = await start_background_refresh()
                elapsed_to_spawn = time.time() - t0

                assert state["started"] is True
                assert state["already_running"] is False
                assert state["started_at"] is not None
                # Spawn should be effectively instant
                assert elapsed_to_spawn < 0.1, f"spawn took {elapsed_to_spawn:.3f}s"
                # Background task is in flight
                assert is_refreshing() is True

                # Wait for the task to drain before exit
                if _snap_mod._background_task is not None:
                    await _snap_mod._background_task

        asyncio.run(run())
        assert is_refreshing() is False

    def test_concurrent_calls_do_not_spawn_duplicate(self):
        """Two awaits of start_background_refresh while one is running yield one spawn."""
        spawn_count = {"n": 0}

        async def slow(trigger="manual", **kwargs):
            spawn_count["n"] += 1
            await asyncio.sleep(0.2)
            return store_snapshot([_make_opp()], {"status_counts": {}}, trigger=trigger)

        async def run():
            with patch("services.snapshot.refresh_snapshot", side_effect=slow):
                # Fire two starts back-to-back; second should detect already-running
                s1 = await start_background_refresh()
                s2 = await start_background_refresh()

                assert s1["started"] is True
                assert s2["started"] is False
                assert s2["already_running"] is True
                assert s2["started_at"] == s1["started_at"]

                # Drain
                if _snap_mod._background_task is not None:
                    await _snap_mod._background_task

        asyncio.run(run())
        # Pipeline ran exactly once despite two start calls
        assert spawn_count["n"] == 1

    def test_in_flight_state_visible_during_refresh(self):
        """While the task is in flight, is_refreshing() and refresh_started_at are set."""
        observed = {}

        async def slow(trigger="manual", **kwargs):
            # Snapshot the state at the moment the pipeline body is running
            observed["is_refreshing_during"] = is_refreshing()
            observed["refresh_started_at_during"] = _snap_mod._refresh_started_at
            observed["last_trigger_during"] = _snap_mod._last_trigger
            return store_snapshot([_make_opp()], {"status_counts": {}}, trigger=trigger)

        async def run():
            with patch("services.snapshot.refresh_snapshot", side_effect=slow):
                await start_background_refresh()
                if _snap_mod._background_task is not None:
                    await _snap_mod._background_task

        asyncio.run(run())

        assert observed["is_refreshing_during"] is True
        assert observed["refresh_started_at_during"] is not None
        assert observed["last_trigger_during"] == "manual"


# ---------------------------------------------------------------------------
# /status reflects post-completion state
# ---------------------------------------------------------------------------

class TestStatusFieldsAfterCompletion:
    def test_status_after_completion_records_duration(self):
        async def quick(trigger="manual", **kwargs):
            return store_snapshot([_make_opp()], {"status_counts": {"BUY": 1}}, trigger=trigger)

        with patch("services.snapshot.refresh_snapshot", side_effect=quick):
            client.post("/api/opportunities/refresh")
            assert _wait_until(
                lambda: not is_refreshing()
                and _snap_mod._last_refresh_duration_seconds is not None,
                timeout=3.0,
            )

        body = client.get("/api/opportunities/status").json()
        assert body["is_refreshing"] is False
        assert body["refresh_started_at"] is None
        assert body["last_refresh_duration_seconds"] is not None
        assert body["last_refresh_duration_seconds"] >= 0
        assert body["last_refresh_error"] is None
        assert body["last_trigger"] == "manual"
        assert body["trigger"] == "manual"  # snapshot.trigger from successful run
        assert body["has_snapshot"] is True


# ---------------------------------------------------------------------------
# Errors are captured, not raised
# ---------------------------------------------------------------------------

class TestErrorCapture:
    def test_pipeline_error_recorded_in_last_refresh_error(self):
        async def failing(trigger="manual", **kwargs):
            raise RuntimeError("simulated pipeline failure")

        with patch("services.snapshot.refresh_snapshot", side_effect=failing):
            resp = client.post("/api/opportunities/refresh")
            assert resp.status_code == 202

            assert _wait_until(
                lambda: not is_refreshing()
                and _snap_mod._last_refresh_error is not None,
                timeout=3.0,
            )

        body = client.get("/api/opportunities/status").json()
        assert body["is_refreshing"] is False
        assert body["last_refresh_error"] is not None
        assert "simulated" in body["last_refresh_error"]
        # Error type is included in the captured message
        assert "RuntimeError" in body["last_refresh_error"]
        # Last trigger is recorded even on failure
        assert body["last_trigger"] == "manual"

    def test_value_error_recorded(self):
        async def failing(trigger="manual", **kwargs):
            raise ValueError("ODDS_API_KEY environment variable is not set")

        with patch("services.snapshot.refresh_snapshot", side_effect=failing):
            resp = client.post("/api/opportunities/refresh")
            assert resp.status_code == 202
            assert _wait_until_idle(timeout=3.0)

        body = client.get("/api/opportunities/status").json()
        assert body["is_refreshing"] is False
        assert body["last_refresh_error"] is not None
        assert "ODDS_API_KEY" in body["last_refresh_error"]


# ---------------------------------------------------------------------------
# /status response shape includes all required fields
# ---------------------------------------------------------------------------

class TestStatusResponseShape:
    def test_empty_state_exposes_all_fields(self):
        body = client.get("/api/opportunities/status").json()
        for f in [
            "has_snapshot",
            "updated_at",
            "is_refreshing",
            "refresh_started_at",
            "last_refresh_error",
            "last_refresh_duration_seconds",
            "trigger",
            "last_trigger",
            "opportunity_count",
            "status_counts",
            "platforms_fetched",
        ]:
            assert f in body, f"missing field: {f}"
        # Initial state values
        assert body["has_snapshot"] is False
        assert body["is_refreshing"] is False
        assert body["refresh_started_at"] is None
        assert body["last_refresh_error"] is None
        assert body["last_refresh_duration_seconds"] is None
        assert body["last_trigger"] is None
