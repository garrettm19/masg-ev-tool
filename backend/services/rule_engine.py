"""
Rule engine for opportunity classification.

Two-pass system:
  Pass A  — Feature extraction (no filtering)
  Pass B  — Rule evaluation → BUY / WATCH / SKIP

Every rule is defined in the POLICY_TABLE. No classification logic lives
outside this module.  Each rule has:
  - rule_name       unique identifier
  - stage           pipeline stage for traceability
  - severity        CRITICAL (fail → SKIP) or DOWNGRADE (fail → WATCH)
  - condition_fn    (features, config) → bool  (True = pass, False = fail)
  - reason_code     short string for logs and API output
  - description     human-readable explanation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from services.engine_config import EngineConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MarketFeatures:
    """
    All computed attributes for a single market candidate.

    Populated in Pass A (feature extraction) — nothing is rejected yet.
    """
    # Identity
    platform: str = ""
    market_id: str = ""
    sport: str = ""
    event_label: str = ""
    event_url: str | None = None
    tournament: str = ""
    start_time: str = ""
    market_type: str = ""             # h2h, totals, handicap, ...
    side: str = ""
    line: float | None = None
    question: str = ""

    # Platform pricing
    pm_price: float = 0.0
    pm_price_no: float = 0.0
    pm_price_effective: float = 0.0   # pm_price + cost_buffer

    # Matching
    home_player: str = ""
    away_player: str = ""
    home_player_norm: str = ""
    away_player_norm: str = ""
    name_match_score: float = 0.0
    matched_players: tuple[str, ...] = ()
    date_score: float = 0.0
    date_delta_hours: float | None = None
    event_match_confidence: float = 0.0
    match_quality: str = "unverified"

    # Outcome alignment
    outcome_aligned: bool = False      # both players found in question
    yes_player: str = ""
    no_player: str = ""

    # FanDuel odds (raw)
    fd_odds: int = 0                   # American odds for this side
    fd_odds_other: int = 0             # American odds for the other side
    fd_home_implied: float = 0.0
    fd_away_implied: float = 0.0

    # Devigged
    p_true: float = 0.0
    p_true_other: float = 0.0

    # FanDuel metrics
    fanduel_overround: float = 0.0
    fanduel_line_width: float = 0.0
    fanduel_line_width_label: str = ""
    fanduel_confidence_label: str = ""

    # Totals / handicap specifics
    line_match_exact: bool = False
    unit_match: bool = False
    side_match: bool = False           # handicap: same player favored on both

    # Computed
    edge: float = 0.0

    # Price validity
    price_in_range: bool = False
    has_bookmaker_data: bool = False
    is_live: bool = False

    # Ambiguity metrics (populated by pipeline after cross-matching)
    best_match_confidence: float = 0.0      # this candidate's confidence
    second_best_confidence: float = 0.0     # next-best event's confidence
    confidence_gap: float = 1.0             # best - second_best (1.0 = no rival)
    competing_matches: int = 0              # how many events survived matching
    matched_event_id: str = ""              # sportsbook event id for this match
    second_best_event_id: str = ""          # runner-up event id (if any)
    has_shared_last_name: bool = False       # two events share a player last name
    home_last_name_collision: bool = False   # home last name matches BOTH event players
    away_last_name_collision: bool = False   # away last name matches BOTH event players

    # Data quality
    bid_ask_spread: float | None = None      # yes_ask - yes_bid; None if unavailable

    # Top-of-book — copied from NormalizedMarket.  Maker planning will read
    # these directly so it doesn't have to fetch /orderbook per feature.
    best_bid: float | None = None
    best_ask: float | None = None

    # Metadata quality
    has_end_date: bool = False               # market has a resolution date
    has_outcome_prices: bool = False          # market has parseable outcome prices
    prices_internally_consistent: bool = True # YES + NO prices sum to ~1.0

    # Staleness tracking
    price_fetched_at: float = 0.0      # when platform price was obtained
    fd_fetched_at: float = 0.0         # when FanDuel odds were obtained (for maker FD-staleness gate)

    # Observability: normalized player tokens (for debugging)
    home_tokens: tuple[str, ...] = ()
    away_tokens: tuple[str, ...] = ()
    question_tokens: tuple[str, ...] = ()

    # Classification (filled by Pass B)
    status: str = ""
    reject_reasons: list[str] = field(default_factory=list)
    downgrade_reasons: list[str] = field(default_factory=list)
    kelly_fraction: float = 0.0
    kelly_full: float = 0.0


@dataclass(frozen=True)
class RuleResult:
    rule_name: str
    passed: bool
    severity: str          # "CRITICAL" | "DOWNGRADE" | "INFO"
    reason_code: str
    description: str


@dataclass(frozen=True)
class PolicyRule:
    rule_name: str
    stage: str
    severity: str                          # CRITICAL | DOWNGRADE | INFO
    condition_fn: Callable[[MarketFeatures, EngineConfig], bool]
    reason_code: str
    description: str


# ---------------------------------------------------------------------------
# Rule condition functions
# ---------------------------------------------------------------------------

def _price_in_range(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.price_in_range


def _not_live(f: MarketFeatures, c: EngineConfig) -> bool:
    return not f.is_live


def _has_bookmaker_data(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.has_bookmaker_data


def _name_match(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.name_match_score >= 1.0


def _outcome_aligned(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.outcome_aligned


def _confidence_above_survival(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.event_match_confidence >= c.survival_threshold


def _confidence_above_buy(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.event_match_confidence >= c.buy_threshold


def _line_match_exact(f: MarketFeatures, c: EngineConfig) -> bool:
    if f.market_type in ("totals", "handicap"):
        return f.line_match_exact
    return True  # h2h has no line


def _unit_match(f: MarketFeatures, c: EngineConfig) -> bool:
    if f.market_type in ("totals", "handicap"):
        return f.unit_match
    return True


def _side_match(f: MarketFeatures, c: EngineConfig) -> bool:
    if f.market_type == "handicap":
        return f.side_match
    return True


def _positive_edge(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.edge > 0


def _min_true_prob(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.p_true >= c.min_true_probability


def _edge_meets_threshold(f: MarketFeatures, c: EngineConfig) -> bool:
    from services.sports_config import config_for_odds_key

    # Wide markets always use the stricter wide-market threshold
    if f.fanduel_line_width > c.max_line_width_for_normal_threshold:
        return f.edge >= c.wide_market_min_edge

    # Per-sport threshold: liquid sports (NBA, MLB, NHL) use lower min_edge
    sc = config_for_odds_key(f.sport)
    threshold = sc.min_edge if sc else c.min_edge
    return f.edge >= threshold


def _fd_confidence_not_low(f: MarketFeatures, c: EngineConfig) -> bool:
    return f.fanduel_confidence_label != "Low"


def _confidence_gap_sufficient(f: MarketFeatures, c: EngineConfig) -> bool:
    """Pass if no close rival event, or gap is large enough."""
    if f.competing_matches <= 1:
        return True  # only one match — no ambiguity
    return f.confidence_gap >= c.min_confidence_gap


def _no_shared_last_name(f: MarketFeatures, c: EngineConfig) -> bool:
    """Pass if no other event shares a player last name with this match."""
    return not f.has_shared_last_name


def _no_excess_competing_matches(f: MarketFeatures, c: EngineConfig) -> bool:
    """Pass if competing matches are within tolerance."""
    return f.competing_matches <= c.max_competing_matches


def _no_last_name_collision(f: MarketFeatures, c: EngineConfig) -> bool:
    """Pass if neither player's last name collides with both event players."""
    return not f.home_last_name_collision and not f.away_last_name_collision


