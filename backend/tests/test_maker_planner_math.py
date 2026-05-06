"""
Tests for the maker planner math, tick helpers, and the maker-only rules
(scope, freshness, book sanity, math constraints).

The canonical case from the design doc anchors the math:

    p_true=0.50, best_bid=0.40, best_ask=0.90
    required_edge=0.05, cost_buffer=0.01
    → maker_max_bid=0.44, suggested_bid=0.41, est. maker edge=0.08

This must be eligible even though buying at the 0.90 ask would be a taker
SKIP for NO_EDGE.  Rule-policy interactions are tested in
test_maker_policy.py — this file focuses on math and the maker-only rules.
"""
from __future__ import annotations

import time

import pytest

from services.engine_config import EngineConfig
from services.maker.config import MakerConfig
from services.maker.planner import MakerBookInput, plan_maker_proposal
from services.maker.tick import (
    TICK_DOLLARS,
    on_tick,
    round_down_to_tick,
    round_up_to_tick,
)
from services.rule_engine import MarketFeatures


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _maker_cfg(**overrides) -> MakerConfig:
    """MakerConfig that is enabled by default — tests need the planner active."""
    base = dict(
        enabled=True,
        paper_only=True,
        platforms=("kalshi",),
        market_types=("h2h",),
        min_estimated_maker_edge=0.05,
        require_min_spread=0.02,
        max_book_age_seconds=30.0,
        max_fd_age_seconds=600.0,
    )
    base.update(overrides)
    return MakerConfig(**base)


def _features(**overrides) -> MarketFeatures:
    """MarketFeatures that passes EVERY taker safety rule by default.

    Edge is set negative (taker would SKIP for NO_EDGE at ask=0.90,
    p_true=0.50) so the canonical test exercises the maker-rescue case.
    Sport=tennis → SportConfig.min_edge=0.05.  Override fields per test."""
    now = time.time()
    base = dict(
        # Identity
        platform="kalshi",
        market_id="K1",
        sport="tennis",
        event_label="A vs B",
        event_url=None,
        tournament="Test",
        start_time="2099-01-01T00:00:00Z",   # not live
        market_type="h2h",
        side="A",
        line=None,
        question="Will A beat B?",
        # Pricing
        pm_price=0.90,
        pm_price_no=0.10,
        pm_price_effective=0.91,
        # Match info
        home_player="A",
        away_player="B",
        home_player_norm="a",
        away_player_norm="b",
        name_match_score=1.0,
        matched_players=("a", "b"),
        date_score=1.0,
        date_delta_hours=2.0,
        event_match_confidence=0.95,
        match_quality="verified",
        # Outcome alignment
        outcome_aligned=True,
        yes_player="A",
        no_player="B",
        # FanDuel raw
        fd_odds=-110,
        fd_odds_other=110,
        fd_home_implied=0.5,
        fd_away_implied=0.5,
        # Devigged
        p_true=0.50,
        p_true_other=0.50,
        # FanDuel metrics
        fanduel_overround=0.02,
        fanduel_line_width=0.20,
        fanduel_line_width_label="Moderate",
        fanduel_confidence_label="High",
        # Totals/handicap (h2h: all True so rules pass)
        line_match_exact=True,
        unit_match=True,
        side_match=True,
        # Computed
        edge=-0.41,                              # taker negative (NO_EDGE)
        # Validity
        price_in_range=True,
        has_bookmaker_data=True,
        is_live=False,
        # Ambiguity
        best_match_confidence=0.95,
        second_best_confidence=0.0,
        confidence_gap=1.0,
        competing_matches=1,
        matched_event_id="E1",
        second_best_event_id="",
        has_shared_last_name=False,
        home_last_name_collision=False,
        away_last_name_collision=False,
        # Data quality
        bid_ask_spread=0.50,
        # Metadata
        has_end_date=True,
        has_outcome_prices=True,
        prices_internally_consistent=True,
        # Staleness
        price_fetched_at=now,
        fd_fetched_at=now,
        # Tokens
        home_tokens=("a",),
        away_tokens=("b",),
        question_tokens=("a", "b", "beat", "will"),
        # Pass B status — empty until evaluate_rules mutates them
        status="",
        reject_reasons=[],
        downgrade_reasons=[],
        kelly_fraction=0.0,
        kelly_full=0.0,
    )
    base.update(overrides)
    return MarketFeatures(**base)


