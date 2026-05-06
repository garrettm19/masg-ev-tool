"""
MakerService — the orchestrator that wires the planner to the paper store.

Pure local computation: takes a Pass-A ``MarketFeatures`` plus a Kalshi
``OrderBook``, runs ``plan_maker_proposal``, and persists the resulting
``MakerProposal`` to the ``PaperMakerStore`` with the appropriate
lifecycle status.

This service performs no network I/O, makes no order-placement calls,
and has no live-trading code path.  ``MakerConfig.enabled`` defaults to
``False``; the planner itself returns an ineligible proposal in that case
and we record it as ``paper_rejected`` for the audit trail.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from services.engine_config import EngineConfig
from services.maker.config import MakerConfig
from services.maker.orderbook import OrderBook
from services.maker.planner import (
    MakerBookInput,
    MakerProposal,
    plan_maker_proposal,
)
from services.maker.state import (
    PaperMakerStore,
    STATUS_PAPER_ACTIVE,
    STATUS_PAPER_REJECTED,
)
from services.rule_engine import MarketFeatures

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposalOutcome:
    """One ``propose`` call's result: the proposal record and the status
    under which it was persisted."""
    proposal: MakerProposal
    status: str


def _book_to_input(book: OrderBook) -> MakerBookInput:
    """Convert a parsed ``OrderBook`` into the planner's minimal book input."""
    best_bid = book.best_yes_bid()
    best_ask = book.best_yes_ask()
    return MakerBookInput(
        best_bid=best_bid,
        best_ask=best_ask,
        fetched_at=book.fetched_at,
        best_bid_qty=book.queue_qty_at("yes_bid", best_bid) if best_bid is not None else 0,
        best_ask_qty=book.queue_qty_at("yes_ask", best_ask) if best_ask is not None else 0,
    )


class MakerService:
    """
    Wraps ``plan_maker_proposal`` and persists every outcome to the
    paper store.

    No network I/O, no orders, no MakerConfig.enabled side effects beyond
    what the planner's policy already enforces.
    """

    def __init__(
        self,
        engine_cfg: EngineConfig,
        maker_cfg: MakerConfig,
        store: PaperMakerStore | None = None,
    ):
        self.engine_cfg = engine_cfg
        self.maker_cfg = maker_cfg
        self.store = store if store is not None else PaperMakerStore()

    def propose(
        self,
        features: MarketFeatures,
        book: OrderBook | MakerBookInput,
        *,
        now: float | None = None,
    ) -> ProposalOutcome:
        """
        Plan one maker proposal and persist it.

        Accepts either an ``OrderBook`` (from the parser/fetcher) or a
        ``MakerBookInput`` (already-condensed shape used in tests).  The
        proposal is persisted with status ``paper_active`` if eligible,
        ``paper_rejected`` otherwise — both paths produce a JSONL record
        for the audit trail.
        """
        book_input = (
            _book_to_input(book) if isinstance(book, OrderBook) else book
        )

        proposal = plan_maker_proposal(
            features=features,
            book=book_input,
            engine_cfg=self.engine_cfg,
            maker_cfg=self.maker_cfg,
            now=now,
        )

        status = STATUS_PAPER_ACTIVE if proposal.eligible else STATUS_PAPER_REJECTED
        try:
            self.store.append(proposal, status)
        except OSError as exc:
            # Persistence failure is logged but does NOT raise — callers
            # downstream of the scan pipeline should never crash because
            # paper telemetry didn't write.
            logger.warning(
                "MakerService: failed to persist proposal %s: %s",
                proposal.proposal_id, exc,
            )

        return ProposalOutcome(proposal=proposal, status=status)
