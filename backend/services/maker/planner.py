"""
Maker-order planner — pure math + policy evaluation, no I/O.

The planner consumes ``MarketFeatures`` from Pass A directly.  It does NOT
require ``EvaluatedOpportunity.status == "BUY"``: the entire point of a
maker bid is to capture EV when the taker ask is too expensive.  Maker
eligibility is decided by ``MAKER_POLICY_TABLE`` in ``services.maker.policy``.

Math
----
    required_edge   = wide_market_min_edge   if line_width > max_line_width_for_normal_threshold
                      else SportConfig.min_edge or EngineConfig.min_edge
    cost_buffer     = 0.0 for polymarket, EngineConfig.cost_buffer otherwise
    maker_max_bid   = round_down_to_tick(p_true - required_edge - cost_buffer)
    candidate_bid   = round_down_to_tick(best_bid + tick)
    proposed_price  = min(candidate_bid, maker_max_bid)
    estimated_maker_edge = p_true - proposed_price - cost_buffer

Sanitization
------------
``maker_max_bid`` / ``proposed_price`` / ``estimated_maker_edge`` become
``None`` instead of carrying impossible negative-cents values when the
math cannot produce a realizable bid:

    * ``maker_max_bid <= 0``           — p_true too low to clear required
                                         edge + cost buffer.
    * Best bid or best ask missing,
      or book crossed/locked, or the
      candidate inside-spread bid is
      not strictly positive.

In all such cases the proposal is still persisted (with ``eligible=False``
and the corresponding policy reason codes) so the audit trail is complete,
but the price-shaped fields are ``None`` rather than ``-0.01``.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from services.engine_config import EngineConfig
from services.maker.config import MakerConfig
from services.maker.policy import MakerContext, evaluate_maker_eligibility
from services.maker.tick import TICK_DOLLARS, round_down_to_tick
from services.rule_engine import MarketFeatures, RuleResult


@dataclass(frozen=True)
class MakerBookInput:
    """
    Minimal orderbook view consumed by the planner.

    Prices are dollars (0.0–1.0), on tick (cents).  Quantities are contracts.
    ``fetched_at`` is unix seconds; 0.0 means uninitialized and will fail the
    book-fresh maker rule.

    ``source`` is informational provenance — "market_list_top_of_book"
    when the values come from the Kalshi market-list adapter (the v1
    production path), "rest_orderbook" when they come from a depth fetch
    via ``services.maker.orderbook.fetch_kalshi_orderbook``, "ws" for the
    streaming book.  Defaults to "unknown" for legacy callers.
    """
    best_bid: float | None
    best_ask: float | None
    fetched_at: float
    best_bid_qty: int = 0
    best_ask_qty: int = 0
    source: str = "unknown"


@dataclass(frozen=True)
class MakerProposal:
    """Snapshot record for one maker-bid proposal.  Always paper-only in v1.

    ``plan_maker_proposal`` always returns a ``MakerProposal``; the
    ``eligible`` flag indicates whether MAKER_POLICY_TABLE accepted it.
    Storing rejected proposals (with reasons + rule trace) keeps the audit
    trail complete.
    """
    proposal_id: str
    platform: str
    market_id: str
    market_type: str
    side: str
    event_label: str
    event_start: str

    # Snapshot at planning time
    p_true: float
    required_edge: float
    cost_buffer: float
    best_bid: float | None
    best_ask: float | None
    book_fetched_at: float
    fd_fetched_at: float

    # Math.  ``None`` whenever the planner cannot produce a realizable bid
    # (low p_true, missing book, crossed book) — see module docstring.
    # Eligible proposals always have non-None values; the policy table
    # guarantees this via _suggested_bid_inside_spread / _proposed_below_max_bid
    # / _maker_edge_meets_min, all of which fail when their input is None.
    maker_max_bid: float | None
    proposed_price: float | None
    tick_size: float
    estimated_maker_edge: float | None

    # Eligibility
    eligible: bool
    rejection_reasons: tuple[str, ...]
    rule_evaluations: tuple[RuleResult, ...]

    # Provenance / observability — never gating, audit only
    taker_status_at_planning: str
    taker_reject_reasons: tuple[str, ...]
    taker_downgrade_reasons: tuple[str, ...]
    taker_edge_at_planning: float

    # Audit
    created_at: float
    notes: tuple[str, ...]

    # Display + execution route — disambiguates ``market_id``/``side`` for
    # 2-way Kalshi where the cheapest YES exposure may route through the
    # opposing market's NO contract.  ``display_side`` mirrors ``side``
    # for UI clarity.  ``execution_market_id`` and
    # ``execution_contract_side`` describe the actual contract that a
    # paper order would post on.  ``execution_route`` is a coarse
    # categorical: ``"direct_yes"`` or ``"equivalent_no"``.  Defaults
    # preserve legacy direct-YES semantics when callers don't populate
    # them (older fixtures, legacy persisted records).
    display_side: str = ""
    execution_market_id: str = ""
    execution_contract_side: str = "yes"
    execution_route: str = "direct_yes"


def _required_edge_for(features: MarketFeatures, cfg: EngineConfig) -> float:
    """Mirror the taker rule_engine ``_edge_meets_threshold`` minimum-edge
    selection: wide-market threshold for wide lines, else per-sport min,
    else global min."""
    if features.fanduel_line_width > cfg.max_line_width_for_normal_threshold:
        return cfg.wide_market_min_edge

    from services.sports_config import config_for_odds_key
    sc = config_for_odds_key(features.sport)
    return sc.min_edge if sc else cfg.min_edge


def _cost_buffer_for(features: MarketFeatures, cfg: EngineConfig) -> float:
    """Polymarket has no fees; everything else uses ``cfg.cost_buffer``."""
    return 0.0 if features.platform == "polymarket" else cfg.cost_buffer


def plan_maker_proposal(
    features: MarketFeatures,
    book: MakerBookInput,
    engine_cfg: EngineConfig,
    maker_cfg: MakerConfig,
    now: float | None = None,
) -> MakerProposal:
    """
    Build a ``MakerProposal`` for one (features, book) pair.

    Pure function: no I/O, no order placement, no side effects.  Always
    returns a proposal record; ``eligible`` indicates whether the proposal
    passes MAKER_POLICY_TABLE.
    """
    if now is None:
        now = time.time()

    required_edge = _required_edge_for(features, engine_cfg)
    cost_buffer = _cost_buffer_for(features, engine_cfg)

    # maker_max_bid is the math-derived ceiling: highest price at which the
    # required edge survives.  When it computes <= 0 the candidate is
    # un-bidable (p_true too low) — surface as None instead of persisting an
    # impossible negative-cents threshold.
    maker_max_bid_raw = round_down_to_tick(
        features.p_true - required_edge - cost_buffer
    )
    maker_max_bid: float | None = (
        maker_max_bid_raw if maker_max_bid_raw > 0 else None
    )

    # proposed_price requires: positive maker_max_bid, both sides of the
    # book present and not crossed, and a strictly positive candidate.  Any
    # failure leaves it None and the policy table rejects the proposal via
    # BOOK_CROSSED_OR_EMPTY / BID_NOT_INSIDE_SPREAD / etc.
    proposed_price: float | None
    if (
        maker_max_bid is None
        or book.best_bid is None
        or book.best_ask is None
        or book.best_bid >= book.best_ask
    ):
        proposed_price = None
    else:
        candidate_bid = round_down_to_tick(book.best_bid + TICK_DOLLARS)
        candidate = min(candidate_bid, maker_max_bid)
        proposed_price = candidate if candidate > 0 else None

    estimated_maker_edge: float | None = (
        None if proposed_price is None
        else round(features.p_true - proposed_price - cost_buffer, 4)
    )

    ctx = MakerContext(
        book=book,
        maker_cfg=maker_cfg,
        now=now,
        proposed_price=proposed_price,
        maker_max_bid=maker_max_bid,
        estimated_maker_edge=estimated_maker_edge,
    )
    eligible, reasons, rule_evals = evaluate_maker_eligibility(features, engine_cfg, ctx)

    notes: list[str] = ["paper_only"]
    # TAKE_NOT_MAKE only meaningful when both maker_max_bid and best_ask
    # exist — without them the comparison is undefined, not "taker would
    # clear the bar."
    if (
        book.best_ask is not None
        and maker_max_bid is not None
        and book.best_ask <= maker_max_bid
    ):
        # Taking the current ask itself clears the required_edge bar — the
        # taker scanner already covers this case.  Record the note so the
        # audit trail explains why a maker proposal might be redundant.
        notes.append("TAKE_NOT_MAKE")
    notes.append(
        "Maker fills are not guaranteed and may occur when the market is moving against you."
    )

    # Resolve the execution route from the feature's per-side info.  Falls
    # back to direct YES on the canonical market_id when route info is
    # absent (legacy features, non-Kalshi platforms, missing TOB).
    execution_market_id = features.best_bid_market_id or features.market_id
    execution_contract_side = features.best_bid_contract_side or "yes"
    execution_route = (
        "direct_yes" if execution_contract_side == "yes" else "equivalent_no"
    )

    return MakerProposal(
        proposal_id=str(uuid.uuid4()),
        platform=features.platform,
        market_id=features.market_id,
        market_type=features.market_type,
        side=features.side,
        event_label=features.event_label,
        event_start=features.start_time,
        p_true=features.p_true,
        required_edge=required_edge,
        cost_buffer=cost_buffer,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        book_fetched_at=book.fetched_at,
        fd_fetched_at=features.fd_fetched_at,
        maker_max_bid=maker_max_bid,
        proposed_price=proposed_price,
        tick_size=TICK_DOLLARS,
        estimated_maker_edge=estimated_maker_edge,
        eligible=eligible,
        rejection_reasons=tuple(reasons),
        rule_evaluations=tuple(rule_evals),
        taker_status_at_planning=features.status,
        taker_reject_reasons=tuple(features.reject_reasons),
        taker_downgrade_reasons=tuple(features.downgrade_reasons),
        taker_edge_at_planning=features.edge,
        created_at=now,
        notes=tuple(notes),
        display_side=features.side,
        execution_market_id=execution_market_id,
        execution_contract_side=execution_contract_side,
        execution_route=execution_route,
    )