def _price_probability_coherent(f: MarketFeatures, c: EngineConfig) -> bool:
    """
    Pass if pm_price and p_true are on the same side of the market.

    When the market price diverges wildly from the devigged probability
    (e.g., pm_price=0.20 vs p_true=0.65), the YES/NO side is likely
    inverted — the price is for the opponent, not the featured team.
    """
    if f.p_true <= 0 or f.pm_price <= 0:
        return True  # can't check without valid data
    divergence = abs(f.p_true - f.pm_price)
    return divergence <= c.max_price_prob_divergence


def _date_not_stale(f: MarketFeatures, c: EngineConfig) -> bool:
    """
    Pass if the date delta between platform market and FD event is within
    the per-sport max_date_delta_hours.

    Liquid team sports (MLB, NBA, NHL, NFL, soccer, ...) override the lenient
    global default down to 12h via SportConfig.  This prevents wrong-game
    matches in multi-game series where the same teams play across days.

    Note: a previous version of this rule exempted ``competing_matches > 1``
    on the assumption "series dedup picks the closest event."  That holds
    only when ``end_date`` carries the actual game start time.  When the
    adapter falls back to a date-only end_date, ALL same-team series games
    score similarly and dedup may pick a wrong game; the exemption then
    masked it.  The cap is now always enforced — adapters must produce an
    accurate game start time (or accept SKIPs for ambiguous series).
    """
    if f.date_delta_hours is None:
        return True  # no date info — can't check

    from services.sports_config import config_for_odds_key
    sc = config_for_odds_key(f.sport)
    limit = sc.max_date_delta_hours if sc else c.max_date_delta_hours
    return f.date_delta_hours <= limit


