"""
Tests for snapshot API endpoints.

Covers:
  - GET  /snapshot  — pure read, 204 when empty, filters
  - GET  /status    — lightweight metadata read
  - POST /refresh   — schedules a background refresh, returns 202 immediately
"""
import time
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from services.snapshot import store_snapshot, clear_snapshot, get_snapshot, is_refreshing
from services import snapshot as _snap_mod
from services.opportunities import EvaluatedOpportunity

client = TestClient(app)


def _wait_until_idle(timeout: float = 5.0) -> bool:
    """Poll until no background refresh is in flight, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_refreshing():
            return True
        time.sleep(0.02)
    return False


def _make_opp(
    platform: str = "polymarket",
    market_id: str = "m1",
    side: str = "Alcaraz",
    edge: float = 0.08,
    status: str = "BUY",
) -> EvaluatedOpportunity:
    return EvaluatedOpportunity(
        platform=platform,
        sport="tennis_atp",
        event="A vs B",
        event_url=None,
        tournament="ATP",
        start_time="2026-06-01T12:00:00Z",
        market_id=market_id,
        market_type="h2h",
        side=side,
        line=None,
        pm_price=0.55,
        fd_odds=-180,
        p_true=0.65,
        edge=edge,
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
        status=status,
        reject_reasons=[],
        downgrade_reasons=[],
        home_tokens=("carlos", "alcaraz"),
        away_tokens=("jannik", "sinner"),
        name_match_score=1.0,
        date_score=1.0,
        date_delta_hours=2.0,
        rule_evaluations=[],
    )


@pytest.fixture(autouse=True)
def _clean():
    clear_snapshot()
    yield
    _wait_until_idle(timeout=3.0)
    clear_snapshot()


# ---------------------------------------------------------------------------
# GET /api/opportunities/snapshot
# ---------------------------------------------------------------------------

class TestSnapshotEndpoint:
    def test_returns_204_when_empty(self):
        resp = client.get("/api/opportunities/snapshot")
        assert resp.status_code == 204

    def test_returns_cached_data(self):
        opps = [_make_opp(edge=0.08), _make_opp(market_id="m2", edge=0.05)]
        meta = {
            "status_counts": {"BUY": 2, "WATCH": 0, "SKIP": 0},
            "platforms_fetched": ["polymarket"],
            "sportsbook_markets_fetched": ["h2h"],
            "markets_dropped_by_type": {},
        }
        store_snapshot(opps, meta, trigger="test")

        resp = client.get("/api/opportunities/snapshot")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["updated_at"] is not None
        assert body["updated_at"] > 0
        assert body["is_refreshing"] is False
        assert body["status_counts"]["BUY"] == 2

    def test_platform_filter(self):
        opps = [
            _make_opp(platform="polymarket", market_id="pm1"),
            _make_opp(platform="kalshi", market_id="k1"),
        ]
        store_snapshot(opps, {"status_counts": {"BUY": 2}}, trigger="test")

        resp = client.get("/api/opportunities/snapshot?platform=kalshi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["opportunities"][0]["platform"] == "kalshi"

    def test_include_watch_false(self):
        opps = [
            _make_opp(status="BUY", market_id="m1"),
            _make_opp(status="WATCH", market_id="m2"),
        ]
        store_snapshot(opps, {"status_counts": {"BUY": 1, "WATCH": 1}}, trigger="test")

        resp = client.get("/api/opportunities/snapshot?include_watch=false")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["opportunities"][0]["status"] == "BUY"

    def test_does_not_trigger_pipeline(self):
        """Calling snapshot 10 times with no snapshot should never run the pipeline."""
        for _ in range(10):
            resp = client.get("/api/opportunities/snapshot")
            assert resp.status_code == 204
        # If pipeline ran, it would fail (no ODDS_API_KEY) or take seconds.
        # 10 instant 204s proves no pipeline execution.


# ---------------------------------------------------------------------------
# GET /api/opportunities/status
# ---------------------------------------------------------------------------

class TestStatusEndpoint:
    def test_empty_state(self):
        resp = client.get("/api/opportunities/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_snapshot"] is False
        assert body["updated_at"] is None
        assert body["is_refreshing"] is False
        assert body["trigger"] is None
        assert body["opportunity_count"] == 0

    def test_with_snapshot(self):
        opps = [_make_opp(), _make_opp(market_id="m2")]
        meta = {
            "status_counts": {"BUY": 2, "WATCH": 0, "SKIP": 3},
            "platforms_fetched": ["polymarket", "kalshi"],
        }
        store_snapshot(opps, meta, trigger="scheduled")

        resp = client.get("/api/opportunities/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_snapshot"] is True
        assert body["updated_at"] > 0
        assert body["trigger"] == "scheduled"
        assert body["opportunity_count"] == 2
        assert body["status_counts"]["BUY"] == 2
        assert "polymarket" in body["platforms_fetched"]

    def test_is_lightweight(self):
        """Status endpoint should not return opportunity data — just metadata."""
        opps = [_make_opp() for _ in range(50)]
        store_snapshot(opps, {"status_counts": {"BUY": 50}}, trigger="test")

        resp = client.get("/api/opportunities/status")
        body = resp.json()
        assert "opportunities" not in body
        assert body["opportunity_count"] == 50


# ---------------------------------------------------------------------------
# POST /api/opportunities/refresh
# ---------------------------------------------------------------------------

class TestRefreshEndpoint:
    def test_refresh_updates_snapshot_and_returns_202(self):
        """POST /refresh schedules background pipeline; eventually stores snapshot."""
        fake_opps = [_make_opp(edge=0.10), _make_opp(market_id="m2", edge=0.06)]
        fake_meta = {
            "status_counts": {"BUY": 2, "WATCH": 0, "SKIP": 5},
            "platforms_fetched": ["polymarket", "kalshi"],
        }

        async def _mock_fetch(cfg=None):
            return fake_opps, fake_meta

        with patch("services.opportunities.fetch_opportunities", side_effect=_mock_fetch):
            resp = client.post("/api/opportunities/refresh")
            assert resp.status_code == 202
            # Wait for the background task to finish
            assert _wait_until_idle(timeout=3.0)

        # Snapshot should now be readable via GET /snapshot
        snap_resp = client.get("/api/opportunities/snapshot")
        assert snap_resp.status_code == 200
        snap_body = snap_resp.json()
        assert snap_body["total"] == 2
        assert snap_body["status_counts"]["BUY"] == 2

        # /status reflects the completed manual refresh
        st_resp = client.get("/api/opportunities/status")
        st_body = st_resp.json()
        assert st_body["has_snapshot"] is True
        assert st_body["trigger"] == "manual"
        assert st_body["last_trigger"] == "manual"
        assert st_body["last_refresh_error"] is None
        assert st_body["last_refresh_duration_seconds"] is not None

    def test_refresh_value_error_captured_not_raised(self):
        """ValueError in the pipeline lands in last_refresh_error; endpoint still returns 202."""
        async def _mock_fetch(cfg=None):
            raise ValueError("ODDS_API_KEY environment variable is not set")

        with patch("services.opportunities.fetch_opportunities", side_effect=_mock_fetch):
            resp = client.post("/api/opportunities/refresh")
            assert resp.status_code == 202
            assert _wait_until_idle(timeout=3.0)

        st = client.get("/api/opportunities/status").json()
        assert st["is_refreshing"] is False
        assert st["last_refresh_error"] is not None
        assert "ODDS_API_KEY" in st["last_refresh_error"]

    def test_refresh_unexpected_error_captured_not_raised(self):
        async def _mock_fetch(cfg=None):
            raise RuntimeError("something broke")

        with patch("services.opportunities.fetch_opportunities", side_effect=_mock_fetch):
            resp = client.post("/api/opportunities/refresh")
            assert resp.status_code == 202
            assert _wait_until_idle(timeout=3.0)

        st = client.get("/api/opportunities/status").json()
        assert st["is_refreshing"] is False
        assert st["last_refresh_error"] is not None
        assert "something broke" in st["last_refresh_error"]

    def test_polling_flow_status_then_snapshot(self):
        """
        Simulates the frontend polling flow:
        1. GET /status → has_snapshot=false
        2. POST /refresh → 202, refresh runs in background
        3. wait for completion → GET /status → has_snapshot=true
        4. GET /snapshot → returns data matching that updated_at
        """
        resp = client.get("/api/opportunities/status")
        assert resp.json()["has_snapshot"] is False

        fake_opps = [_make_opp(edge=0.09)]
        fake_meta = {"status_counts": {"BUY": 1}, "platforms_fetched": ["polymarket"]}

        async def _mock_fetch(cfg=None):
            return fake_opps, fake_meta

        with patch("services.opportunities.fetch_opportunities", side_effect=_mock_fetch):
            resp = client.post("/api/opportunities/refresh")
            assert resp.status_code == 202
            assert _wait_until_idle(timeout=3.0)

        # Status reflects the new snapshot
        resp = client.get("/api/opportunities/status")
        body = resp.json()
        assert body["has_snapshot"] is True
        assert body["opportunity_count"] == 1
        refresh_ts = body["updated_at"]
        assert refresh_ts is not None

        # Snapshot returns the same data
        resp = client.get("/api/opportunities/snapshot")
        assert resp.status_code == 200
        snap = resp.json()
        assert snap["total"] == 1
        assert snap["updated_at"] == refresh_ts
        assert snap["opportunities"][0]["edge"] == 0.09

    def test_refresh_does_not_affect_monitor(self):
        """POST /refresh should not start/stop/modify the scheduler."""
        fake_opps = [_make_opp()]

        async def _mock_fetch(cfg=None):
            return fake_opps, {"status_counts": {"BUY": 1}}

        with patch("services.opportunities.fetch_opportunities", side_effect=_mock_fetch):
            resp = client.post("/api/opportunities/refresh")
            assert resp.status_code == 202
            assert _wait_until_idle(timeout=3.0)

        from routers import monitor
        assert monitor._scheduler is None
