"""
Integration tests for the maker pass inside ``fetch_opportunities``.

The maker pass consumes ``MarketFeatures`` directly and builds its book
input from ``f.best_bid`` / ``f.best_ask`` / ``f.price_fetched_at``.  No
per-feature HTTP call to ``/markets/{ticker}/orderbook`` is made — that
endpoint frequently returned empty bodies in live testing, while the
Kalshi adapter already exposes top-of-book on every market in its
``/markets`` payload.

These tests pin both the architectural invariant (maker rescues taker
SKIP/NO_EDGE candidates) and the v1 source guarantee (no ``/orderbook``
fetch in the production path).
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

def _tob_features(**overrides):
    """`_features()` populated with the canonical wide-spread top-of-book.

    p_true=0.50 (default), best_bid=0.40, best_ask=0.90 — the case from the
    design doc that maker is meant to rescue when taker SKIPs for NO_EDGE.
    Tests can override any field, including best_bid/best_ask, to exercise
    edge cases.
    """
    base = dict(best_bid=0.40, best_ask=0.90)
    base.update(overrides)
    return _features(**base)


# ---------------------------------------------------------------------------
# Disabled fast-exit
# ---------------------------------------------------------------------------

class TestMakerPassDisabled:
    def test_disabled_meta_keys(self):
        meta = asyncio.run(_run_maker_pass(
            features=[_tob_features()],
            engine_cfg=EngineConfig(),
            maker_cfg=MakerConfig(),  # enabled=False default
        ))
        assert meta == {
            "maker_enabled": False,
            "maker_proposals_total": 0,
            "maker_proposals_eligible": 0,
            "maker_proposals_rejected": 0,
        }

    def test_disabled_writes_nothing(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        asyncio.run(_run_maker_pass(
            features=[_tob_features()],
            engine_cfg=EngineConfig(),
            maker_cfg=MakerConfig(),
            store=store,
        ))
        assert store.read_recent(days=2) == []
        assert list(tmp_path.glob("*.jsonl")) == []

    def test_disabled_does_not_call_orderbook_fetcher(self, tmp_path: Path):
        """Disabled fast-exit must NOT touch fetch_kalshi_orderbook either."""
        store = PaperMakerStore(base_dir=tmp_path)
        with patch(
            "services.maker.orderbook.fetch_kalshi_orderbook",
            side_effect=AssertionError("must not be called when disabled"),
        ):
            asyncio.run(_run_maker_pass(
                features=[_tob_features()],
                engine_cfg=EngineConfig(),
                maker_cfg=MakerConfig(),
                store=store,
            ))


# ---------------------------------------------------------------------------
# Canonical rescue: taker SKIP/NO_EDGE → eligible maker proposal
# ---------------------------------------------------------------------------

class TestMakerPassRescue:
    def test_no_edge_taker_becomes_eligible_paper_proposal(self, tmp_path: Path):
        """The user's canonical case:
           p_true=0.50, ask=0.90, best_bid=0.40, best_ask=0.90 (from features)
           taker would be SKIP for NO_EDGE.
           Maker proposal eligible at 0.41 with maker edge 0.08."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(pm_price=0.90, pm_price_effective=0.91, edge=-0.41)
        # Simulate post-Pass-B mutation
        feat.status = "SKIP"
        feat.reject_reasons = ["NO_EDGE"]

        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
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
        assert rec["best_bid"] == pytest.approx(0.40)
        assert rec["best_ask"] == pytest.approx(0.90)
        # Audit fields preserve the taker SKIP/NO_EDGE verdict.
        assert rec["taker_status_at_planning"] == "SKIP"
        assert "NO_EDGE" in rec["taker_reject_reasons"]

    def test_no_orderbook_fetch_on_rescue(self, tmp_path: Path):
        """The rescue path must NOT call fetch_kalshi_orderbook."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(pm_price=0.90, pm_price_effective=0.91, edge=-0.41)
        with patch(
            "services.maker.orderbook.fetch_kalshi_orderbook",
            side_effect=AssertionError("/orderbook fetch must not happen"),
        ):
            meta = asyncio.run(_run_maker_pass(
                features=[feat],
                engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
                maker_cfg=_maker_cfg(),
                store=store,
            ))
        assert meta["maker_proposals_eligible"] == 1


# ---------------------------------------------------------------------------
# Safety failures still block the proposal — no orderbook fetch needed
# ---------------------------------------------------------------------------

class TestMakerPassSafetyBlocks:
    def _plan_one(self, tmp_path: Path, feature_overrides: dict, cfg_overrides: dict | None = None):
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(**feature_overrides)
        cfg = EngineConfig(**(cfg_overrides or {}))
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=cfg,
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        return meta, store.read_recent(days=2)

    def test_no_bookmaker_data_persists_rejected(self, tmp_path: Path):
        meta, records = self._plan_one(tmp_path, {"has_bookmaker_data": False})
        assert meta["maker_proposals_eligible"] == 0
        assert meta["maker_proposals_rejected"] == 1
        assert records[0]["status"] == STATUS_PAPER_REJECTED
        assert "NO_BOOKMAKER_DATA" in records[0]["rejection_reasons"]

    def test_date_too_far_persists_rejected(self, tmp_path: Path):
        meta, records = self._plan_one(
            tmp_path,
            {"sport": "basketball_nba", "date_delta_hours": 200.0,
             "fanduel_line_width": 0.20},
        )
        assert meta["maker_proposals_eligible"] == 0
        assert "DATE_TOO_FAR" in records[0]["rejection_reasons"]

    def test_ambiguity_persists_rejected(self, tmp_path: Path):
        meta, records = self._plan_one(
            tmp_path,
            {"competing_matches": 2, "confidence_gap": 0.01,
             "second_best_confidence": 0.94, "second_best_event_id": "E2"},
            {"min_confidence_gap": 0.05, "max_competing_matches": 5},
        )
        assert "AMBIGUOUS_MATCH_GAP" in records[0]["rejection_reasons"]

    def test_safety_failure_does_not_call_orderbook(self, tmp_path: Path):
        """Safety pre-filter rejects without ever invoking the depth fetcher."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(has_bookmaker_data=False)
        with patch(
            "services.maker.orderbook.fetch_kalshi_orderbook",
            side_effect=AssertionError("must not be called for safety-rejected"),
        ):
            asyncio.run(_run_maker_pass(
                features=[feat],
                engine_cfg=EngineConfig(),
                maker_cfg=_maker_cfg(),
                store=store,
            ))


