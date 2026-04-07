"""
Pass A: Feature extraction.

Computes all attributes for each (market, event) candidate without
rejecting anything.  Every candidate gets a fully populated MarketFeatures
object that the rule engine can classify.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from services.adapters.base import NormalizedMarket
from services.devig import devig_multiplicative
from services.engine_config import EngineConfig
from services.normalizer import normalize_name, last_name, tokenize
from services.odds_provider import TennisOddsEvent
from services.rule_engine import MarketFeatures

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _american_to_implied(odds: int) -> float:
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _is_live(commence_time: str) -> bool:
    try:
        start_dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        return start_dt <= datetime.now(timezone.utc)
    except (ValueError, AttributeError):
        return False


def _parse_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _line_width_label(line_width: float) -> str:
    if line_width <= 0.10:
        return "Tight"
    if line_width <= 0.35:
        return "Moderate"
    return "Wide"


def _fd_confidence_label(
    overround: float,
    line_width_label: str,
    cfg: EngineConfig,
) -> str:
    if overround <= cfg.overround_high_max:
        tier = "High"
    elif overround <= cfg.overround_medium_max:
        tier = "Medium"
    else:
        tier = "Low"
    # Wide lines downgrade one tier
    if line_width_label == "Wide":
        if tier == "High":
            tier = "Medium"
        elif tier == "Medium":
            tier = "Low"
    return tier


# ---------------------------------------------------------------------------
# Name scoring (same logic as old matcher, but returns features not decisions)
# ---------------------------------------------------------------------------

def _name_score(
    question_norm: str,
    home_norm: str,
    away_norm: str,
    min_len: int,
) -> tuple[float, list[str]]:
    """
    Returns (score, matched_names).  1.0 if both found, 0.0 otherwise.
    Tries last-name word matching first, then full-name substring.
    """
    words = set(re.findall(r"[a-z]+", question_norm))

    # Strategy 1: last-name matching
    matched: list[str] = []
    for name_norm in (home_norm, away_norm):
        ln = last_name(name_norm)
        if len(ln) >= min_len and ln in words:
            matched.append(name_norm)
    if len(matched) == 2:
        return 1.0, matched

    # Strategy 2: full-name substring (team sports)
    matched_team: list[str] = []
    for name_norm in (home_norm, away_norm):
        if len(name_norm) >= min_len and name_norm in question_norm:
            matched_team.append(name_norm)
    if len(matched_team) == 2:
        return 1.0, matched_team

    return 0.0, matched or matched_team


def _date_score(end_date: str | None, commence_time: str) -> tuple[float, float | None]:
    if not end_date:
        return 0.5, None
    market_dt = _parse_dt(end_date)
    event_dt = _parse_dt(commence_time)
    if market_dt is None or event_dt is None:
        return 0.5, None
    delta_h = abs((market_dt - event_dt).total_seconds()) / 3600.0
    if delta_h <= 6.0:
        return 1.0, delta_h
    if delta_h <= 24.0:
        return 0.95, delta_h
    if delta_h <= 168.0:
        return 0.85, delta_h
    if delta_h <= 504.0:
        return 0.75, delta_h
    return 0.0, delta_h


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
    """Return (yes_player, no_player, outcome_match)."""
    home_last = last_name(home_player_norm)
    away_last = last_name(away_player_norm)

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
# Totals / handicap parsers
# ---------------------------------------------------------------------------

def _parse_totals_question(question: str) -> tuple[str | None, float | None, str | None]:
    q = question.lower()
    if re.search(r'set\s+\d', q):
        return None, None, None
    unit = None
    if "total sets" in q or "sets o/u" in q:
        unit = "set"
    elif "match o/u" in q or "games" in q:
        unit = "game"
    elif "o/u" in q:
        unit = "game"
    m = re.search(r'(\d+\.5)', q)
    if not m:
        return None, None, None
    return "over", float(m.group(1)), unit


def _parse_handicap_question(question: str) -> tuple[str | None, float | None, str | None]:
    q = question.lower()
    unit = None
    if "set" in q:
        unit = "set"
    elif "game" in q:
        unit = "game"
    m = re.search(r'(\w[\w\s]*?)\s*\(\s*-(\d+\.?\d*)\s*\)', q)
    if not m:
        return None, None, None
    return m.group(1).strip(), float(m.group(2)), unit


# ---------------------------------------------------------------------------
# Pass A: extract features for a single (market, event) pair
# ---------------------------------------------------------------------------

def extract_h2h_features(
    market: NormalizedMarket,
    event: TennisOddsEvent,
    name_sc: float,
    matched: list[str],
    date_sc: float,
    delta_h: float | None,
    confidence: float,
    cfg: EngineConfig,
) -> list[MarketFeatures]:
    """
    Build MarketFeatures for an H2H market — one per side (two candidates).
    """
    prices = _parse_prices(market)
    if not prices:
        return []

    pm_yes, pm_no = prices
    has_bm = bool(event.bookmakers)

    if not has_bm:
        # Still produce features so rule engine can log the rejection
        base = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
        base.pm_price = pm_yes
        base.pm_price_no = pm_no
        base.price_in_range = True
        base.has_bookmaker_data = False
        return [base]

    fd = event.bookmakers[0]
    fd_home_impl = _american_to_implied(fd.home_odds)
    fd_away_impl = _american_to_implied(fd.away_odds)
    overround = round(fd_home_impl + fd_away_impl - 1.0, 4)
    p_true_home, p_true_away = devig_multiplicative(fd_home_impl, fd_away_impl)
    line_width = round(abs(p_true_home - p_true_away), 4)
    lw_label = _line_width_label(line_width)

    question_norm = normalize_name(market.question)
    yes_player, no_player, outcome_match = _identify_yes_player(
        question_norm,
        event.home_player_norm,
        event.away_player_norm,
        event.home_player,
        event.away_player,
    )
    yes_is_home = (yes_player == event.home_player)

    sides = [
        (yes_player, pm_yes,
         fd.home_odds if yes_is_home else fd.away_odds,
         fd.away_odds if yes_is_home else fd.home_odds,
         p_true_home if yes_is_home else p_true_away,
         p_true_away if yes_is_home else p_true_home),
        (no_player, pm_no,
         fd.away_odds if yes_is_home else fd.home_odds,
         fd.home_odds if yes_is_home else fd.away_odds,
         p_true_away if yes_is_home else p_true_home,
         p_true_home if yes_is_home else p_true_away),
    ]

    price_consistent = _check_price_consistency(pm_yes, pm_no)

    results: list[MarketFeatures] = []
    for side_name, price, fd_odds, fd_odds_other, p_true, p_true_other in sides:
        f = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
        f.market_type = "h2h"
        f.side = side_name
        f.pm_price = price
        f.pm_price_no = 1.0 - price
        f.pm_price_effective = round(price + cfg.cost_buffer, 4)
        f.price_in_range = cfg.min_price < price < cfg.max_price
        f.prices_internally_consistent = price_consistent

        f.outcome_aligned = outcome_match
        f.yes_player = yes_player
        f.no_player = no_player

        f.fd_odds = fd_odds
        f.fd_odds_other = fd_odds_other
        f.fd_home_implied = fd_home_impl
        f.fd_away_implied = fd_away_impl
        f.p_true = p_true
        f.p_true_other = p_true_other

        f.fanduel_overround = overround
        f.fanduel_line_width = line_width
        f.fanduel_line_width_label = lw_label
        f.fanduel_confidence_label = _fd_confidence_label(overround, lw_label, cfg)

        f.edge = round(p_true - f.pm_price_effective, 4)
        f.has_bookmaker_data = True

        # h2h has no line/unit concerns
        f.line_match_exact = True
        f.unit_match = True
        f.side_match = True

        results.append(f)

    return results


def extract_totals_features(
    market: NormalizedMarket,
    event: TennisOddsEvent,
    name_sc: float,
    matched: list[str],
    date_sc: float,
    delta_h: float | None,
    confidence: float,
    cfg: EngineConfig,
) -> list[MarketFeatures]:
    """Build MarketFeatures for a totals market."""
    prices = _parse_prices(market)
    if not prices:
        return []
    pm_yes, _ = prices

    event_totals = getattr(event, "totals", None) or []
    if not event_totals:
        f = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
        f.market_type = "totals"
        f.pm_price = pm_yes
        f.pm_price_effective = round(pm_yes + cfg.cost_buffer, 4)
        f.price_in_range = cfg.min_price < pm_yes < cfg.max_price
        f.has_bookmaker_data = False
        return [f]

    pm_side, pm_line, pm_unit = _parse_totals_question(market.question)
    if pm_side is None or pm_line is None:
        f = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
        f.market_type = "totals"
        f.pm_price = pm_yes
        f.pm_price_effective = round(pm_yes + cfg.cost_buffer, 4)
        f.price_in_range = cfg.min_price < pm_yes < cfg.max_price
        f.has_bookmaker_data = True
        f.outcome_aligned = False  # can't parse question
        return [f]

    # Find matching sportsbook line
    matching_total = None
    for tl in event_totals:
        if abs(tl.point - pm_line) < 0.01:
            matching_total = tl
            break

    f = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
    f.market_type = "totals"
    f.side = "Over"
    f.line = pm_line
    f.pm_price = pm_yes
    f.pm_price_effective = round(pm_yes + cfg.cost_buffer, 4)
    f.price_in_range = cfg.min_price < pm_yes < cfg.max_price
    f.outcome_aligned = True  # O/U YES = Over is a known convention
    f.has_bookmaker_data = True

    f.line_match_exact = matching_total is not None
    f.unit_match = pm_unit != "set"  # sportsbook totals are games
    f.side_match = True  # not applicable to totals

    if matching_total:
        over_impl = _american_to_implied(matching_total.over_odds)
        under_impl = _american_to_implied(matching_total.under_odds)
        overround = round(over_impl + under_impl - 1.0, 4)
        p_true_over, p_true_under = devig_multiplicative(over_impl, under_impl)
        line_width = round(abs(p_true_over - p_true_under), 4)
        lw_label = _line_width_label(line_width)

        f.fd_odds = matching_total.over_odds
        f.fd_odds_other = matching_total.under_odds
        f.p_true = p_true_over
        f.p_true_other = p_true_under
        f.fanduel_overround = overround
        f.fanduel_line_width = line_width
        f.fanduel_line_width_label = lw_label
        f.fanduel_confidence_label = _fd_confidence_label(overround, lw_label, cfg)
        f.edge = round(p_true_over - f.pm_price_effective, 4)

    return [f]


def extract_handicap_features(
    market: NormalizedMarket,
    event: TennisOddsEvent,
    name_sc: float,
    matched: list[str],
    date_sc: float,
    delta_h: float | None,
    confidence: float,
    cfg: EngineConfig,
) -> list[MarketFeatures]:
    """Build MarketFeatures for a handicap market."""
    prices = _parse_prices(market)
    if not prices:
        return []
    pm_yes, _ = prices

    event_spreads = getattr(event, "spreads", None) or []
    if not event_spreads:
        f = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
        f.market_type = "handicap"
        f.pm_price = pm_yes
        f.pm_price_effective = round(pm_yes + cfg.cost_buffer, 4)
        f.price_in_range = cfg.min_price < pm_yes < cfg.max_price
        f.has_bookmaker_data = False
        return [f]

    pm_favored_norm, pm_line, pm_unit = _parse_handicap_question(market.question)
    if pm_favored_norm is None or pm_line is None:
        f = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
        f.market_type = "handicap"
        f.pm_price = pm_yes
        f.pm_price_effective = round(pm_yes + cfg.cost_buffer, 4)
        f.price_in_range = cfg.min_price < pm_yes < cfg.max_price
        f.has_bookmaker_data = True
        f.outcome_aligned = False
        return [f]

    # Find matching sportsbook spread
    matching_spread = None
    for sl in event_spreads:
        if abs(abs(sl.home_point) - pm_line) < 0.01:
            matching_spread = sl
            break

    f = _base_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
    f.market_type = "handicap"
    f.line = -pm_line
    f.pm_price = pm_yes
    f.pm_price_effective = round(pm_yes + cfg.cost_buffer, 4)
    f.price_in_range = cfg.min_price < pm_yes < cfg.max_price
    f.outcome_aligned = True
    f.has_bookmaker_data = True

    f.line_match_exact = matching_spread is not None
    f.unit_match = not pm_unit or pm_unit == "set"

    if matching_spread:
        # Determine sportsbook favored player
        if matching_spread.home_point < 0:
            sb_favored_norm = event.home_player_norm
            sb_favored = event.home_player
            sb_fav_odds = matching_spread.home_odds
            sb_dog_odds = matching_spread.away_odds
        else:
            sb_favored_norm = event.away_player_norm
            sb_favored = event.away_player
            sb_fav_odds = matching_spread.away_odds
            sb_dog_odds = matching_spread.home_odds

        f.side = sb_favored

        # Side match check
        sb_fav_last = last_name(sb_favored_norm)
        f.side_match = (
            sb_fav_last in pm_favored_norm or pm_favored_norm in sb_favored_norm
        )

        fav_impl = _american_to_implied(sb_fav_odds)
        dog_impl = _american_to_implied(sb_dog_odds)
        overround = round(fav_impl + dog_impl - 1.0, 4)
        p_true_fav, p_true_dog = devig_multiplicative(fav_impl, dog_impl)
        line_width = round(abs(p_true_fav - p_true_dog), 4)
        lw_label = _line_width_label(line_width)

        f.fd_odds = sb_fav_odds
        f.fd_odds_other = sb_dog_odds
        f.p_true = p_true_fav
        f.p_true_other = p_true_dog
        f.fanduel_overround = overround
        f.fanduel_line_width = line_width
        f.fanduel_line_width_label = lw_label
        f.fanduel_confidence_label = _fd_confidence_label(overround, lw_label, cfg)
        f.edge = round(p_true_fav - f.pm_price_effective, 4)
    else:
        f.side_match = False

    return [f]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_prices(market: NormalizedMarket) -> tuple[float, float] | None:
    if not market.outcome_prices or len(market.outcome_prices) < 2:
        return None
    try:
        pm_yes = float(market.outcome_prices[0])
        pm_no = float(market.outcome_prices[1])
    except (ValueError, TypeError):
        return None
    if not (0.01 <= pm_yes <= 0.99):
        return None
    if not (0.01 <= pm_no <= 0.99):
        pm_no = round(1.0 - pm_yes, 4)
    return pm_yes, pm_no


def _detect_last_name_collision(
    home_norm: str,
    away_norm: str,
    question_norm: str,
) -> tuple[bool, bool]:
    """
    Detect if a player's last name collides with the other player's name tokens.

    Example: home="Alex de Minaur", away="Daniil Medvedev"
    If "de" appears in both normalized names, that's a token collision risk.

    Returns (home_collision, away_collision).
    """
    home_ln = last_name(home_norm)
    away_ln = last_name(away_norm)

    # Collision = one player's last name is a substring/token of the other
    # player's full normalized name (e.g., "lee" in both "lee duck hee" and "felix lee")
    home_collision = (
        len(home_ln) >= 3
        and home_ln != away_ln
        and home_ln in away_norm.split()
    )
    away_collision = (
        len(away_ln) >= 3
        and away_ln != home_ln
        and away_ln in home_norm.split()
    )
    return home_collision, away_collision


def _check_price_consistency(pm_yes: float, pm_no: float) -> bool:
    """YES + NO should sum to approximately 1.0 (within 15% tolerance for PM spreads)."""
    total = pm_yes + pm_no
    return 0.85 <= total <= 1.15


def _base_features(
    market: NormalizedMarket,
    event: TennisOddsEvent,
    name_sc: float,
    matched: list[str],
    date_sc: float,
    delta_h: float | None,
    confidence: float,
    cfg: EngineConfig,
) -> MarketFeatures:
    """Create a MarketFeatures with all common fields populated."""
    event_label = f"{event.home_player} vs {event.away_player}"
    question_norm = normalize_name(market.question)

    home_coll, away_coll = _detect_last_name_collision(
        event.home_player_norm, event.away_player_norm, question_norm,
    )

    return MarketFeatures(
        platform=market.platform,
        market_id=market.market_id,
        sport=event.sport_key,
        event_label=event_label,
        event_url=market.url,
        tournament=event.tournament,
        start_time=event.commence_time,
        market_type=market.market_type,
        question=market.question,
        home_player=event.home_player,
        away_player=event.away_player,
        home_player_norm=event.home_player_norm,
        away_player_norm=event.away_player_norm,
        name_match_score=name_sc,
        matched_players=tuple(matched),
        date_score=date_sc,
        date_delta_hours=delta_h,
        event_match_confidence=confidence,
        match_quality="verified" if confidence >= cfg.buy_threshold else "unverified",
        is_live=_is_live(event.commence_time),
        matched_event_id=event.event_id,
        best_match_confidence=confidence,
        # Ambiguity: last-name collision
        home_last_name_collision=home_coll,
        away_last_name_collision=away_coll,
        # Metadata quality
        has_end_date=bool(market.end_date),
        has_outcome_prices=bool(market.outcome_prices and len(market.outcome_prices) >= 2),
        # Observability tokens
        home_tokens=tuple(tokenize(event.home_player_norm)),
        away_tokens=tuple(tokenize(event.away_player_norm)),
        question_tokens=tuple(sorted(set(re.findall(r"[a-z]+", question_norm)))),
    )


# ---------------------------------------------------------------------------
# Dispatcher: extract features for any market type
# ---------------------------------------------------------------------------

def extract_features(
    market: NormalizedMarket,
    event: TennisOddsEvent,
    cfg: EngineConfig,
) -> list[MarketFeatures]:
    """
    Extract features for a (market, event) pair.

    Returns 0-2 MarketFeatures objects (H2H produces two sides).
    All features are computed; nothing is filtered.
    """
    question_norm = normalize_name(market.question)

    name_sc, matched = _name_score(
        question_norm,
        event.home_player_norm,
        event.away_player_norm,
        cfg.min_name_length,
    )

    # Fast reject: no name match at all → don't produce features
    # (this is the only hard filter in Pass A — it's O(M×E) so we skip
    # candidates that have zero overlap to avoid noise)
    if name_sc == 0.0:
        return []

    date_sc, delta_h = _date_score(market.end_date, event.commence_time)
    confidence = round(name_sc * 0.65 + date_sc * 0.35, 3)

    mt = market.market_type
    if mt == "h2h":
        return extract_h2h_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
    elif mt == "totals":
        return extract_totals_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)
    elif mt == "handicap":
        return extract_handicap_features(market, event, name_sc, matched, date_sc, delta_h, confidence, cfg)

    return []