def _edge_plausible(f: MarketFeatures, c: EngineConfig) -> bool:
    """
    Pass if the edge is within a plausible range for this sport.

    Uses sport-specific max_plausible_edge from SportConfig when an exact
    match exists for the FD odds_api key.  Falls back to the global
    EngineConfig.max_plausible_edge when no config matches.

    Uses the same exact mapping as _date_not_stale (config_for_odds_key)
    so sibling sports (basketball_wnba vs basketball_nba, baseball_kbo vs
    baseball_mlb) cannot accidentally inherit each other's caps via prefix
    matching.
    """
    if f.edge <= 0:
        return True  # no edge — nothing to check

    from services.sports_config import config_for_odds_key
    sc = config_for_odds_key(f.sport)
    limit = sc.max_plausible_edge if sc else c.max_plausible_edge
    return f.edge <= limit


def _metadata_complete(f: MarketFeatures, c: EngineConfig) -> bool:
    """Pass if required metadata is present."""
    if c.require_end_date and not f.has_end_date:
        return False
    return f.has_outcome_prices


def _prices_consistent(f: MarketFeatures, c: EngineConfig) -> bool:
    """Pass if YES + NO prices are internally consistent (sum near 1.0)."""
    return f.prices_internally_consistent


# ---------------------------------------------------------------------------
# Policy Table — the single source of truth
# ---------------------------------------------------------------------------