# ---------------------------------------------------------------------------
# Missing or stale top-of-book — replaces the previous "fetch failure" tests
# ---------------------------------------------------------------------------

class TestMakerPassMissingTopOfBook:
    def test_missing_best_bid_rejected(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(best_bid=None, best_ask=0.90)
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        assert meta["maker_proposals_eligible"] == 0
        assert meta["maker_proposals_rejected"] == 1
        rec = store.read_recent(days=2)[0]
        assert rec["status"] == STATUS_PAPER_REJECTED
        assert "BOOK_CROSSED_OR_EMPTY" in rec["rejection_reasons"]

    def test_missing_best_ask_rejected(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(best_bid=0.40, best_ask=None)
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        assert meta["maker_proposals_rejected"] == 1
        assert "BOOK_CROSSED_OR_EMPTY" in store.read_recent(days=2)[0]["rejection_reasons"]

    def test_both_sides_missing_rejected(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(best_bid=None, best_ask=None)
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        assert meta["maker_proposals_rejected"] == 1

    def test_stale_price_fetched_at_rejected(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        now = time.time()
        feat = _tob_features(price_fetched_at=now - 600.0)
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(max_book_age_seconds=30.0),
            store=store,
        ))
        assert meta["maker_proposals_eligible"] == 0
        assert "BOOK_STALE" in store.read_recent(days=2)[0]["rejection_reasons"]

    def test_crossed_top_of_book_rejected(self, tmp_path: Path):
        """best_bid >= best_ask (crossed/locked TOB) rejects without proposal."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(best_bid=0.91, best_ask=0.90)   # crossed
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        assert meta["maker_proposals_rejected"] == 1
        assert "BOOK_CROSSED_OR_EMPTY" in store.read_recent(days=2)[0]["rejection_reasons"]


# ---------------------------------------------------------------------------
# Scope filter — Polymarket and non-H2H ignored without record or I/O
# ---------------------------------------------------------------------------

class TestMakerPassScope:
    def test_polymarket_silently_ignored(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(platform="polymarket")
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        assert meta["maker_proposals_total"] == 0
        assert store.read_recent(days=2) == []

    def test_totals_market_silently_ignored(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(market_type="totals")
        meta = asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        assert meta["maker_proposals_total"] == 0
        assert store.read_recent(days=2) == []

    def test_mixed_scope_only_kalshi_h2h_processed(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        feats = [
            _tob_features(platform="kalshi", market_type="h2h", market_id="K1"),
            _tob_features(platform="polymarket", market_type="h2h", market_id="P1"),
            _tob_features(platform="kalshi", market_type="totals", market_id="K2"),
        ]
        meta = asyncio.run(_run_maker_pass(
            features=feats,
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        # Only the first feature is in scope → exactly one record.
        assert meta["maker_proposals_total"] == 1
        records = store.read_recent(days=2)
        assert len(records) == 1
        assert records[0]["market_id"] == "K1"


# ---------------------------------------------------------------------------
# Production path: no /orderbook fetcher invoked under any circumstance
# ---------------------------------------------------------------------------

class TestNoOrderbookFetchInProductionPath:
    def test_eligible_path_does_not_call_fetcher(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        with patch("services.maker.orderbook.fetch_kalshi_orderbook") as mock_fetch:
            asyncio.run(_run_maker_pass(
                features=[_tob_features()],
                engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
                maker_cfg=_maker_cfg(),
                store=store,
            ))
        mock_fetch.assert_not_called()

    def test_safety_rejected_path_does_not_call_fetcher(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        with patch("services.maker.orderbook.fetch_kalshi_orderbook") as mock_fetch:
            asyncio.run(_run_maker_pass(
                features=[_tob_features(has_bookmaker_data=False)],
                engine_cfg=EngineConfig(),
                maker_cfg=_maker_cfg(),
                store=store,
            ))
        mock_fetch.assert_not_called()

    def test_missing_tob_path_does_not_call_fetcher(self, tmp_path: Path):
        """Even when TOB is missing the fetcher must NOT be called as fallback."""
        store = PaperMakerStore(base_dir=tmp_path)
        with patch("services.maker.orderbook.fetch_kalshi_orderbook") as mock_fetch:
            asyncio.run(_run_maker_pass(
                features=[_tob_features(best_bid=None, best_ask=None)],
                engine_cfg=EngineConfig(),
                maker_cfg=_maker_cfg(),
                store=store,
            ))
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Source provenance
# ---------------------------------------------------------------------------

class TestBookSourceProvenance:
    def test_eligible_proposal_uses_market_list_top_of_book_source(self, tmp_path: Path):
        """The MakerBookInput built by the pass carries the correct source.
        Indirectly verified: an eligible proposal records best_bid/best_ask
        identical to the features' TOB values, proving that path was used."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(best_bid=0.40, best_ask=0.90)
        asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        rec = store.read_recent(days=2)[0]
        assert rec["best_bid"] == pytest.approx(feat.best_bid)
        assert rec["best_ask"] == pytest.approx(feat.best_ask)
        assert rec["book_fetched_at"] == feat.price_fetched_at


# ---------------------------------------------------------------------------
# Execution route propagation through the full pipeline
# ---------------------------------------------------------------------------

class TestExecutionRouteThroughPipeline:
    """Regression guard for commit 7bba5c6: ensure route fields set on
    ``MarketFeatures`` survive ``_run_maker_pass`` and land in the persisted
    JSONL record.  Caught a stale-data confusion where pre-commit records
    legitimately lacked the fields and fresh-scan validation needed an
    integration-level test, not just unit tests on the planner and store
    in isolation."""

    def test_direct_yes_route_persisted_through_pipeline(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(
            side="Player A",
            market_id="KXATPMATCH-A",
            best_bid_market_id="KXATPMATCH-A",
            best_bid_contract_side="yes",
        )
        asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        rec = store.read_recent(days=2)[0]
        assert rec["status"] == STATUS_PAPER_ACTIVE
        assert rec["display_side"] == "Player A"
        assert rec["execution_market_id"] == "KXATPMATCH-A"
        assert rec["execution_contract_side"] == "yes"
        assert rec["execution_route"] == "direct_yes"

    def test_equivalent_no_route_persisted_through_pipeline(self, tmp_path: Path):
        """Best YES bid for player A came via the M2 ticker's NO contract;
        the persisted record's display_side stays as A but execution_market_id
        and contract_side point at the opposing M2 ticker."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(
            side="Player A",
            market_id="KXATPMATCH-A",
            best_bid_market_id="KXATPMATCH-B",
            best_bid_contract_side="no",
        )
        asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        rec = store.read_recent(days=2)[0]
        assert rec["status"] == STATUS_PAPER_ACTIVE
        assert rec["display_side"] == "Player A"
        # Canonical market_id (legacy display) stays unchanged
        assert rec["market_id"] == "KXATPMATCH-A"
        # But the execution route names the actual contract a paper order
        # would post on
        assert rec["execution_market_id"] == "KXATPMATCH-B"
        assert rec["execution_contract_side"] == "no"
        assert rec["execution_route"] == "equivalent_no"

    def test_legacy_features_fall_back_to_direct_yes_through_pipeline(self, tmp_path: Path):
        """When MarketFeatures.best_bid_market_id is None (older feature
        objects, non-Kalshi platforms), the persisted record still gets
        non-empty defaults: direct YES on the canonical market_id."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(
            side="Player A",
            market_id="K1",
            best_bid_market_id=None,
            best_bid_contract_side=None,
        )
        asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        rec = store.read_recent(days=2)[0]
        assert rec["display_side"] == "Player A"
        assert rec["execution_market_id"] == "K1"
        assert rec["execution_contract_side"] == "yes"
        assert rec["execution_route"] == "direct_yes"

    def test_rejected_proposal_still_carries_route_fields(self, tmp_path: Path):
        """Rejected (ineligible) proposals must also persist route fields so
        the audit trail and UI can describe why a paper order would have
        landed where it would have landed."""
        store = PaperMakerStore(base_dir=tmp_path)
        feat = _tob_features(
            side="Player A",
            market_id="KXATPMATCH-A",
            best_bid_market_id="KXATPMATCH-B",
            best_bid_contract_side="no",
            best_bid=None,        # forces BOOK_CROSSED_OR_EMPTY rejection
        )
        asyncio.run(_run_maker_pass(
            features=[feat],
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        ))
        rec = store.read_recent(days=2)[0]
        assert rec["status"] == STATUS_PAPER_REJECTED
        assert "BOOK_CROSSED_OR_EMPTY" in rec["rejection_reasons"]
        # Route fields persist regardless of eligibility
        assert rec["display_side"] == "Player A"
        assert rec["execution_market_id"] == "KXATPMATCH-B"
        assert rec["execution_contract_side"] == "no"
        assert rec["execution_route"] == "equivalent_no"


# ---------------------------------------------------------------------------
# fetch_opportunities — end-to-end integration
# ---------------------------------------------------------------------------

def _stub_market() -> NormalizedMarket:
    return NormalizedMarket(
        platform="kalshi", market_id="K-EMPTY", event="N/A",
        market_type="h2h", side="", line=None, price=0.50,
        liquidity=100.0, url=None, timestamp=None,
        question="placeholder", end_date=None,
        outcome_prices=["0.50", "0.50"], event_slug="empty",
        fetched_at=time.time(),
    )


class _StubAdapter:
    platform_name = "kalshi"

    def __init__(self, markets):
        self._markets = markets

    async def fetch_markets(self):
        return list(self._markets)


class TestFetchOpportunitiesIntegration:
    def test_disabled_meta_present_no_fetch(self):
        async def _no_odds(*args, **kwargs):
            return [], {}

        with patch("services.opportunities.fetch_odds", side_effect=_no_odds), \
             patch("services.maker.orderbook.fetch_kalshi_orderbook") as mock_fetch:
            opps, meta = asyncio.run(fetch_opportunities(
                cfg=EngineConfig(),
                adapters=[_StubAdapter([_stub_market()])],
            ))

        assert meta["maker_enabled"] is False
        assert meta["maker_proposals_total"] == 0
        mock_fetch.assert_not_called()
        assert "status_counts" in meta
        assert "platforms_fetched" in meta

    def test_enabled_passes_meta_through(self):
        """When maker_cfg.enabled=True with empty markets, meta keys reflect
        zero proposals and the orderbook fetcher is still never called."""
        async def _no_odds(*args, **kwargs):
            return [], {}

        with patch("services.opportunities.fetch_odds", side_effect=_no_odds), \
             patch("services.maker.orderbook.fetch_kalshi_orderbook") as mock_fetch:
            opps, meta = asyncio.run(fetch_opportunities(
                cfg=EngineConfig(),
                adapters=[_StubAdapter([])],
                maker_cfg=MakerConfig(enabled=True, paper_only=True),
            ))

        assert meta["maker_enabled"] is True
        assert meta["maker_proposals_total"] == 0
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Existing taker behavior must not change
# ---------------------------------------------------------------------------

class TestTakerBehaviorUnchanged:
    def test_disabled_meta_keys_added_existing_keys_present(self):
        async def _no_odds(*args, **kwargs):
            return [], {"sports_fetched": ["x"]}

        with patch("services.opportunities.fetch_odds", side_effect=_no_odds):
            opps, meta = asyncio.run(fetch_opportunities(
                cfg=EngineConfig(),
                adapters=[_StubAdapter([])],
            ))

        for k in (
            "maker_enabled",
            "maker_proposals_total",
            "maker_proposals_eligible",
            "maker_proposals_rejected",
        ):
            assert k in meta
        for k in (
            "status_counts",
            "platforms_fetched",
            "opportunities_count",
            "sportsbook_markets_fetched",
        ):
            assert k in meta
        assert opps == []
