"""
Integration tests for the maker pass inside ``fetch_opportunities``.

Covers two layers:

  1. ``_run_maker_pass`` — direct unit tests with crafted features and a
     fake fetch_book.  These pin the architectural invariant that maker
     consumes Pass A features and rescues taker SKIP/NO_EDGE candidates.

  2. ``fetch_opportunities`` — end-to-end integration with mocked adapters
     and odds.  Confirms the disabled path is a true no-op and the enabled
     path produces meta counts + persisted records.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from services.adapters.base import NormalizedMarket
from services.engine_config import EngineConfig
from services.maker.config import MakerConfig
from services.maker.orderbook import OrderBook, parse_kalshi_orderbook
from services.maker.planner import MakerBookInput
from services.maker.state import (
    PaperMakerStore,
    STATUS_PAPER_ACTIVE,
    STATUS_PAPER_REJECTED,
)
from services.opportunities import _run_maker_pass, fetch_opportunities

# Reuse the canonical-feature factory from the math test file.
from tests.test_maker_planner_math import _features, _maker_cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_book(best_bid_cents: int = 40, best_ask_cents: int = 90) -> OrderBook:
    """Build a parsed orderbook with the supplied best bid/ask in cents.

    best_yes_ask is synthesized from a single NO bid at (100 - ask_cents).
    """
    payload = {
        "orderbook": {
            "yes": [[best_bid_cents, 10]],
            "no":  [[100 - best_ask_cents, 10]],
        }
    }
    return parse_kalshi_orderbook("K1", payload, fetched_at=time.time())


def _fake_fetcher(book: OrderBook | None):
    """Return an async fetcher that yields the supplied book for any ticker."""
    async def _fetch(ticker, **kwargs):
        return book
    return _fetch


def _raising_fetcher():
    """Return an async fetcher that raises — exercises the defensive boundary."""
    async def _fetch(ticker, **kwargs):
        raise RuntimeError("boom")
    return _fetch


# ---------------------------------------------------------------------------
# _run_maker_pass — disabled fast-exit
# ---------------------------------------------------------------------------

class TestMakerPassDisabled:
    def test_disabled_meta_keys(self):
        """Disabled config returns the four meta keys with zero counts."""
        meta = asyncio.run(_run_maker_pass(
            features=[_features()],
            engine_cfg=EngineConfig(),
            maker_cfg=MakerConfig(),  # enabled=False default
        ))
        assert meta == {
            "maker_enabled": False,
            "maker_proposals_total": 0,
            "maker_proposals_eligible": 0,
            "maker_proposals_rejected": 0,
        }

    def test_disabled_does_not_call_fetcher(self, tmp_path: Path):
        """The fast-exit must not even invoke the fetch_book coroutine."""
        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return None

        asyncio.run(_run_maker_pass(
            features=[_features()],
            engine_cfg=EngineConfig(),
            maker_cfg=MakerConfig(),  # disabled
            store=PaperMakerStore(base_dir=tmp_path),
            fetch_book=_spy_fetch,
        ))
        assert called["n"] == 0

    def test_disabled_does_not_write_records(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        asyncio.run(_run_maker_pass(
            features=[_features()],
            engine_cfg=EngineConfig(),
            maker_cfg=MakerConfig(),
            store=store,
        ))
        assert store.read_recent(days=2) == []
        assert list(tmp_path.glob("*.jsonl")) == []


# ---------------------------------------------------------------------------
# _run_maker_pass — enabled, canonical wide-spread case (rescue)
# ---------------------------------------------------------------------------

class TestMakerPassRescue:
    def test_no_edge_taker_becomes_eligible_paper_proposal(self, tmp_path: Path):
        """The user's canonical case:
           p_true=0.50, ask=0.90, best_bid=0.40, best_ask=0.90
           taker would be SKIP for NO_EDGE
           maker proposal at 0.41 is eligible."""
        store = PaperMakerStore(base_dir=tmp_path)
        # Feature is in NO_EDGE territory (taker edge -0.41) but otherwise clean
        feat = _features(pm_price=0.90, pm_price_effective=0.91, edge=-0.41)
        # Mark Pass B status to simulate post-Pass-B mutation
        feat.status = "SKIP"
        feat.reject_reasons = ["NO_EDGE"]

        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_fake_fetcher(_ok_book()),
        ))

        assert meta["maker_enabled"] is True
        assert meta["maker_proposals_total"] == 1
        assert meta["maker_proposals_eligible"] == 1
        assert meta["maker_proposals_rejected"] == 0

        records = store.read_recent(days=2)
        assert len(records) == 1
        rec = records[0]
        assert rec["status"] == STATUS_PAPER_ACTIVE
        assert rec["proposed_price"] == pytest.approx(0.41)
        assert rec["maker_max_bid"] == pytest.approx(0.44)
        assert rec["estimated_maker_edge"] == pytest.approx(0.08)
        # Audit: the taker SKIP/NO_EDGE verdict is preserved on the record
        assert rec["taker_status_at_planning"] == "SKIP"
        assert "NO_EDGE" in rec["taker_reject_reasons"]


# ---------------------------------------------------------------------------
# _run_maker_pass — safety failures block ALL fetches and result in rejected
# ---------------------------------------------------------------------------

class TestMakerPassSafetyBlocks:
    def test_no_bookmaker_data_blocks_fetch(self, tmp_path: Path):
        """Soccer missing-draw is encoded as has_bookmaker_data=False
        (NO_BOOKMAKER_DATA).  Maker must NOT fetch the orderbook."""
        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return _ok_book()

        feat = _features(has_bookmaker_data=False)
        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_spy_fetch,
        ))

        assert called["n"] == 0
        assert meta["maker_proposals_eligible"] == 0
        assert meta["maker_proposals_rejected"] == 1
        records = store.read_recent(days=2)
        assert records[0]["status"] == STATUS_PAPER_REJECTED
        assert "NO_BOOKMAKER_DATA" in records[0]["rejection_reasons"]

    def test_date_too_far_blocks_fetch(self, tmp_path: Path):
        """DATE_TOO_FAR (NBA series, 200 hours off) → no fetch, rejected record."""
        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return _ok_book()

        feat = _features(
            sport="basketball_nba",
            date_delta_hours=200.0,
            fanduel_line_width=0.20,
        )
        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_spy_fetch,
        ))
        assert called["n"] == 0
        assert meta["maker_proposals_eligible"] == 0
        assert meta["maker_proposals_rejected"] == 1
        assert "DATE_TOO_FAR" in store.read_recent(days=2)[0]["rejection_reasons"]

    def test_ambiguity_blocks_fetch(self, tmp_path: Path):
        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return _ok_book()

        feat = _features(
            competing_matches=2,
            confidence_gap=0.01,
            second_best_confidence=0.94,
            second_best_event_id="E2",
        )
        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_confidence_gap=0.05, max_competing_matches=5),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_spy_fetch,
        ))
        assert called["n"] == 0
        assert meta["maker_proposals_eligible"] == 0
        assert "AMBIGUOUS_MATCH_GAP" in store.read_recent(days=2)[0]["rejection_reasons"]


# ---------------------------------------------------------------------------
# _run_maker_pass — orderbook fetch failure
# ---------------------------------------------------------------------------

class TestMakerPassFetchFailure:
    def test_fetch_returns_none_records_rejected(self, tmp_path: Path):
        """fetch_kalshi_orderbook returning None must produce a rejected
        record, not a crash."""
        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=[_features()],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_fake_fetcher(None),
        ))
        assert meta["maker_proposals_total"] == 1
        assert meta["maker_proposals_eligible"] == 0
        assert meta["maker_proposals_rejected"] == 1
        rec = store.read_recent(days=2)[0]
        assert rec["status"] == STATUS_PAPER_REJECTED
        assert "BOOK_CROSSED_OR_EMPTY" in rec["rejection_reasons"]

    def test_fetcher_exception_does_not_crash(self, tmp_path: Path):
        """A fetcher that RAISES (it shouldn't, but defensive) must be caught
        and recorded as a rejected proposal — never propagate to the scan."""
        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=[_features()],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_raising_fetcher(),
        ))
        assert meta["maker_proposals_eligible"] == 0
        assert meta["maker_proposals_rejected"] == 1
        rec = store.read_recent(days=2)[0]
        assert rec["status"] == STATUS_PAPER_REJECTED


# ---------------------------------------------------------------------------
# _run_maker_pass — out-of-scope features are silently ignored
# ---------------------------------------------------------------------------

class TestMakerPassScope:
    def test_polymarket_feature_silently_ignored(self, tmp_path: Path):
        """No record, no fetch.  Polymarket is out-of-scope for v1."""
        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return _ok_book()

        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=[_features(platform="polymarket")],
            engine_cfg=EngineConfig(),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_spy_fetch,
        ))
        assert called["n"] == 0
        assert meta["maker_proposals_total"] == 0
        assert store.read_recent(days=2) == []

    def test_totals_market_silently_ignored(self, tmp_path: Path):
        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return _ok_book()

        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=[_features(market_type="totals")],
            engine_cfg=EngineConfig(),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_spy_fetch,
        ))
        assert called["n"] == 0
        assert meta["maker_proposals_total"] == 0
        assert store.read_recent(days=2) == []

    def test_mixed_scope_only_kalshi_h2h_processed(self, tmp_path: Path):
        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return _ok_book()

        feats = [
            _features(platform="kalshi", market_type="h2h", market_id="K1"),
            _features(platform="polymarket", market_type="h2h", market_id="P1"),
            _features(platform="kalshi", market_type="totals", market_id="K2"),
        ]
        store = PaperMakerStore(base_dir=tmp_path)
        meta = asyncio.run(_run_maker_pass(
            features=feats,
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
            fetch_book=_spy_fetch,
        ))
        # Only the first feature is in-scope → exactly one fetch, one record
        assert called["n"] == 1
        assert meta["maker_proposals_total"] == 1
        records = store.read_recent(days=2)
        assert len(records) == 1
        assert records[0]["market_id"] == "K1"


# ---------------------------------------------------------------------------
# fetch_opportunities — end-to-end integration
# ---------------------------------------------------------------------------

def _stub_market() -> NormalizedMarket:
    """Minimal NormalizedMarket whose Pass A features won't match anything
    (we use this when the test only cares about meta keys, not opportunities)."""
    return NormalizedMarket(
        platform="kalshi",
        market_id="K-EMPTY",
        event="N/A",
        market_type="h2h",
        side="",
        line=None,
        price=0.50,
        liquidity=100.0,
        url=None,
        timestamp=None,
        question="placeholder",
        end_date=None,
        outcome_prices=["0.50", "0.50"],
        event_slug="empty",
        fetched_at=time.time(),
    )


class _StubAdapter:
    platform_name = "kalshi"

    def __init__(self, markets: list[NormalizedMarket]):
        self._markets = markets

    async def fetch_markets(self):
        return list(self._markets)


class TestFetchOpportunitiesIntegration:
    def test_disabled_meta_present_no_fetch(self, monkeypatch):
        """Default fetch_opportunities call: maker_meta keys are present
        with disabled values; no orderbook fetcher invoked."""
        async def _no_odds(*args, **kwargs):
            return [], {}

        called = {"n": 0}

        async def _spy_fetch(ticker, **kwargs):
            called["n"] += 1
            return None

        with patch("services.opportunities.fetch_odds", side_effect=_no_odds), \
             patch("services.maker.orderbook.fetch_kalshi_orderbook", side_effect=_spy_fetch):
            opps, meta = asyncio.run(fetch_opportunities(
                cfg=EngineConfig(),
                adapters=[_StubAdapter([_stub_market()])],
                # maker_cfg defaults to disabled
            ))

        assert meta["maker_enabled"] is False
        assert meta["maker_proposals_total"] == 0
        assert meta["maker_proposals_eligible"] == 0
        assert meta["maker_proposals_rejected"] == 0
        assert called["n"] == 0
        # Existing meta still present
        assert "status_counts" in meta
        assert "platforms_fetched" in meta

    def test_enabled_passes_meta_through(self, tmp_path: Path):
        """When maker_cfg.enabled=True, fetch_opportunities returns the
        enabled meta keys.  Empty markets → 0 features → 0 proposals,
        but maker_enabled=True is reported."""
        async def _no_odds(*args, **kwargs):
            return [], {}

        with patch("services.opportunities.fetch_odds", side_effect=_no_odds):
            opps, meta = asyncio.run(fetch_opportunities(
                cfg=EngineConfig(),
                adapters=[_StubAdapter([])],
                maker_cfg=MakerConfig(enabled=True, paper_only=True),
            ))

        assert meta["maker_enabled"] is True
        assert meta["maker_proposals_total"] == 0


# ---------------------------------------------------------------------------
# Existing taker behavior must not change
# ---------------------------------------------------------------------------

class TestTakerBehaviorUnchanged:
    def test_disabled_meta_does_not_alter_existing_keys(self):
        """Sanity: maker meta is purely additive."""
        async def _no_odds(*args, **kwargs):
            return [], {"sports_fetched": ["x"]}

        with patch("services.opportunities.fetch_odds", side_effect=_no_odds):
            opps, meta = asyncio.run(fetch_opportunities(
                cfg=EngineConfig(),
                adapters=[_StubAdapter([])],
            ))

        # All four maker keys present...
        for k in (
            "maker_enabled",
            "maker_proposals_total",
            "maker_proposals_eligible",
            "maker_proposals_rejected",
        ):
            assert k in meta

        # ...and existing keys are still there too.
        for k in (
            "status_counts",
            "platforms_fetched",
            "opportunities_count",
            "sportsbook_markets_fetched",
        ):
            assert k in meta

        # No taker opportunities expected (empty markets)
        assert opps == []