def _book(
    best_bid: float | None = 0.40,
    best_ask: float | None = 0.90,
    fetched_at: float | None = None,
    **overrides,
) -> MakerBookInput:
    if fetched_at is None:
        fetched_at = time.time()
    return MakerBookInput(
        best_bid=best_bid,
        best_ask=best_ask,
        fetched_at=fetched_at,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Tick helpers
# ---------------------------------------------------------------------------

class TestTickHelpers:
    def test_tick_constant(self):
        assert TICK_DOLLARS == 0.01

    def test_round_down_to_tick(self):
        assert round_down_to_tick(0.444) == pytest.approx(0.44)
        assert round_down_to_tick(0.445) == pytest.approx(0.44)
        assert round_down_to_tick(0.41) == pytest.approx(0.41)
        assert round_down_to_tick(0.50) == pytest.approx(0.50)
        assert round_down_to_tick(0.99) == pytest.approx(0.99)
        # Float jitter: 0.504 * 100 = 50.39999... must still round down to 50
        assert round_down_to_tick(0.504) == pytest.approx(0.50)

    def test_round_up_to_tick(self):
        assert round_up_to_tick(0.401) == pytest.approx(0.41)
        assert round_up_to_tick(0.41) == pytest.approx(0.41)
        assert round_up_to_tick(0.405) == pytest.approx(0.41)
        assert round_up_to_tick(0.50) == pytest.approx(0.50)

    def test_on_tick(self):
        assert on_tick(0.41) is True
        assert on_tick(0.50) is True
        assert on_tick(0.99) is True
        assert on_tick(0.415) is False
        assert on_tick(0.504) is False


# ---------------------------------------------------------------------------
# Canonical example
# ---------------------------------------------------------------------------

class TestCanonicalExample:
    """p_true=0.50, best_bid=0.40, best_ask=0.90, required_edge=0.05,
    cost_buffer=0.01 → max_bid=0.44, proposed=0.41, edge=0.08, eligible."""

    def test_eligible_with_correct_math(self):
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.required_edge == pytest.approx(0.05)
        assert prop.cost_buffer == pytest.approx(0.01)
        assert prop.maker_max_bid == pytest.approx(0.44)
        assert prop.proposed_price == pytest.approx(0.41)
        assert prop.estimated_maker_edge == pytest.approx(0.08)
        assert prop.eligible is True
        assert prop.rejection_reasons == ()

    def test_proposal_carries_book_and_audit_snapshot(self):
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90, best_bid_qty=120, best_ask_qty=80)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=1234.0)

        assert prop.platform == "kalshi"
        assert prop.market_id == "K1"
        assert prop.market_type == "h2h"
        assert prop.best_bid == pytest.approx(0.40)
        assert prop.best_ask == pytest.approx(0.90)
        assert prop.book_fetched_at == b.fetched_at
        assert prop.fd_fetched_at == f.fd_fetched_at
        assert prop.tick_size == TICK_DOLLARS
        assert prop.created_at == 1234.0
        assert "paper_only" in prop.notes


# ---------------------------------------------------------------------------
# Maker math edge cases — book and bid/ask boundaries
# ---------------------------------------------------------------------------

