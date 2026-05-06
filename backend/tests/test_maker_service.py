"""
Tests for ``MakerService`` — the orchestrator that wires the planner to
the paper store.

The service must:
  * call ``plan_maker_proposal`` for every (features, book) pair
  * persist the result to the supplied ``PaperMakerStore``
  * record ``paper_active`` for eligible proposals, ``paper_rejected`` otherwise
  * never make network calls or place real orders

httpx is patched in one test to assert the service never instantiates
an HTTP client; this is the regression guard against a future commit
accidentally adding live trading I/O to this layer.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from services.engine_config import EngineConfig
from services.maker.config import MakerConfig
from services.maker.orderbook import parse_kalshi_orderbook
from services.maker.planner import MakerBookInput
from services.maker.service import MakerService
from services.maker.state import (
    PaperMakerStore,
    STATUS_PAPER_ACTIVE,
    STATUS_PAPER_REJECTED,
)

# Reuse fixtures from the policy/math test file.
from tests.test_maker_planner_math import _book, _features, _maker_cfg


# ---------------------------------------------------------------------------
# Eligible proposal
# ---------------------------------------------------------------------------

class TestEligibleFlow:
    def test_eligible_proposal_marked_paper_active(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        svc = MakerService(
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        )
        outcome = svc.propose(features=_features(), book=_book(), now=time.time())

        assert outcome.proposal.eligible is True
        assert outcome.status == STATUS_PAPER_ACTIVE

        # Persisted to the store
        records = store.read_recent(days=2)
        assert len(records) == 1
        assert records[0]["status"] == STATUS_PAPER_ACTIVE
        assert records[0]["proposal_id"] == outcome.proposal.proposal_id


# ---------------------------------------------------------------------------
# Rejected proposals
# ---------------------------------------------------------------------------

class TestRejectedFlow:
    def test_rejected_proposal_marked_paper_rejected(self, tmp_path: Path):
        """Polymarket out-of-scope is the simplest rejection — exercises the
        not-eligible code path."""
        store = PaperMakerStore(base_dir=tmp_path)
        svc = MakerService(
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),  # platforms = ("kalshi",)
            store=store,
        )
        outcome = svc.propose(
            features=_features(platform="polymarket"),
            book=_book(),
            now=time.time(),
        )

        assert outcome.proposal.eligible is False
        assert outcome.status == STATUS_PAPER_REJECTED
        assert "PLATFORM_OUT_OF_SCOPE" in outcome.proposal.rejection_reasons

        records = store.read_recent(days=2)
        assert len(records) == 1
        assert records[0]["status"] == STATUS_PAPER_REJECTED
        assert "PLATFORM_OUT_OF_SCOPE" in records[0]["rejection_reasons"]

    def test_disabled_maker_records_paper_rejected(self, tmp_path: Path):
        """When MakerConfig.enabled=False the planner returns ineligible —
        the service still persists the record (for telemetry)."""
        store = PaperMakerStore(base_dir=tmp_path)
        svc = MakerService(
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=MakerConfig(),  # default enabled=False
            store=store,
        )
        outcome = svc.propose(features=_features(), book=_book(), now=time.time())

        assert outcome.status == STATUS_PAPER_REJECTED
        assert "MAKER_DISABLED" in outcome.proposal.rejection_reasons


# ---------------------------------------------------------------------------
# OrderBook input shape
# ---------------------------------------------------------------------------

class TestOrderBookInput:
    def test_accepts_orderbook_object(self, tmp_path: Path):
        """The service should accept a parsed OrderBook (not just MakerBookInput)
        and convert it internally."""
        store = PaperMakerStore(base_dir=tmp_path)
        svc = MakerService(
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        )
        # Best YES bid 0.40, best YES ask = 1 - 0.10 = 0.90
        ts = time.time()
        book = parse_kalshi_orderbook(
            "K1",
            {"orderbook": {"yes": [[40, 10]], "no": [[10, 5]]}},
            fetched_at=ts,
        )
        outcome = svc.propose(features=_features(), book=book, now=ts)

        assert outcome.proposal.best_bid == pytest.approx(0.40)
        assert outcome.proposal.best_ask == pytest.approx(0.90)
        assert outcome.proposal.book_fetched_at == ts
        assert outcome.proposal.eligible is True
        assert outcome.status == STATUS_PAPER_ACTIVE

    def test_accepts_makerbookinput(self, tmp_path: Path):
        """Direct MakerBookInput path is preserved (math tests use this shape)."""
        store = PaperMakerStore(base_dir=tmp_path)
        svc = MakerService(
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        )
        ts = time.time()
        book_input = MakerBookInput(
            best_bid=0.40,
            best_ask=0.90,
            fetched_at=ts,
        )
        outcome = svc.propose(features=_features(), book=book_input, now=ts)
        assert outcome.proposal.eligible is True


# ---------------------------------------------------------------------------
# Multiple proposals over time
# ---------------------------------------------------------------------------

class TestMultipleProposals:
    def test_multiple_proposals_same_day_persist_in_order(self, tmp_path: Path):
        store = PaperMakerStore(base_dir=tmp_path)
        svc = MakerService(
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        )
        ts = time.time()
        ids: list[str] = []
        for market_id in ("M1", "M2", "M3"):
            outcome = svc.propose(
                features=_features(market_id=market_id),
                book=_book(),
                now=ts,
            )
            ids.append(outcome.proposal.proposal_id)

        records = store.read_recent(days=2)
        assert [r["proposal_id"] for r in records] == ids
        assert all(r["status"] == STATUS_PAPER_ACTIVE for r in records)


# ---------------------------------------------------------------------------
# No I/O — service must not place orders or call HTTP
# ---------------------------------------------------------------------------

class TestNoExternalIo:
    def test_service_does_not_instantiate_httpx(self, tmp_path: Path):
        """Regression guard: the service must not create HTTP clients or
        otherwise reach the network.  If a future commit adds live trading
        here, this test will fail loudly."""
        store = PaperMakerStore(base_dir=tmp_path)
        svc = MakerService(
            engine_cfg=EngineConfig(min_edge=0.05, cost_buffer=0.01),
            maker_cfg=_maker_cfg(),
            store=store,
        )

        with patch("httpx.AsyncClient") as mock_async, \
             patch("httpx.Client") as mock_sync:
            outcome = svc.propose(features=_features(), book=_book(), now=time.time())

        assert outcome.proposal.eligible is True
        mock_async.assert_not_called()
        mock_sync.assert_not_called()

    def test_service_default_store_is_paper_only(self):
        """A MakerService constructed without an explicit store still
        defaults to the file-backed PaperMakerStore — no network I/O."""
        svc = MakerService(
            engine_cfg=EngineConfig(),
            maker_cfg=MakerConfig(),
        )
        assert isinstance(svc.store, PaperMakerStore)
