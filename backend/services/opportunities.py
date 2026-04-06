"""
Opportunities pipeline: prediction markets × FanDuel tennis.

Platform-agnostic engine.  Accepts NormalizedMarket objects from any adapter
(Polymarket, Kalshi, etc.) and compares them against FanDuel truth odds.
Every row is normalised to a SINGLE side so there is no YES/NO ambiguity.

Pipeline
--------
1. Fetch markets from all adapters + FanDuel odds in parallel.
2. Match normalized markets to FanDuel events by player names + dates.
3. Identify Yes player from question text; normalise to a single side.
4. Devig FanDuel odds → true probability for the normalised side.
5. Compute line width, overround, and confidence (FanDuel only).
6. Compute edge = p_true − (pm_price + cost_buffer).
7. Apply line-width-aware edge thresholds.
8. Kelly: binary contract formula, clamped [0, 0.25], × 0.2.
9. Deduplicate by (platform, event, market_type, side, line).
10. Status: BUY / WATCH / SKIP.

Read-only.  No trade execution.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from services.adapters import MarketAdapter, NormalizedMarket, PolymarketAdapter, KalshiAdapter
from services.odds_provider import fetch_odds, normalize_player_name
from services.matcher import match_markets, MatchResult, SUPPORTED_SPORTSBOOK_MARKET_TYPES
from services.devig import devig_multiplicative

logger = logging.getLogger(__name__)

_BOOKMAKER = "fanduel"
_COST_BUFFER: float = 0.01       # 1¢ trading cost buffer


# ---------------------------------------------------------------------------
# Configurable thresholds — edit here before future automation
# ---------------------------------------------------------------------------

@dataclass
class EngineConfig:
    """All tuneable thresholds in one place."""
    min_true_probability: float = 0.40
    min_edge: float = 0.05
    wide_market_min_edge: float = 0.08
    max_line_width_for_normal_threshold: float = 0.35
    min_event_match_confidence: float = 0.90


DEFAULT_CONFIG = EngineConfig()

# Default adapter set — add new adapters here
DEFAULT_ADAPTERS: list[MarketAdapter] = [PolymarketAdapter(), KalshiAdapter()]


# ---------------------------------------------------------------------------
# Output type — normalised to a single side
# ---------------------------------------------------------------------------

@dataclass
class Opportunity:
    # Platform & sport
    platform: str                    # "polymarket" | "kalshi" | ...
    sport: str                       # odds API sport_key (e.g., "tennis_atp_monte_carlo_masters")

    # Event identity
    event: str                       # "Player A vs Player B"
    event_url: str | None            # platform-specific URL
    tournament: str
    start_time: str                  # ISO-8601 UTC (FanDuel commence_time)

    # Market identity
    market_id: str
    market_type: str                 # "h2h" | "handicap" | "totals" | "first_set"
    side: str                        # player name (h2h) or "Over"/"Under"
    line: float | None               # handicap/totals line; None for h2h

    # Pricing — all for the SAME normalised side
    pm_price: float                  # platform price for this side
    fd_odds: int                     # FanDuel American odds for this side
    p_true: float                    # devigged true probability for this side
    edge: float                      # p_true − pm_price_effective
    recommended_kelly: float         # clamped quarter-Kelly × 0.2

    # FanDuel metrics (FanDuel only — platform price is NOT used)
    fanduel_overround: float
    fanduel_line_width: float        # abs(p_true_home − p_true_away)
    fanduel_line_width_label: str    # "Tight" | "Moderate" | "Wide"
    fanduel_confidence_label: str    # "High" | "Medium" | "Low"

    # Event match quality
    event_match_confidence: float    # 0–1 from the matcher

    # Status
    status: str                      # "BUY" | "WATCH" | "SKIP"


# ---------------------------------------------------------------------------
# Outcome alignment
# ---------------------------------------------------------------------------

def _identify_yes_player(
    question_norm: str,
    home_player_norm: str,
    away_player_norm: str,
    home_player: str,
    away_player: str,
) -> tuple[str, str, bool]:
    """
    Return (yes_player, no_player, outcome_match).

    outcome_match is True only when BOTH player last names are found in the
    question.  The Yes player is whichever player's normalised last name
    appears first in the question (standard convention).
    """
    home_last = home_player_norm.split()[-1] if home_player_norm.split() else home_player_norm
    away_last = away_player_norm.split()[-1] if away_player_norm.split() else away_player_norm

    home_m = re.search(r"\b" + re.escape(home_last) + r"\b", question_norm)
    away_m = re.search(r"\b" + re.escape(away_last) + r"\b", question_norm)

    home_pos = home_m.start() if home_m else -1
    away_pos = away_m.start() if away_m else -1

    outcome_match = home_pos >= 0 and away_pos >= 0

    if home_pos >= 0 and away_pos >= 0:
        if home_pos < away_pos:
            return home_player, away_player, True
        return away_player, home_player, True

    if home_pos >= 0:
        return home_player, away_player, False
    if away_pos >= 0:
        return away_player, home_player, False

    return home_player, away_player, False


# ---------------------------------------------------------------------------
# FanDuel-only helpers
# ---------------------------------------------------------------------------

def _american_to_implied(odds: int) -> float:
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _line_width_label(line_width: float) -> str:
    if line_width <= 0.10:
        return "Tight"
    if line_width <= 0.35:
        return "Moderate"
    return "Wide"


def _fd_confidence_label(overround: float, line_width_label: str) -> str:
    if overround <= 0.03:
        tier = "High"
    elif overround <= 0.06:
        tier = "Medium"
    else:
        tier = "Low"

    if line_width_label == "Wide":
        if tier == "High":
            tier = "Medium"
        elif tier == "Medium":
            tier = "Low"

    return tier


def _required_edge(line_width: float, cfg: EngineConfig) -> float:
    if line_width > cfg.max_line_width_for_normal_threshold:
        return cfg.wide_market_min_edge
    return cfg.min_edge


def _status(
    edge: float,
    p_true: float,
    fd_confidence: str,
    event_confidence: float,
    line_width: float,
    cfg: EngineConfig,
) -> str:
    req_edge = _required_edge(line_width, cfg)
    if (
        edge >= req_edge
        and p_true >= cfg.min_true_probability
        and fd_confidence != "Low"
        and event_confidence >= cfg.min_event_match_confidence
    ):
        return "BUY"
    if edge > 0 and p_true >= cfg.min_true_probability:
        return "WATCH"
    return "SKIP"


# ---------------------------------------------------------------------------
# Core: build normalised opportunities from a single match
# ---------------------------------------------------------------------------

def _is_live(event: object) -> bool:
    """Check if event has already started."""
    try:
        start_dt = datetime.fromisoformat(
            event.commence_time.replace("Z", "+00:00")  # type: ignore[union-attr]
        )
        return start_dt <= datetime.now(timezone.utc)
    except (ValueError, AttributeError):
        return False


def _parse_prices(market: NormalizedMarket) -> tuple[float, float] | None:
    """Extract (yes_price, no_price) from outcome_prices."""
    if not market.outcome_prices or len(market.outcome_prices) < 2:
        return None
    try:
        pm_yes = float(market.outcome_prices[0])
        pm_no = float(market.outcome_prices[1])
    except (ValueError, TypeError):
        return None
    if not (0.02 < pm_yes < 0.98):
        return None
    if not (0.02 < pm_no < 0.98):
        pm_no = round(1.0 - pm_yes, 4)
    return pm_yes, pm_no


def _build_opportunity(
    platform: str,
    sport: str,
    event_label: str,
    url: str | None,
    tournament: str,
    start_time: str,
    market_id: str,
    market_type: str,
    side: str,
    line: float | None,
    pm_price: float,
    fd_odds: int,
    p_true: float,
    overround: float,
    line_width: float,
    match_confidence: float,
    cfg: EngineConfig,
) -> Opportunity | None:
    """Compute edge, kelly, status and return Opportunity or None."""
    pm_eff = pm_price + _COST_BUFFER
    edge = round(p_true - pm_eff, 4)

    if p_true < cfg.min_true_probability or edge <= 0:
        return None

    if pm_eff >= 1.0:
        full_kelly = 0.0
    else:
        full_kelly = max(0.0, (p_true - pm_eff) / (1.0 - pm_eff))
    full_kelly = min(full_kelly, 0.25)
    rec_kelly = round(full_kelly * 0.2, 4)

    lw_label = _line_width_label(line_width)
    fd_confidence = _fd_confidence_label(overround, lw_label)
    status = _status(edge, p_true, fd_confidence, match_confidence, line_width, cfg)

    return Opportunity(
        platform=platform,
        sport=sport,
        event=event_label,
        event_url=url,
        tournament=tournament,
        start_time=start_time,
        market_id=market_id,
        market_type=market_type,
        side=side,
        line=line,
        pm_price=pm_price,
        fd_odds=fd_odds,
        p_true=p_true,
        edge=edge,
        recommended_kelly=rec_kelly,
        fanduel_overround=overround,
        fanduel_line_width=line_width,
        fanduel_line_width_label=lw_label,
        fanduel_confidence_label=fd_confidence,
        event_match_confidence=match_confidence,
        status=status,
    )


def _extract_line_from_question(question: str) -> float | None:
    """Extract numeric line from question (e.g., 'O/U 22.5' -> 22.5)."""
    m = re.search(r'(\d+\.5)', question)
    return float(m.group(1)) if m else None


def _enrich(
    match: MatchResult,
    market: NormalizedMarket,
    cfg: EngineConfig = DEFAULT_CONFIG,
) -> list[Opportunity]:
    """
    Build normalised Opportunity rows from a MatchResult + NormalizedMarket.

    Dispatches to market-type-specific logic:
    - H2H: two candidate rows (one per player)
    - Totals: over/under at a specific line
    - Handicap: spread at a specific line
    """
    event = match.odds_event

    if _is_live(event):
        return []

    prices = _parse_prices(market)
    if not prices:
        return []
    pm_yes, pm_no = prices

    event_label = f"{event.home_player} vs {event.away_player}"

    if match.market_type == "h2h":
        return _enrich_h2h(match, market, event, event_label, pm_yes, pm_no, cfg)
    elif match.market_type == "totals":
        return _enrich_totals(match, market, event, event_label, pm_yes, cfg)
    elif match.market_type == "handicap":
        return _enrich_handicap(match, market, event, event_label, pm_yes, cfg)

    return []


def _enrich_h2h(
    match: MatchResult,
    market: NormalizedMarket,
    event: object,
    event_label: str,
    pm_yes: float,
    pm_no: float,
    cfg: EngineConfig,
) -> list[Opportunity]:
    """H2H enrichment — two sides (one per player)."""
    if not event.bookmakers:
        return []
    fd = event.bookmakers[0]

    fd_home_impl = _american_to_implied(fd.home_odds)
    fd_away_impl = _american_to_implied(fd.away_odds)
    overround = round(fd_home_impl + fd_away_impl - 1.0, 4)
    p_true_home, p_true_away = devig_multiplicative(fd_home_impl, fd_away_impl)
    line_width = round(abs(p_true_home - p_true_away), 4)

    question_norm = normalize_player_name(market.question)
    yes_player, no_player, outcome_match = _identify_yes_player(
        question_norm,
        event.home_player_norm,
        event.away_player_norm,
        event.home_player,
        event.away_player,
    )
    if not outcome_match:
        return []

    yes_is_home = (yes_player == event.home_player)

    sides = [
        (yes_player, pm_yes,
         fd.home_odds if yes_is_home else fd.away_odds,
         p_true_home if yes_is_home else p_true_away),
        (no_player, pm_no,
         fd.away_odds if yes_is_home else fd.home_odds,
         p_true_away if yes_is_home else p_true_home),
    ]

    results = []
    for side_name, price, fd_odds, p_true in sides:
        opp = _build_opportunity(
            market.platform, event.sport_key, event_label, market.url,
            event.tournament, event.commence_time, market.market_id,
            "h2h", side_name, None,
            price, fd_odds, p_true, overround, line_width,
            match.confidence, cfg,
        )
        if opp:
            results.append(opp)
    return results


def _enrich_totals(
    match: MatchResult,
    market: NormalizedMarket,
    event: object,
    event_label: str,
    pm_yes: float,
    cfg: EngineConfig,
) -> list[Opportunity]:
    """Totals enrichment — over/under at a specific line."""
    if not event.totals:
        return []

    # Extract line from question (e.g., "Match O/U 22.5")
    question_line = _extract_line_from_question(market.question)
    if question_line is None:
        return []

    # Find matching sportsbook total line
    matching_total = None
    for tl in event.totals:
        if abs(tl.point - question_line) < 0.01:
            matching_total = tl
            break

    if not matching_total:
        return []

    over_impl = _american_to_implied(matching_total.over_odds)
    under_impl = _american_to_implied(matching_total.under_odds)
    overround = round(over_impl + under_impl - 1.0, 4)
    p_true_over, p_true_under = devig_multiplicative(over_impl, under_impl)
    line_width = round(abs(p_true_over - p_true_under), 4)

    # Determine if PM question is asking about Over or Under
    q_lower = market.question.lower()
    is_over = "over" in q_lower or "o/u" in q_lower

    if is_over:
        opp = _build_opportunity(
            market.platform, event.sport_key, event_label, market.url,
            event.tournament, event.commence_time, market.market_id,
            "totals", "Over", question_line, pm_yes,
            matching_total.over_odds, p_true_over, overround, line_width,
            match.confidence, cfg,
        )
    else:
        opp = _build_opportunity(
            market.platform, event.sport_key, event_label, market.url,
            event.commence_time, market.market_id, "totals",
            "Under", question_line, pm_yes,
            matching_total.under_odds, p_true_under, overround, line_width,
            match.confidence, cfg,
        )

    return [opp] if opp else []


def _enrich_handicap(
    match: MatchResult,
    market: NormalizedMarket,
    event: object,
    event_label: str,
    pm_yes: float,
    cfg: EngineConfig,
) -> list[Opportunity]:
    """Handicap/spread enrichment."""
    if not event.spreads:
        return []

    question_line = _extract_line_from_question(market.question)
    if question_line is None:
        return []

    # Find matching spread line
    matching_spread = None
    for sl in event.spreads:
        if abs(abs(sl.home_point) - question_line) < 0.01:
            matching_spread = sl
            break

    if not matching_spread:
        return []

    home_impl = _american_to_implied(matching_spread.home_odds)
    away_impl = _american_to_implied(matching_spread.away_odds)
    overround = round(home_impl + away_impl - 1.0, 4)
    p_true_home, p_true_away = devig_multiplicative(home_impl, away_impl)
    line_width = round(abs(p_true_home - p_true_away), 4)

    # Determine which player the PM market is about
    question_norm = normalize_player_name(market.question)
    yes_player, _, outcome_match = _identify_yes_player(
        question_norm,
        event.home_player_norm,
        event.away_player_norm,
        event.home_player,
        event.away_player,
    )
    if not outcome_match:
        return []

    yes_is_home = (yes_player == event.home_player)
    spread_point = matching_spread.home_point if yes_is_home else matching_spread.away_point
    fd_odds = matching_spread.home_odds if yes_is_home else matching_spread.away_odds
    p_true = p_true_home if yes_is_home else p_true_away

    opp = _build_opportunity(
        market.platform, event.sport_key, event_label, market.url,
        event.tournament, event.commence_time, market.market_id,
        "handicap", yes_player, spread_point, pm_yes,
        fd_odds, p_true, overround, line_width,
        match.confidence, cfg,
    )
    return [opp] if opp else []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _dedup_key(opp: Opportunity) -> tuple:
    """(platform, event, market_type, side, line)."""
    return (opp.platform, opp.event, opp.market_type, opp.side, opp.line)


def _deduplicate(opps: list[Opportunity]) -> list[Opportunity]:
    best: dict[tuple, Opportunity] = {}
    for opp in opps:
        key = _dedup_key(opp)
        if key not in best or opp.edge > best[key].edge:
            best[key] = opp
    return list(best.values())


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def fetch_opportunities(
    cfg: EngineConfig = DEFAULT_CONFIG,
    adapters: list[MarketAdapter] | None = None,
) -> tuple[list[Opportunity], dict]:
    """
    Full pipeline:
      1. Fetch markets from all adapters + FanDuel odds in parallel.
      2. Match normalized markets to FanDuel events.
      3. Normalise each match to single-side rows.
      4. Apply filters, Kelly, status.
      5. Deduplicate and sort by edge descending.
    """
    if adapters is None:
        adapters = DEFAULT_ADAPTERS

    # Fetch all sources in parallel
    adapter_results = await asyncio.gather(
        *[a.fetch_markets() for a in adapters],
        fetch_odds(bookmaker=_BOOKMAKER, max_sports=25),
    )

    # Last result is the FanDuel odds tuple
    odds_events, meta = adapter_results[-1]
    # All other results are lists of NormalizedMarket
    all_markets: list[NormalizedMarket] = []
    for adapter_markets in adapter_results[:-1]:
        all_markets.extend(adapter_markets)

    # Match against FanDuel
    matches = match_markets(
        all_markets, odds_events, min_confidence=cfg.min_event_match_confidence,
    )

    market_by_id: dict[str, NormalizedMarket] = {m.market_id: m for m in all_markets}

    all_opps: list[Opportunity] = []
    for match in matches:
        mkt = market_by_id.get(match.market_id)
        if not mkt:
            continue
        all_opps.extend(_enrich(match, mkt, cfg=cfg))

    opportunities = _deduplicate(all_opps)
    opportunities.sort(key=lambda o: o.edge, reverse=True)

    platforms_fetched = [a.platform_name for a in adapters]

    # Collect dropped_by_type from adapters that track it
    dropped_by_type: dict[str, int] = {}
    for adapter in adapters:
        if hasattr(adapter, "dropped_by_type"):
            for k, v in adapter.dropped_by_type.items():
                dropped_by_type[k] = dropped_by_type.get(k, 0) + v

    logger.info(
        "Opportunities: %d markets (%s) · %d FD events · "
        "%d matches · %d sides · %d after dedup",
        len(all_markets),
        ", ".join(f"{p}={sum(1 for m in all_markets if m.platform == p)}" for p in platforms_fetched),
        len(odds_events),
        len(matches),
        len(all_opps),
        len(opportunities),
    )

    meta["opportunities_count"] = len(opportunities)
    meta["sportsbook_markets_fetched"] = list(SUPPORTED_SPORTSBOOK_MARKET_TYPES)
    meta["markets_dropped_by_type"] = dropped_by_type
    meta["platforms_fetched"] = platforms_fetched
    return opportunities, meta


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------

async def diagnose_pipeline(
    cfg: EngineConfig = DEFAULT_CONFIG,
    adapters: list[MarketAdapter] | None = None,
) -> dict:
    """
    Run the full pipeline but collect diagnostic info at every stage.
    """
    from services.matcher import classify_pm_market_type, score_pair

    if adapters is None:
        adapters = DEFAULT_ADAPTERS

    adapter_results = await asyncio.gather(
        *[a.fetch_markets() for a in adapters],
        fetch_odds(bookmaker=_BOOKMAKER, max_sports=25),
    )

    odds_events, meta = adapter_results[-1]
    all_markets: list[NormalizedMarket] = []
    for adapter_markets in adapter_results[:-1]:
        all_markets.extend(adapter_markets)

    # Dropped by type from adapters
    dropped_by_type: dict[str, int] = {}
    for adapter in adapters:
        if hasattr(adapter, "dropped_by_type"):
            for k, v in adapter.dropped_by_type.items():
                dropped_by_type[k] = dropped_by_type.get(k, 0) + v

    # Stage 1: per-platform counts
    platform_counts: dict[str, int] = {}
    for m in all_markets:
        platform_counts[m.platform] = platform_counts.get(m.platform, 0) + 1

    # Stage 2: matching
    match_details: list[dict] = []
    for m in all_markets[:50]:
        best_conf = 0.0
        best_detail: dict | None = None
        for ev in odds_events:
            conf, matched, delta_h = score_pair(m, ev)
            if conf > best_conf:
                best_conf = conf
                best_detail = {
                    "platform": m.platform,
                    "question": m.question[:80],
                    "fd_event": f"{ev.home_player} vs {ev.away_player}",
                    "confidence": conf,
                    "matched_players": matched,
                    "date_delta_hours": round(delta_h, 2) if delta_h is not None else None,
                    "passes_threshold": conf >= cfg.min_event_match_confidence,
                }
        if best_detail:
            match_details.append(best_detail)

    # Stage 3: enrichment
    matches = match_markets(
        all_markets, odds_events, min_confidence=cfg.min_event_match_confidence,
    )

    market_by_id = {m.market_id: m for m in all_markets}

    permissive_cfg = EngineConfig(
        min_true_probability=0.0,
        min_edge=-1.0,
        wide_market_min_edge=-1.0,
        max_line_width_for_normal_threshold=cfg.max_line_width_for_normal_threshold,
        min_event_match_confidence=cfg.min_event_match_confidence,
    )

    enrich_details: list[dict] = []
    for match in matches:
        mkt = market_by_id.get(match.market_id)
        if not mkt:
            continue

        opps = _enrich(match, mkt, cfg=permissive_cfg)
        if not opps:
            enrich_details.append({
                "platform": mkt.platform,
                "market_id": mkt.market_id,
                "question": mkt.question[:80],
                "reason": "no positive edge or unmappable",
            })
        else:
            for opp in opps:
                req_edge = _required_edge(opp.fanduel_line_width, cfg)
                enrich_details.append({
                    "platform": opp.platform,
                    "market_id": opp.market_id,
                    "event": opp.event,
                    "side": opp.side,
                    "pm_price": opp.pm_price,
                    "fd_odds": opp.fd_odds,
                    "p_true": opp.p_true,
                    "edge": opp.edge,
                    "fanduel_line_width": opp.fanduel_line_width,
                    "fanduel_line_width_label": opp.fanduel_line_width_label,
                    "required_edge": req_edge,
                    "passes_edge": opp.edge >= req_edge,
                    "status": _status(
                        opp.edge, opp.p_true, opp.fanduel_confidence_label,
                        match.confidence, opp.fanduel_line_width, cfg,
                    ),
                })

    fd_sample = [
        {
            "event_id": ev.event_id,
            "event": f"{ev.home_player} vs {ev.away_player}",
            "tournament": ev.tournament,
            "commence_time": ev.commence_time,
            "bookmaker_count": len(ev.bookmakers),
        }
        for ev in odds_events[:20]
    ]

    return {
        "config": {
            "min_true_probability": cfg.min_true_probability,
            "min_edge": cfg.min_edge,
            "wide_market_min_edge": cfg.wide_market_min_edge,
            "max_line_width_for_normal_threshold": cfg.max_line_width_for_normal_threshold,
            "min_event_match_confidence": cfg.min_event_match_confidence,
        },
        "stage_1_fetch": {
            "platforms": platform_counts,
            "total_markets": len(all_markets),
            "fd_events": len(odds_events),
            "fd_sports_fetched": meta.get("sports_fetched", []),
            "dropped_by_type": dropped_by_type,
        },
        "stage_2_match": {
            "matches_passing": len(matches),
            "best_match_per_market": match_details,
        },
        "stage_3_enrich": {
            "details": enrich_details,
        },
        "fd_events_sample": fd_sample,
    }