class TestMakerMathEdges:
    def test_best_bid_above_max_blocks(self):
        """best_bid >= maker_max_bid → no proposal can be both inside-spread
        AND ≤ maker_max_bid.  proposed_price collapses to maker_max_bid,
        which is below best_bid, failing inside-spread."""
        f = _features()
        b = _book(best_bid=0.50, best_ask=0.90)   # max_bid=0.44 < best_bid=0.50
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is False
        assert "BID_NOT_INSIDE_SPREAD" in prop.rejection_reasons

    def test_proposed_strictly_below_ask(self):
        """At a 2-tick spread, proposed sits exactly one tick above best_bid
        and one tick below best_ask — must be eligible at the boundary."""
        f = _features()
        b = _book(best_bid=0.43, best_ask=0.45)   # 2-tick spread
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(
            f, b, cfg, _maker_cfg(min_estimated_maker_edge=0.05), now=time.time()
        )

        # max_bid=0.44, candidate=0.44, proposed=0.44 → 0.43 < 0.44 < 0.45 ✓
        # maker edge = 0.50 - 0.44 - 0.01 = 0.05 ≥ 0.05 ✓
        assert prop.proposed_price == pytest.approx(0.44)
        assert prop.eligible is True

    def test_one_tick_spread_blocks(self):
        """1-tick spread (e.g., 0.44/0.45) is too narrow to seat a maker."""
        f = _features()
        b = _book(best_bid=0.44, best_ask=0.45)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is False
        assert "SPREAD_TOO_NARROW" in prop.rejection_reasons

    def test_crossed_book_blocks(self):
        f = _features()
        b = _book(best_bid=0.91, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is False
        assert "BOOK_CROSSED_OR_EMPTY" in prop.rejection_reasons

    def test_missing_best_bid_blocks(self):
        f = _features()
        b = _book(best_bid=None, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is False
        assert "BOOK_CROSSED_OR_EMPTY" in prop.rejection_reasons

    def test_missing_best_ask_blocks(self):
        f = _features()
        b = _book(best_bid=0.40, best_ask=None)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is False
        assert "BOOK_CROSSED_OR_EMPTY" in prop.rejection_reasons

    def test_maker_edge_below_min_blocks(self):
        """If proposed_price clears max_bid but doesn't meet the maker-edge
        floor, planner blocks even though math constraints hold."""
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        # Require an unrealistically high maker edge floor
        prop = plan_maker_proposal(
            f, b, cfg, _maker_cfg(min_estimated_maker_edge=0.50), now=time.time()
        )

        assert prop.eligible is False
        assert "MAKER_EDGE_TOO_LOW" in prop.rejection_reasons

    def test_maker_edge_implausible_blocks(self):
        """A wildly high estimated maker edge is treated as a data error,
        same threshold the taker rule uses."""
        # p_true=0.95, best_bid=0.10, best_ask=0.90
        # max_bid = 0.95 - 0.05 - 0.01 = 0.89, candidate = 0.11, proposed = 0.11
        # maker_edge = 0.95 - 0.11 - 0.01 = 0.83 (implausible)
        f = _features(p_true=0.95)
        b = _book(best_bid=0.10, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01, max_plausible_edge=0.20)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        # Tennis SportConfig has its own max_plausible_edge=0.25, still
        # blown well past it by the 0.83 maker edge.
        assert prop.eligible is False
        assert "MAKER_EDGE_IMPLAUSIBLE" in prop.rejection_reasons


# ---------------------------------------------------------------------------
# Freshness gates
# ---------------------------------------------------------------------------

class TestFreshness:
    def test_stale_book_blocks(self):
        now = time.time()
        f = _features(fd_fetched_at=now)
        b = _book(best_bid=0.40, best_ask=0.90, fetched_at=now - 60.0)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(
            f, b, cfg, _maker_cfg(max_book_age_seconds=30.0), now=now
        )

        assert prop.eligible is False
        assert "BOOK_STALE" in prop.rejection_reasons

    def test_unfetched_book_blocks(self):
        """fetched_at == 0.0 (uninitialized) is rejected."""
        now = time.time()
        f = _features(fd_fetched_at=now)
        b = _book(best_bid=0.40, best_ask=0.90, fetched_at=0.0)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=now)

        assert prop.eligible is False
        assert "BOOK_STALE" in prop.rejection_reasons

    def test_stale_fd_blocks(self):
        now = time.time()
        f = _features(fd_fetched_at=now - 700.0)
        b = _book(best_bid=0.40, best_ask=0.90, fetched_at=now)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(
            f, b, cfg, _maker_cfg(max_fd_age_seconds=600.0), now=now
        )

        assert prop.eligible is False
        assert "FD_STALE" in prop.rejection_reasons

    def test_unfetched_fd_blocks(self):
        """fd_fetched_at == 0.0 (uninitialized) is rejected."""
        now = time.time()
        f = _features(fd_fetched_at=0.0)
        b = _book(best_bid=0.40, best_ask=0.90, fetched_at=now)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=now)

        assert prop.eligible is False
        assert "FD_STALE" in prop.rejection_reasons