POLICY_TABLE: list[PolicyRule] = [
    # --- Stage: fetch ---
    PolicyRule(
        rule_name="price_range",
        stage="fetch",
        severity="CRITICAL",
        condition_fn=_price_in_range,
        reason_code="PRICE_OUT_OF_RANGE",
        description="PM price must be within (0.02, 0.98)",
    ),
    PolicyRule(
        rule_name="not_live",
        stage="fetch",
        severity="CRITICAL",
        condition_fn=_not_live,
        reason_code="EVENT_LIVE",
        description="Event has already started (live betting not supported)",
    ),
    PolicyRule(
        rule_name="has_bookmaker",
        stage="fetch",
        severity="CRITICAL",
        condition_fn=_has_bookmaker_data,
        reason_code="NO_BOOKMAKER_DATA",
        description="No FanDuel bookmaker data available for this event",
    ),

    # --- Stage: match ---
    PolicyRule(
        rule_name="name_match",
        stage="match",
        severity="CRITICAL",
        condition_fn=_name_match,
        reason_code="NAME_MISMATCH",
        description="Both player names must match between PM and sportsbook",
    ),
    PolicyRule(
        rule_name="outcome_alignment",
        stage="match",
        severity="CRITICAL",
        condition_fn=_outcome_aligned,
        reason_code="OUTCOME_NOT_ALIGNED",
        description="Cannot determine YES/NO player mapping from question text",
    ),
    PolicyRule(
        rule_name="confidence_survival",
        stage="match",
        severity="CRITICAL",
        condition_fn=_confidence_above_survival,
        reason_code="CONFIDENCE_BELOW_SURVIVAL",
        description=f"Event match confidence below survival threshold",
    ),

    # --- Stage: alignment (totals/handicap-specific) ---
    PolicyRule(
        rule_name="line_match",
        stage="alignment",
        severity="CRITICAL",
        condition_fn=_line_match_exact,
        reason_code="LINE_MISMATCH",
        description="Totals/handicap line must match exactly between platforms",
    ),
    PolicyRule(
        rule_name="unit_match",
        stage="alignment",
        severity="CRITICAL",
        condition_fn=_unit_match,
        reason_code="UNIT_MISMATCH",
        description="Market unit (games/sets) must match between platforms",
    ),
    PolicyRule(
        rule_name="side_match",
        stage="alignment",
        severity="CRITICAL",
        condition_fn=_side_match,
        reason_code="SIDE_MISMATCH",
        description="Handicap favored player must match between platforms",
    ),

    # --- Stage: date validation ---
    PolicyRule(
        rule_name="date_not_stale",
        stage="date",
        severity="CRITICAL",
        condition_fn=_date_not_stale,
        reason_code="DATE_TOO_FAR",
        description="PM market date is too far from FD event — likely different game",
    ),

    # --- Stage: pricing ---
    PolicyRule(
        rule_name="price_prob_coherence",
        stage="pricing",
        severity="CRITICAL",
        condition_fn=_price_probability_coherent,
        reason_code="PRICE_PROB_DIVERGENCE",
        description="Market price and true probability diverge too much — likely side inversion",
    ),
    PolicyRule(
        rule_name="positive_edge",
        stage="pricing",
        severity="CRITICAL",
        condition_fn=_positive_edge,
        reason_code="NO_EDGE",
        description="Edge must be positive (p_true > pm_price + cost_buffer)",
    ),
    PolicyRule(
        rule_name="min_true_prob",
        stage="pricing",
        severity="CRITICAL",
        condition_fn=_min_true_prob,
        reason_code="TRUE_PROB_TOO_LOW",
        description="True probability below minimum threshold",
    ),

    # --- Stage: quality (DOWNGRADE rules — failure = WATCH, not SKIP) ---
    PolicyRule(
        rule_name="confidence_buy",
        stage="quality",
        severity="DOWNGRADE",
        condition_fn=_confidence_above_buy,
        reason_code="CONFIDENCE_BELOW_BUY",
        description="Event match confidence below BUY threshold (between survival and buy)",
    ),
    PolicyRule(
        rule_name="edge_threshold",
        stage="quality",
        severity="DOWNGRADE",
        condition_fn=_edge_meets_threshold,
        reason_code="EDGE_BELOW_THRESHOLD",
        description="Edge below minimum threshold for market width",
    ),
    PolicyRule(
        rule_name="fd_confidence",
        stage="quality",
        severity="DOWNGRADE",
        condition_fn=_fd_confidence_not_low,
        reason_code="FD_CONFIDENCE_LOW",
        description="FanDuel confidence is Low (high overround or wide line)",
    ),

    PolicyRule(
        rule_name="edge_plausible",
        stage="quality",
        severity="DOWNGRADE",
        condition_fn=_edge_plausible,
        reason_code="EDGE_IMPLAUSIBLE",
        description="Edge exceeds plausible maximum — likely data error or wrong game",
    ),

    # --- Stage: ambiguity (DOWNGRADE — uncertain matching must not BUY) ---
    PolicyRule(
        rule_name="confidence_gap",
        stage="ambiguity",
        severity="DOWNGRADE",
        condition_fn=_confidence_gap_sufficient,
        reason_code="AMBIGUOUS_MATCH_GAP",
        description="Multiple event candidates with close confidence scores",
    ),
    PolicyRule(
        rule_name="shared_last_name",
        stage="ambiguity",
        severity="DOWNGRADE",
        condition_fn=_no_shared_last_name,
        reason_code="SHARED_LAST_NAME",
        description="Another event shares a player last name (ambiguous mapping)",
    ),
    PolicyRule(
        rule_name="competing_matches",
        stage="ambiguity",
        severity="DOWNGRADE",
        condition_fn=_no_excess_competing_matches,
        reason_code="EXCESS_COMPETING_MATCHES",
        description="Too many sportsbook events matched this market",
    ),
    PolicyRule(
        rule_name="last_name_collision",
        stage="ambiguity",
        severity="DOWNGRADE",
        condition_fn=_no_last_name_collision,
        reason_code="LAST_NAME_COLLISION",
        description="Player last name matches multiple event participants (ambiguous mapping)",
    ),

    # --- Stage: metadata (DOWNGRADE — incomplete data must not BUY) ---
    PolicyRule(
        rule_name="metadata_complete",
        stage="metadata",
        severity="DOWNGRADE",
        condition_fn=_metadata_complete,
        reason_code="INCOMPLETE_METADATA",
        description="Market is missing required metadata (end date or prices)",
    ),
    PolicyRule(
        rule_name="prices_consistent",
        stage="metadata",
        severity="DOWNGRADE",
        condition_fn=_prices_consistent,
        reason_code="PRICES_INCONSISTENT",
        description="YES + NO prices do not sum to approximately 1.0",
    ),
]


