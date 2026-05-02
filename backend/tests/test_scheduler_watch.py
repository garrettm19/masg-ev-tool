"""
Tests for MonitorScheduler._update_watch_lists — WS consumer watch population.

Covers:
  - Polymarket market_ids routed to pm_ws
  - Kalshi market_ids routed to kalshi_ws
  - SKIP opportunities excluded
  - Empty results don't call watch
"""
import pytest
from unittest.mock import MagicMock

from services.monitor.scheduler import MonitorScheduler
from services.monitor.config import MonitorConfig
from services.opportunities import EvaluatedOpportunity


def _make_opp(
    platform: str = "polymarket",
    market_id: str = "m1",
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
        status=status,
        reject_reasons=[],
        downgrade_reasons=[],
        home_tokens=(),
        away_tokens=(),
        name_match_score=1.0,
        date_score=1.0,
        date_delta_hours=2.0,
        rule_evaluations=[],
    )


def _make_scheduler() -> MonitorScheduler:
    cfg = MonitorConfig(enabled=True, dry_run=True)
    s = MonitorScheduler(monitor_config=cfg)
    # Replace WS consumers with mocks
    s.pm_ws = MagicMock()
    s.kalshi_ws = MagicMock()
    return s


class TestUpdateWatchLists:
    def test_polymarket_ids_routed(self):
        s = _make_scheduler()
        opps = [
            _make_opp(platform="polymarket", market_id="pm_abc"),
            _make_opp(platform="polymarket", market_id="pm_def"),
        ]
        s._update_watch_lists(opps)
        s.pm_ws.watch.assert_called_once_with({"pm_abc", "pm_def"})
        s.kalshi_ws.watch.assert_not_called()

    def test_kalshi_tickers_routed(self):
        s = _make_scheduler()
        opps = [
            _make_opp(platform="kalshi", market_id="KXATPMATCH-A"),
        ]
        s._update_watch_lists(opps)
        s.kalshi_ws.watch.assert_called_once_with({"KXATPMATCH-A"})
        s.pm_ws.watch.assert_not_called()

    def test_mixed_platforms(self):
        s = _make_scheduler()
        opps = [
            _make_opp(platform="polymarket", market_id="pm_1"),
            _make_opp(platform="kalshi", market_id="k_1"),
        ]
        s._update_watch_lists(opps)
        s.pm_ws.watch.assert_called_once_with({"pm_1"})
        s.kalshi_ws.watch.assert_called_once_with({"k_1"})

    def test_skip_excluded(self):
        s = _make_scheduler()
        opps = [
            _make_opp(platform="polymarket", market_id="pm_skip", status="SKIP"),
            _make_opp(platform="polymarket", market_id="pm_buy", status="BUY"),
        ]
        s._update_watch_lists(opps)
        s.pm_ws.watch.assert_called_once_with({"pm_buy"})

    def test_watch_includes_all(self):
        s = _make_scheduler()
        opps = [
            _make_opp(platform="polymarket", market_id="pm_buy", status="BUY"),
            _make_opp(platform="polymarket", market_id="pm_watch", status="WATCH"),
        ]
        s._update_watch_lists(opps)
        s.pm_ws.watch.assert_called_once_with({"pm_buy", "pm_watch"})

    def test_empty_opps_no_watch_called(self):
        s = _make_scheduler()
        s._update_watch_lists([])
        s.pm_ws.watch.assert_not_called()
        s.kalshi_ws.watch.assert_not_called()


# ---------------------------------------------------------------------------
# Scheduler unifies pipeline locking with manual /refresh — both paths now
# acquire services.snapshot._refresh_lock, so concurrent expensive pipeline
# runs are impossible regardless of which caller initiated.
# ---------------------------------------------------------------------------

import asyncio
import time
from unittest.mock import patch

from services import snapshot as snap_mod
from services.snapshot import (
    clear_snapshot,
    is_refreshing,
    start_background_refresh,
    get_snapshot,
)


@pytest.fixture
def _clean_snapshot_state():
    clear_snapshot()
    yield
    # Drain any background task before clearing so leaked tasks don't pollute
    deadline = time.time() + 3.0
    while time.time() < deadline and is_refreshing():
        time.sleep(0.02)
    clear_snapshot()


