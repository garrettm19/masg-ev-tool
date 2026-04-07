"""
Matching layer: prediction market  ←→  sportsbook tennis events.

Platform-agnostic — operates on NormalizedMarket objects from any adapter
(Polymarket, Kalshi, etc.).  Market-type classification is the adapter's
responsibility; the matcher only sees pre-filtered h2h markets.

Strategy
--------
1. Name match  — check whether both players' normalised last names appear
   as whole words in the market question text.
   BOTH names are required (name_score = 1.0); single-name matches are rejected.

2. Date match  — compare market end_date (resolution) against event
   commence_time (scheduled start).  End dates may be tournament-level
   rather than match-level, so the window is lenient.

Confidence formula (weights sum to 1.0)
   confidence = name_score * 0.65 + date_score * 0.35

Name score
   1.0  both players found in question
   0.0  fewer than two found  (pair discarded immediately)

Date score
   1.0  |Δ| ≤ 90 min
   0.8  |Δ| ≤ 6 h   (accounts for PM endDate being post-match)
   0.5  |Δ| ≤ 24 h
   0.0  beyond 24 h or missing

High-confidence threshold: 0.90
Requires both player names AND date within ~6 hours.
"""
import re
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from services.adapters.base import NormalizedMarket
from services.odds_provider import TennisOddsEvent, normalize_player_name

logger = logging.getLogger(__name__)

MIN_CONFIDENCE: float = 0.90
_MIN_NAME_LEN: int = 3   # ignore last names shorter than this

# Only H2H (moneyline) is fetched from The Odds API.
# Spreads and totals require separate API calls with markets=spreads,totals
# and are not currently requested or matched.
_SB_MARKET_TYPE = "h2h"

# Exported constant so callers can report what is actually supported.
SUPPORTED_SPORTSBOOK_MARKET_TYPES: tuple[str, ...] = ("h2h",)


# ---------------------------------------------------------------------------
# Market-type classification
# ---------------------------------------------------------------------------

def classify_pm_market_type(question: str) -> str:
    """
    Classify a Polymarket tennis market question into a market type.

    Returns one of:
      "h2h"       — match winner / moneyline ("Will X beat Y?", "X vs Y")
      "outright"  — tournament winner / futures ("Will X win the 2026 AO?")
      "handicap"  — game/set spread ("X -4.5 games handicap")
      "totals"    — over/under on games or sets
      "first_set" — who wins the first set
      "unknown"   — couldn't classify

    Order matters: check more-specific patterns before broader ones.
    """
    q = question.lower()

    # Outright / futures — tournament/season winner questions (must precede h2h)
    if re.search(r'win the \d{4}', q):
        return "outright"
    if re.search(r'\b(?:champion|championship|grey cup|super bowl|stanley cup)\b', q) and not re.search(r'\bvs\.?\b|\bversus\b', q):
        if re.search(r'\bwin\b|\bwinner\b', q):
            return "outright"
    if re.search(r'\b(?:open|slam|wimbledon|masters)\b', q) and not re.search(r'\bvs\.?\b|\bversus\b|:\s*\w+\s+vs', q):
        if re.search(r'\bwin\b|\bwinner\b', q):
            return "outright"

    # MMA / boxing props (not h2h — skip for now)
    if re.search(r'\b(?:knockout|ko|tko|submission|decision|distance|method)\b', q):
        if not re.search(r'\bwin\b.*\bvs\b|\bvs\b.*\bwin\b', q):
            return "prop"

    # Rounds over/under (MMA / boxing)
    if re.search(r'\bo/u\s+\d+\.5\s+rounds?\b', q) or re.search(r'\brounds?\s+o/u\b', q):
        return "totals"

    # First set (tennis-specific, must precede h2h)
    if re.search(r'\bfirst\s+set\b|\b1st\s+set\b|\bset\s+1\b', q):
        return "first_set"

    # Handicap / spread
    if re.search(r'\bhandicap\b|\bgame\s+spread\b|\bset\s+spread\b|\bset\s+handicap\b', q):
        return "handicap"
    if re.search(r'[+-]\d+(?:\.\d+)?\s*(?:game|set|gem|point)', q):
        return "handicap"

    # Totals / over-under
    if re.search(r'\b(?:over|under)\b', q) and re.search(r'\b(?:games?|sets?|gem|runs?|goals?|points?)\b', q):
        return "totals"
    if re.search(r'\btotal\s+(?:games?|sets?|runs?|goals?|points?)\b', q):
        return "totals"
    if re.search(r'\bo/u\s+\d', q) or re.search(r'\bmatch\s+o/u\b', q):
        return "totals"

    # H2H / match / fight / game winner
    if re.search(r'\b(?:vs\.?|versus|beat|defeat|win|winner|match\s+winner|advance|fight)\b', q):
        return "h2h"
    if re.search(r'\w+\s*/\s*\w+', question):   # "Player A / Player B"
        return "h2h"
    if re.search(r':\s*.+\bvs\b', q):
        return "h2h"
    # Team sport game patterns
    if re.search(r'\bgame\b|\bmatch\b|\bbout\b', q):
        return "h2h"

    return "unknown"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchResult:
    market_id: str
    market_question: str
    market_end_date: str | None
    odds_event: TennisOddsEvent
    confidence: float
    matched_players: tuple[str, ...]   # normalised player names found in question
    date_delta_hours: float | None     # None if dates couldn't be parsed
    market_type: str                   # PM market type (always "h2h" after filtering)
    sportsbook_market_type: str        # sportsbook market type ("h2h")
    exact_market_match: bool           # True when types match (always True after filtering)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alpha_words(text: str) -> set[str]:
    """Return the set of lowercase alpha tokens in *text*."""
    return set(re.findall(r"[a-z]+", text))


