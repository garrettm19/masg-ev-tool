"""
Tests for services.snapshot — in-memory opportunity snapshot.

Covers:
  - store_snapshot / get_snapshot round-trip
  - get_snapshot returns None when empty
  - is_refreshing flag
  - store overwrites previous snapshot
  - clear_snapshot resets state
  - snapshot metadata preserved
"""
import time

import pytest

from services.snapshot import (
    get_snapshot,
    store_snapshot,
    is_refreshing,
    clear_snapshot,
    OpportunitySnapshot,
)
from services.opportunities import EvaluatedOpportunity


def _make_opp(
    edge: float = 0.08,
    status: str = "BUY",
    platform: str = "polymarket",
    market_id: str = "m1",
    side: str = "Alcaraz",
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
        home_tokens=(),
        away_tokens=(),
        name_match_score=1.0,
        date_score=1.0,
        date_delta_hours=2.0,
        rule_evaluations=[],
    )


@pytest.fixture(autouse=True)
def _clean_snapshot():
    """Reset snapshot state before and after each test."""
    clear_snapshot()
    yield
    clear_snapshot()


class TestGetSnapshot:
    def test_returns_none_when_empty(self):
        assert get_snapshot() is None

    def test_returns_stored_snapshot(self):
        opps = [_make_opp()]
        meta = {"status_counts": {"BUY": 1}}
        store_snapshot(opps, meta, trigger="test")

        snap = get_snapshot()
        assert snap is not None
        assert len(snap.opportunities) == 1
        assert snap.trigger == "test"
        assert snap.updated_at > 0


class TestStoreSnapshot:
    def test_stores_opportunities_and_meta(self):
        opps = [_make_opp(edge=0.08), _make_opp(edge=0.05, market_id="m2")]
        meta = {"quota_remaining": "450", "platforms_fetched": ["polymarket"]}
        snap = store_snapshot(opps, meta, trigger="scheduled")

        assert len(snap.opportunities) == 2
        assert snap.meta["quota_remaining"] == "450"
        assert snap.trigger == "scheduled"

    def test_overwrites_previous(self):
        store_snapshot([_make_opp(edge=0.08)], {}, trigger="first")
        store_snapshot([_make_opp(edge=0.12)], {}, trigger="second")

        snap = get_snapshot()
        assert snap is not None
        assert snap.trigger == "second"
        assert snap.opportunities[0].edge == 0.12

    def test_updated_at_is_recent(self):
        before = time.time()
        store_snapshot([_make_opp()], {}, trigger="test")
        after = time.time()

        snap = get_snapshot()
        assert snap is not None
        assert before <= snap.updated_at <= after

    def test_meta_is_copied(self):
        """Mutating the original meta dict should not affect the snapshot."""
        meta = {"key": "original"}
        store_snapshot([_make_opp()], meta, trigger="test")
        meta["key"] = "mutated"

        snap = get_snapshot()
        assert snap is not None
        assert snap.meta["key"] == "original"


class TestIsRefreshing:
    def test_false_by_default(self):
        assert is_refreshing() is False


class TestClearSnapshot:
    def test_clears_stored_data(self):
        store_snapshot([_make_opp()], {}, trigger="test")
        assert get_snapshot() is not None

        clear_snapshot()
        assert get_snapshot() is None
        assert is_refreshing() is False
