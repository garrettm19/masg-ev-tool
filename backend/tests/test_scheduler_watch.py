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