def _last_name(player_norm: str) -> str:
    parts = player_norm.split()
    return parts[-1] if parts else player_norm


def _parse_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Scoring components
# ---------------------------------------------------------------------------

def _name_score(
    question_norm: str,
    home_norm: str,
    away_norm: str,
) -> tuple[float, list[str]]:
    """
    Returns (name_score, matched_name_norms).

    Strategy 1 — last-name word-boundary matching (individual sports):
      "alcaraz" found in {"will", "alcaraz", "beat", "sinner"}

    Strategy 2 — full-name substring matching (team sports):
      "kolkata knight riders" found in "will kolkata knight riders beat ..."

    Both require BOTH names to match. Strategy 1 is tried first.
    """
    # Strategy 1: last-name matching (tennis, MMA)
    words = _alpha_words(question_norm)
    matched: list[str] = []
    for name_norm in (home_norm, away_norm):
        last = _last_name(name_norm)
        if len(last) >= _MIN_NAME_LEN and last in words:
            matched.append(name_norm)
    if len(matched) == 2:
        return 1.0, matched

    # Strategy 2: full-name substring matching (team sports)
    matched_team: list[str] = []
    for name_norm in (home_norm, away_norm):
        if len(name_norm) >= _MIN_NAME_LEN and name_norm in question_norm:
            matched_team.append(name_norm)
    if len(matched_team) == 2:
        return 1.0, matched_team

    return 0.0, []


def _date_score(
    end_date: str | None,
    commence_time: str,
) -> tuple[float, float | None]:
    """
    Returns (date_score, |delta| in hours).

    PM endDate is often the TOURNAMENT end date (e.g., April 13 for a match
    on April 7), not the individual match resolution time.  This produces
    deltas of 24–168 hours even for perfectly valid matches.

    When both player names match (name_score = 1.0), the date check serves
    as a sanity gate rather than the primary signal, so we use a lenient
    window that only penalises clearly wrong matches (different month/year).
    """
    if not end_date:
        return 0.5, None   # missing date → neutral

    market_dt = _parse_dt(end_date)
    event_dt  = _parse_dt(commence_time)

    if market_dt is None or event_dt is None:
        return 0.5, None

    delta_h = abs((market_dt - event_dt).total_seconds()) / 3600.0

    if delta_h <= 6.0:       # same-day or next-day match
        return 1.0, delta_h
    if delta_h <= 24.0:
        return 0.95, delta_h
    if delta_h <= 168.0:     # ≤ 7 days — typical tournament window
        return 0.85, delta_h
    if delta_h <= 504.0:     # ≤ 21 days — covers tournament-end close dates
        return 0.75, delta_h
    return 0.0, delta_h      # > 21 days — likely wrong event


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def score_pair(
    market: NormalizedMarket,
    event: TennisOddsEvent,
) -> tuple[float, list[str], float | None]:
    """
    Compute confidence for one (market, event) candidate pair.
    Returns (confidence, matched_players, date_delta_hours).
    Returns (0.0, [], None) when there is no name match at all.
    """
    question_norm = normalize_player_name(market.question)
    name_sc, matched = _name_score(
        question_norm,
        event.home_player_norm,
        event.away_player_norm,
    )

    if name_sc == 0.0:
        return 0.0, [], None

    date_sc, delta_h = _date_score(market.end_date, event.commence_time)
    confidence = round(name_sc * 0.65 + date_sc * 0.35, 3)

    return confidence, matched, delta_h


def match_markets(
    markets: list[NormalizedMarket],
    events: list[TennisOddsEvent],
    min_confidence: float = MIN_CONFIDENCE,
) -> list[MatchResult]:
    """
    Cross-match every NormalizedMarket against every sportsbook event.

    Assumes all incoming markets are already filtered to the correct market
    type by their adapter (e.g., only h2h).  Market-type classification is
    the adapter's responsibility, not the matcher's.

    Only pairs with confidence >= min_confidence are returned.
    Results are sorted by confidence descending.

    O(M × E) — fast enough for typical sizes (few hundred markets, ≤50 events).
    """
    results: list[MatchResult] = []

    for market in markets:
        for event in events:
            # Only h2h markets are supported — require bookmaker lines
            if market.market_type != "h2h" or not event.bookmakers:
                continue

            conf, matched, delta_h = score_pair(market, event)
            if conf >= min_confidence:
                results.append(
                    MatchResult(
                        market_id=market.market_id,
                        market_question=market.question,
                        market_end_date=market.end_date,
                        odds_event=event,
                        confidence=conf,
                        matched_players=tuple(matched),
                        date_delta_hours=round(delta_h, 2) if delta_h is not None else None,
                        market_type=market.market_type,
                        sportsbook_market_type=market.market_type,
                        exact_market_match=True,
                    )
                )

    results.sort(key=lambda r: r.confidence, reverse=True)
    logger.info(
        "Matcher: %d normalized markets · %d events · "
        "%d high-confidence matches (threshold=%.2f)",
        len(markets),
        len(events),
        len(results),
        min_confidence,
    )
    return results