# ---------------------------------------------------------------------------
# Scope gates: platform and market type
# ---------------------------------------------------------------------------

class TestScope:
    def test_polymarket_blocked(self):
        f = _features(platform="polymarket")
        b = _book()
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is False
        assert "PLATFORM_OUT_OF_SCOPE" in prop.rejection_reasons

    def test_non_h2h_blocked(self):
        f = _features(market_type="totals")
        b = _book()
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is False
        assert "MARKET_TYPE_OUT_OF_SCOPE" in prop.rejection_reasons

    def test_disabled_maker_blocks(self):
        """MakerConfig.enabled=False makes every proposal ineligible."""
        f = _features()
        b = _book()
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, MakerConfig(), now=time.time())

        assert prop.eligible is False
        assert "MAKER_DISABLED" in prop.rejection_reasons

    def test_polymarket_uses_zero_cost_buffer(self):
        """Even though Polymarket is gated out, the math layer should still
        compute cost_buffer=0 for it so a future scope expansion is correct."""
        f = _features(platform="polymarket")
        b = _book()
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(
            f, b, cfg, _maker_cfg(platforms=("kalshi", "polymarket")), now=time.time()
        )

        # max_bid = 0.50 - 0.05 - 0.0 = 0.45 (no cost buffer)
        assert prop.cost_buffer == pytest.approx(0.0)
        assert prop.maker_max_bid == pytest.approx(0.45)


# ---------------------------------------------------------------------------
# Tick rounding behavior in math
# ---------------------------------------------------------------------------

class TestTickRoundingConservative:
    def test_max_bid_rounds_down(self):
        """p_true=0.504, edge=0.05, buffer=0.01 → max_bid_raw=0.444 → 0.44.

        Conservative: must remain at or below the math, never round up."""
        f = _features(p_true=0.504)
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.maker_max_bid == pytest.approx(0.44)
        assert prop.proposed_price == pytest.approx(0.41)

    def test_candidate_rounds_down(self):
        """best_bid+tick is always on tick when best_bid is.  Confirm the
        math doesn't drift it up."""
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.proposed_price == pytest.approx(0.41)

    def test_proposed_capped_at_max_bid(self):
        """When candidate exceeds max_bid, proposed is the cap, on tick."""
        # best_bid=0.43 → candidate=0.44; max_bid=0.44 → proposed=0.44
        f = _features()
        b = _book(best_bid=0.43, best_ask=0.50)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.proposed_price == pytest.approx(0.44)
        assert prop.maker_max_bid == pytest.approx(0.44)
        assert prop.eligible is True


# ---------------------------------------------------------------------------
# Notes / observability
# ---------------------------------------------------------------------------

class TestNotes:
    def test_paper_only_note_always_present(self):
        f = _features()
        b = _book()
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert "paper_only" in prop.notes

    def test_take_not_make_note_when_taker_clears_bar(self):
        """If best_ask itself is at or below maker_max_bid, taking is
        already positive-EV — record a TAKE_NOT_MAKE note (informational)."""
        # max_bid = 0.44; ask=0.43 → taking clears the required_edge bar
        f = _features()
        b = _book(best_bid=0.20, best_ask=0.43)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert "TAKE_NOT_MAKE" in prop.notes

    def test_no_take_not_make_when_ask_too_high(self):
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert "TAKE_NOT_MAKE" not in prop.notes