# ---------------------------------------------------------------------------
# Classification engine
# ---------------------------------------------------------------------------

def evaluate_rules(
    features: MarketFeatures,
    config: EngineConfig,
) -> tuple[str, list[RuleResult]]:
    """
    Evaluate all policy rules against a set of market features.

    Returns (status, rule_results) where:
      - status is "BUY", "WATCH", or "SKIP"
      - rule_results is the full evaluation trace
    """
    results: list[RuleResult] = []
    critical_failures: list[str] = []
    downgrade_failures: list[str] = []

    for rule in POLICY_TABLE:
        passed = rule.condition_fn(features, config)
        results.append(RuleResult(
            rule_name=rule.rule_name,
            passed=passed,
            severity=rule.severity,
            reason_code=rule.reason_code,
            description=rule.description,
        ))
        if not passed:
            if rule.severity == "CRITICAL":
                critical_failures.append(rule.reason_code)
            elif rule.severity == "DOWNGRADE":
                downgrade_failures.append(rule.reason_code)

    if critical_failures:
        status = "SKIP"
    elif downgrade_failures:
        status = "WATCH"
    else:
        status = "BUY"

    # Populate features with classification results
    features.status = status
    features.reject_reasons = critical_failures
    features.downgrade_reasons = downgrade_failures

    return status, results


def compute_kelly(features: MarketFeatures, config: EngineConfig) -> None:
    """Compute Kelly sizing (only meaningful for BUY, but computed for all positive-edge)."""
    if features.edge <= 0 or features.pm_price_effective >= 1.0:
        features.kelly_full = 0.0
        features.kelly_fraction = 0.0
        return

    full = max(0.0, (features.p_true - features.pm_price_effective) / (1.0 - features.pm_price_effective))
    full = min(full, config.kelly_cap)
    features.kelly_full = round(full, 6)
    features.kelly_fraction = round(full * config.kelly_fraction, 6)
