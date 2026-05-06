"""
Maker eligibility policy.

A maker proposal is eligible when:

  1. Every taker safety rule from POLICY_TABLE passes — except the two
     entry-price rules that are intentionally bypassed for maker, because
     a maker bid inside the spread can clear the edge bar even when the
     current ask cannot.
  2. Every maker-only rule (scope, freshness, book sanity, math) passes.

EXCLUDED_TAKER_RULES is the *only* way a taker rule loses authority over
maker eligibility.  Adding a new safety rule to POLICY_TABLE makes it
inherited automatically; entry-price rules must be added to the exclusion
set explicitly so the bypass is auditable in one place.

This module performs no I/O and never places orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from services.engine_config import EngineConfig
from services.maker.config import MakerConfig
from services.maker.tick import TICK_DOLLARS
from services.rule_engine import (
    MarketFeatures,
    PolicyRule,
    POLICY_TABLE,
    RuleResult,
)

if TYPE_CHECKING:
    from services.maker.planner import MakerBookInput


# Taker rules whose failure does NOT block maker.  Both are strictly about
# the taker entry price, which is exactly what a maker bid replaces.
EXCLUDED_TAKER_RULES: frozenset[str] = frozenset({
    "positive_edge",      # NO_EDGE — taker ask too expensive (whole point of maker)
    "edge_threshold",     # EDGE_BELOW_THRESHOLD — thin taker edge (maker can clear)
})


@dataclass(frozen=True)
class MakerContext:
    """Inputs for maker-only rule conditions."""
    book: "MakerBookInput"
    maker_cfg: MakerConfig
    now: float
    proposed_price: float | None
    maker_max_bid: float | None
    estimated_maker_edge: float | None


@dataclass(frozen=True)
class MakerRule:
    """Maker-only policy rule.  All maker rules are CRITICAL — eligibility
    is binary (eligible / not), no DOWNGRADE tier."""
    rule_name: str
    stage: str
    severity: str           # always "CRITICAL" in v1
    condition_fn: Callable[[MarketFeatures, EngineConfig, MakerContext], bool]
    reason_code: str
    description: str


# ---------------------------------------------------------------------------
# Maker-only rule conditions
# ---------------------------------------------------------------------------

def _maker_enabled(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    return ctx.maker_cfg.enabled


def _platform_in_scope(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    return f.platform in ctx.maker_cfg.platforms


def _market_type_in_scope(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    return f.market_type in ctx.maker_cfg.market_types


def _book_fresh(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    if ctx.book.fetched_at <= 0:
        return False
    return ctx.book.fetched_at >= ctx.now - ctx.maker_cfg.max_book_age_seconds


def _fd_fresh(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    if f.fd_fetched_at <= 0:
        return False
    return f.fd_fetched_at >= ctx.now - ctx.maker_cfg.max_fd_age_seconds


def _book_not_crossed(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    book = ctx.book
    if book.best_bid is None or book.best_ask is None:
        return False
    return book.best_bid < book.best_ask


def _spread_wide_enough(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    book = ctx.book
    if book.best_bid is None or book.best_ask is None:
        return False
    spread = book.best_ask - book.best_bid
    threshold = max(2 * TICK_DOLLARS, ctx.maker_cfg.require_min_spread)
    # Use a small epsilon so prices like 0.45 - 0.43 = 0.020000000000000018
    # don't fail at the boundary.
    return spread + 1e-9 >= threshold


def _suggested_bid_inside_spread(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    book = ctx.book
    p = ctx.proposed_price
    if p is None or book.best_bid is None or book.best_ask is None:
        return False
    return book.best_bid < p < book.best_ask


def _proposed_below_max_bid(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    if ctx.proposed_price is None or ctx.maker_max_bid is None:
        return False
    # Allow exact equality at the cap, since round_down_to_tick can land
    # the proposed price exactly on maker_max_bid.
    return ctx.proposed_price <= ctx.maker_max_bid + 1e-9


def _maker_edge_meets_min(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    if ctx.estimated_maker_edge is None:
        return False
    return ctx.estimated_maker_edge + 1e-9 >= ctx.maker_cfg.min_estimated_maker_edge


def _maker_edge_plausible(f: MarketFeatures, c: EngineConfig, ctx: MakerContext) -> bool:
    """Estimated maker edge must not exceed the per-sport plausibility cap.

    Reuses the same cap as the taker ``edge_plausible`` rule — an implausibly
    high estimated maker edge is the same data-error tell.
    """
    if ctx.estimated_maker_edge is None or ctx.estimated_maker_edge <= 0:
        return True

    from services.sports_config import config_for_odds_key
    sc = config_for_odds_key(f.sport)
    limit = sc.max_plausible_edge if sc else c.max_plausible_edge
    return ctx.estimated_maker_edge <= limit


# ---------------------------------------------------------------------------
# Maker-only policy table
# ---------------------------------------------------------------------------

MAKER_RULES: list[MakerRule] = [
    MakerRule(
        rule_name="maker_enabled",
        stage="scope",
        severity="CRITICAL",
        condition_fn=_maker_enabled,
        reason_code="MAKER_DISABLED",
        description="MakerConfig.enabled is False",
    ),
    MakerRule(
        rule_name="platform_in_scope",
        stage="scope",
        severity="CRITICAL",
        condition_fn=_platform_in_scope,
        reason_code="PLATFORM_OUT_OF_SCOPE",
        description="Platform not in MakerConfig.platforms",
    ),
    MakerRule(
        rule_name="market_type_in_scope",
        stage="scope",
        severity="CRITICAL",
        condition_fn=_market_type_in_scope,
        reason_code="MARKET_TYPE_OUT_OF_SCOPE",
        description="Market type not in MakerConfig.market_types",
    ),
    MakerRule(
        rule_name="book_fresh",
        stage="freshness",
        severity="CRITICAL",
        condition_fn=_book_fresh,
        reason_code="BOOK_STALE",
        description="Orderbook snapshot older than MakerConfig.max_book_age_seconds",
    ),
    MakerRule(
        rule_name="fd_fresh",
        stage="freshness",
        severity="CRITICAL",
        condition_fn=_fd_fresh,
        reason_code="FD_STALE",
        description="FanDuel odds older than MakerConfig.max_fd_age_seconds",
    ),
    MakerRule(
        rule_name="book_not_crossed",
        stage="book",
        severity="CRITICAL",
        condition_fn=_book_not_crossed,
        reason_code="BOOK_CROSSED_OR_EMPTY",
        description="Best bid >= best ask, or one side empty",
    ),
    MakerRule(
        rule_name="spread_wide_enough",
        stage="book",
        severity="CRITICAL",
        condition_fn=_spread_wide_enough,
        reason_code="SPREAD_TOO_NARROW",
        description="Spread below max(2 ticks, MakerConfig.require_min_spread)",
    ),
    MakerRule(
        rule_name="suggested_bid_inside_spread",
        stage="math",
        severity="CRITICAL",
        condition_fn=_suggested_bid_inside_spread,
        reason_code="BID_NOT_INSIDE_SPREAD",
        description="Proposed bid not strictly inside best_bid/best_ask",
    ),
    MakerRule(
        rule_name="proposed_below_max_bid",
        stage="math",
        severity="CRITICAL",
        condition_fn=_proposed_below_max_bid,
        reason_code="BID_ABOVE_MAX",
        description="Proposed bid above maker_max_bid",
    ),
    MakerRule(
        rule_name="maker_edge_meets_min",
        stage="math",
        severity="CRITICAL",
        condition_fn=_maker_edge_meets_min,
        reason_code="MAKER_EDGE_TOO_LOW",
        description="Estimated maker edge below MakerConfig.min_estimated_maker_edge",
    ),
    MakerRule(
        rule_name="maker_edge_plausible",
        stage="math",
        severity="CRITICAL",
        condition_fn=_maker_edge_plausible,
        reason_code="MAKER_EDGE_IMPLAUSIBLE",
        description="Estimated maker edge above the sport's max_plausible_edge cap",
    ),
]


# ---------------------------------------------------------------------------
# Eligibility evaluator
# ---------------------------------------------------------------------------

def inherited_taker_rules() -> list[PolicyRule]:
    """Taker rules whose failure also blocks maker eligibility.

    Strict subset of POLICY_TABLE: every rule except those in
    EXCLUDED_TAKER_RULES.  Reading this in one place gives the auditable
    answer to "which taker rules guard maker."
    """
    return [r for r in POLICY_TABLE if r.rule_name not in EXCLUDED_TAKER_RULES]


def evaluate_maker_eligibility(
    features: MarketFeatures,
    engine_cfg: EngineConfig,
    ctx: MakerContext,
) -> tuple[bool, list[str], list[RuleResult]]:
    """
    Evaluate the full maker policy (inherited safety rules + maker-only rules).

    Returns ``(eligible, rejection_reasons, rule_evaluations)`` where:
      * ``eligible`` is True iff every rule passes.
      * ``rejection_reasons`` are the failing reason codes, in evaluation order.
      * ``rule_evaluations`` is the full per-rule trace (passed and failed).

    For maker we treat every inherited taker rule as CRITICAL — there is no
    DOWNGRADE tier in maker eligibility.  Either we'd be willing to commit
    a price to this candidate, or we wouldn't.
    """
    results: list[RuleResult] = []
    reasons: list[str] = []

    # Inherited taker safety rules (every POLICY_TABLE rule except the
    # entry-price exclusions).
    for rule in inherited_taker_rules():
        passed = rule.condition_fn(features, engine_cfg)
        results.append(RuleResult(
            rule_name=rule.rule_name,
            passed=passed,
            severity=rule.severity,
            reason_code=rule.reason_code,
            description=rule.description,
        ))
        if not passed:
            reasons.append(rule.reason_code)

    # Maker-only rules.
    for rule in MAKER_RULES:
        passed = rule.condition_fn(features, engine_cfg, ctx)
        results.append(RuleResult(
            rule_name=rule.rule_name,
            passed=passed,
            severity=rule.severity,
            reason_code=rule.reason_code,
            description=rule.description,
        ))
        if not passed:
            reasons.append(rule.reason_code)

    return (len(reasons) == 0), reasons, results