class TestSchedulerUnifiedLock:
    def test_scheduler_routes_through_refresh_snapshot(self, _clean_snapshot_state):
        """Scheduler-triggered cycle stores a snapshot via the shared path,
        and /status reports last_trigger reflecting the scheduler's trigger."""
        async def quick(cfg=None):
            return [_make_opp(market_id="pm_buy")], {"status_counts": {"BUY": 1}}

        s = _make_scheduler()

        async def run():
            with patch("services.opportunities.fetch_opportunities", side_effect=quick):
                with patch.object(s.alert_manager, "run_cycle") as mock_cycle:
                    from services.monitor.manager import CycleResult
                    mock_cycle.return_value = CycleResult(
                        timestamp=time.time(),
                        candidates_evaluated=1,
                        filter_passed=1,
                        alerts_sent=0,
                        suppressed_cooldown=0,
                        suppressed_filter=0,
                        dry_run=True,
                    )
                    await s._run_pipeline_and_alert(trigger="scheduled")

        asyncio.run(run())

        # Snapshot should be populated and tagged with the scheduler's trigger
        snap = get_snapshot()
        assert snap is not None
        assert snap.trigger == "scheduled"
        assert len(snap.opportunities) == 1
        assert snap_mod._last_trigger == "scheduled"
        assert snap_mod._last_refresh_error is None
        # Watch lists were updated from the (non-SKIP) opportunity
        s.pm_ws.watch.assert_called_once_with({"pm_buy"})

    def test_scheduler_failure_does_not_run_alerts(self, _clean_snapshot_state):
        """If refresh_snapshot raises, scheduler must skip alert dispatch and
        the previous (stale) snapshot must NOT be passed to alert_manager."""
        async def boom(cfg=None):
            raise RuntimeError("fetch broke")

        s = _make_scheduler()

        async def run():
            with patch("services.opportunities.fetch_opportunities", side_effect=boom):
                with patch.object(s.alert_manager, "run_cycle") as mock_cycle:
                    result = await s._run_pipeline_and_alert(trigger="scheduled")
                    assert result is None
                    mock_cycle.assert_not_called()

        asyncio.run(run())

        # /status surfaces the failure
        assert snap_mod._last_refresh_error is not None
        assert "fetch broke" in snap_mod._last_refresh_error
        assert snap_mod._last_trigger == "scheduled"
        # Watch lists were NOT touched on a failed cycle
        s.pm_ws.watch.assert_not_called()
        s.kalshi_ws.watch.assert_not_called()

    def test_manual_refresh_blocked_while_scheduler_running(self, _clean_snapshot_state):
        """A manual POST /refresh that arrives while the scheduler is running
        the pipeline must NOT spawn a duplicate. start_background_refresh
        observes the shared _refresh_lock / _is_refreshing and returns
        already_running."""
        invocations = {"n": 0}
        manual_state: dict = {}

        async def slow(cfg=None):
            invocations["n"] += 1
            await asyncio.sleep(0.2)
            return [_make_opp()], {"status_counts": {}}

        s = _make_scheduler()

        async def run():
            with patch("services.opportunities.fetch_opportunities", side_effect=slow):
                with patch.object(s.alert_manager, "run_cycle") as mock_cycle:
                    from services.monitor.manager import CycleResult
                    mock_cycle.return_value = CycleResult(
                        timestamp=time.time(), candidates_evaluated=1,
                        filter_passed=1, alerts_sent=0,
                        suppressed_cooldown=0, suppressed_filter=0, dry_run=True,
                    )
                    # Start the scheduler pipeline; it acquires _refresh_lock.
                    sched_task = asyncio.create_task(
                        s._run_pipeline_and_alert(trigger="scheduled")
                    )
                    # Yield so scheduler enters the lock.
                    await asyncio.sleep(0.05)
                    # Manual refresh attempt — must observe already-running.
                    manual_state.update(
                        await start_background_refresh(trigger="manual")
                    )
                    await sched_task

        asyncio.run(run())

        assert manual_state["already_running"] is True
        assert manual_state["started"] is False
        # Pipeline ran exactly once — manual was coalesced.
        assert invocations["n"] == 1

    def test_scheduler_blocked_while_manual_refresh_running(self, _clean_snapshot_state):
        """A scheduler cycle starting while manual refresh is in flight must
        wait on the shared lock (not run a second concurrent pipeline)."""
        invocations = {"n": 0}

        async def slow(cfg=None):
            invocations["n"] += 1
            await asyncio.sleep(0.2)
            return [_make_opp()], {"status_counts": {}}

        s = _make_scheduler()

        async def run():
            with patch("services.opportunities.fetch_opportunities", side_effect=slow):
                with patch.object(s.alert_manager, "run_cycle") as mock_cycle:
                    from services.monitor.manager import CycleResult
                    mock_cycle.return_value = CycleResult(
                        timestamp=time.time(), candidates_evaluated=1,
                        filter_passed=1, alerts_sent=0,
                        suppressed_cooldown=0, suppressed_filter=0, dry_run=True,
                    )
                    # Manual refresh starts first.
                    await start_background_refresh(trigger="manual")
                    # Yield so the spawned task enters the lock.
                    await asyncio.sleep(0.05)
                    assert is_refreshing() is True
                    # Scheduler attempt — should wait, then run AFTER manual finishes.
                    sched_task = asyncio.create_task(
                        s._run_pipeline_and_alert(trigger="scheduled")
                    )
                    # Drain the manual background task and the scheduler in turn.
                    if snap_mod._background_task is not None:
                        await snap_mod._background_task
                    await sched_task

        asyncio.run(run())

        # Both pipelines ran, sequentially — never concurrently.
        assert invocations["n"] == 2
        # Latest trigger should be scheduler's (it ran second).
        assert snap_mod._last_trigger == "scheduled"
