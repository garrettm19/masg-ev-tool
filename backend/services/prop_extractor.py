"""
Player prop feature extraction.

Matches prediction market prop questions against FanDuel PropLines.
Strict matching: full player name, exact prop type, exact line, clear side.

Produces MarketFeatures objects that enter the same Pass B rule engine
as h2h features. Returns at most ONE feature per prop (the asked side).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from services.adapters.base import NormalizedMarket
from services.devig import devig_multiplicative
from services.engine_config import EngineConfig
from services.feature_extractor import _cost_buffer
from services.normalizer import normalize_name
from services.odds_provider import PropEvent, PropLine
from services.rule_engine import MarketFeatures

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prop type classification
# ---------------------------------------------------------------------------

# Maps Odds API prop key → set of keywords that identify it in a question.
# Order: more specific patterns first to avoid ambiguity.
_PROP_TYPE_PATTERNS: dict[str, list[str]] = {
    # NBA
    "player_points_rebounds_assists": [
        r"points?\s*\+?\s*rebounds?\s*\+?\s*assists?",
        r"pts?\s*\+?\s*reb\s*\+?\s*ast",
        r"\bpra\b",
    ],
    "player_points": [r"\bpoints?\b", r"\bpts\b"],
    "player_rebounds": [r"\brebounds?\b", r"\brebs?\b"],
    "player_assists": [r"\bassists?\b", r"\bast\b"],
    "player_threes": [
        r"\bthree\s*pointers?\b", r"\b3[\s-]*pointers?\b",
        r"\bthrees\b", r"\b3pt\b", r"\b3s\b",
    ],
    # NFL
    "player_pass_tds": [
        r"\bpassing\s+touchdowns?\b", r"\bpass(?:ing)?\s+tds?\b",
    ],
    "player_pass_yds": [
        r"\bpassing\s+yards?\b", r"\bpass(?:ing)?\s+yds?\b",
    ],
    "player_rush_yds": [
        r"\brushing\s+yards?\b", r"\brush(?:ing)?\s+yds?\b",
    ],
    "player_rush_tds": [
        r"\brushing\s+touchdowns?\b", r"\brush(?:ing)?\s+tds?\b",
    ],
    "player_receptions": [r"\breceptions?\b", r"\bcatches\b", r"\brec\b"],
    "player_reception_yds": [
        r"\breceiving\s+yards?\b", r"\brec(?:eiving)?\s+yds?\b",
    ],
    "player_anytime_td": [
        r"\banytime\s+touchdown\b", r"\bscore\s+a\s+touchdown\b",
        r"\banytime\s+td\b",
    ],
    # MLB
    "batter_total_bases": [r"\btotal\s+bases\b"],
    "batter_home_runs": [r"\bhome\s*runs?\b", r"\bhomers?\b", r"\bhr\b"],
    "batter_rbis": [r"\brbis?\b", r"\bruns?\s+batted\s+in\b"],
    "batter_hits": [r"\bhits?\b"],
    "batter_strikeouts": [r"\bstrikeouts?\b", r"\bk\b"],
    "pitcher_strikeouts": [r"\bstrikeouts?\b", r"\bk\b"],
    "pitcher_outs": [r"\bouts?\s+recorded\b", r"\binnings?\s+pitched\b"],
}

# Sport-specific prop keys — avoids matching NBA keywords in MLB questions
_SPORT_PROP_KEYS: dict[str, set[str]] = {
    "basketball_nba": {
        "player_points", "player_rebounds", "player_assists",
        "player_threes", "player_points_rebounds_assists",
    },
    "americanfootball_nfl": {
        "player_pass_tds", "player_pass_yds", "player_rush_yds",
        "player_rush_tds", "player_receptions", "player_reception_yds",
        "player_anytime_td",
    },
    "baseball_mlb": {
        "batter_hits", "batter_total_bases", "batter_home_runs",
        "batter_rbis", "batter_strikeouts",
        "pitcher_strikeouts", "pitcher_outs",
    },
}


def classify_prop_type(question: str, sport_key: str) -> str | None:
    """
    Classify a prediction market question into an Odds API prop market key.

    Returns the key (e.g., "player_points") or None if unclassifiable.
    Only checks prop types valid for the given sport.
    """
    q = question.lower()
    valid_keys = _SPORT_PROP_KEYS.get(sport_key)
    if not valid_keys:
        return None

    for prop_key, patterns in _PROP_TYPE_PATTERNS.items():
        if prop_key not in valid_keys:
            continue
        for pattern in patterns:
            if re.search(pattern, q):
                return prop_key

    return None


# ---------------------------------------------------------------------------
# Question parsing
# ---------------------------------------------------------------------------

def _parse_prop_question(question: str) -> tuple[str | None, float | None]:
    """
    Extract the line and side from a prop question.

    Returns (side, line) where side is "over" or "under", line is the float
    threshold. Returns (None, None) if either can't be determined.
    """
    q = question.lower()

    # Detect side
    side: str | None = None
    if re.search(r"\bover\b", q):
        side = "over"
    elif re.search(r"\bunder\b", q):
        side = "under"

    # Extract line: look for a number near "over"/"under"
    # Patterns: "over 18.5", "o/u 2.5", "over/under 27.5"
    line: float | None = None
    m = re.search(r"\b(?:over|under|o/u)\s+(\d+(?:\.\d+)?)\b", q)
    if m:
        try:
            line = float(m.group(1))
        except ValueError:
            pass

    # Fallback: any standalone decimal number (e.g., "18.5 points")
    if line is None:
        m = re.search(r"\b(\d+\.\d+)\b", q)
        if m:
            try:
                line = float(m.group(1))
            except ValueError:
                pass

    return side, line


# ---------------------------------------------------------------------------
# Player matching
# ---------------------------------------------------------------------------

def _match_player(
    question_norm: str,
    props: list[PropLine],
    prop_type: str,
    line: float,
) -> PropLine | None:
    """
    Find the unique PropLine matching the question by player name, prop type,
    and exact line.

    Rules:
      - Player name (normalized) must be a substring of the question
      - Prop type must match exactly
      - Line must match exactly (tolerance 0.01 for float precision)
      - Exactly ONE player must match — reject ambiguity

    Returns the matched PropLine or None.
    """
    candidates: list[PropLine] = []
    for pl in props:
        if pl.prop_type != prop_type:
            continue
        if abs(pl.line - line) > 0.01:
            continue
        # Full-name substring match — strict, no last-name fallback
        if pl.player_name_norm in question_norm:
            candidates.append(pl)

    if len(candidates) == 1:
        return candidates[0]

    # Ambiguous (multiple players match) or no match
    return None


# ---------------------------------------------------------------------------
# Feature extraction
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


def extract_prop_features(
    market: NormalizedMarket,
    prop_event: PropEvent,
    cfg: EngineConfig,
) -> list[MarketFeatures]:
    """
    Build MarketFeatures for a player prop market.

    Matching chain:
      1. Classify prop type from question + sport
      2. Parse line and side (over/under) from question
      3. Find matching PropLine (player + type + exact line)
      4. Devig and compute edge

    Returns 0 or 1 MarketFeatures. Strict — rejects on any ambiguity.
    """
    question_norm = normalize_name(market.question)

    # Step 1: Classify prop type
    prop_type = classify_prop_type(market.question, prop_event.sport_key)
    if not prop_type:
        return []

    # Step 2: Parse side and line
    side, pm_line = _parse_prop_question(market.question)
    if side is None or pm_line is None:
        return []

    # Step 3: Find matching PropLine
    matched_prop = _match_player(
        question_norm, prop_event.props, prop_type, pm_line,
    )
    if matched_prop is None:
        return []

    # Step 4: Parse prediction market prices
    if not market.outcome_prices or len(market.outcome_prices) < 2:
        return []
    try:
        pm_yes = float(market.outcome_prices[0])
        pm_no = float(market.outcome_prices[1])
    except (ValueError, TypeError):
        return []
    if not (0.01 <= pm_yes <= 0.99):
        return []

    # The PM YES price corresponds to Over (convention for prop markets).
    # If the question asks about Under, the PM YES price is the Under probability.
    if side == "over":
        pm_price = pm_yes
        fd_odds = matched_prop.over_odds
        fd_odds_other = matched_prop.under_odds
    else:
        pm_price = pm_yes  # YES = Under for under-questions
        fd_odds = matched_prop.under_odds
        fd_odds_other = matched_prop.over_odds

    # Step 5: Devig
    over_impl = _american_to_implied(matched_prop.over_odds)
    under_impl = _american_to_implied(matched_prop.under_odds)
    p_true_over, p_true_under = devig_multiplicative(over_impl, under_impl)
    overround = round(over_impl + under_impl - 1.0, 4)

    if side == "over":
        p_true = p_true_over
        p_true_other = p_true_under
    else:
        p_true = p_true_under
        p_true_other = p_true_over

    pm_price_effective = round(pm_price + _cost_buffer(market.platform, cfg), 4)
    edge = round(p_true - pm_price_effective, 4)
    line_width = round(abs(p_true_over - p_true_under), 4)

    # Step 6: Build MarketFeatures
    event_label = f"{prop_event.home_team} vs {prop_event.away_team}"

    f = MarketFeatures(
        platform=market.platform,
        market_id=market.market_id,
        sport=prop_event.sport_key,
        event_label=event_label,
        event_url=market.url,
        tournament=prop_event.tournament,
        start_time=prop_event.commence_time,
        market_type=prop_type,
        side=f"{matched_prop.player_name} {'Over' if side == 'over' else 'Under'}",
        line=pm_line,
        question=market.question,

        pm_price=pm_price,
        pm_price_no=pm_no if side == "over" else (1.0 - pm_price),
        pm_price_effective=pm_price_effective,
        price_in_range=cfg.min_price < pm_price < cfg.max_price,
        prices_internally_consistent=0.85 <= (pm_yes + pm_no) <= 1.15,
        has_outcome_prices=True,

        # Single-player matching — score 1.0 if found
        home_player=prop_event.home_team,
        away_player=prop_event.away_team,
        home_player_norm=prop_event.home_team_norm,
        away_player_norm=prop_event.away_team_norm,
        name_match_score=1.0,
        matched_players=(matched_prop.player_name_norm,),
        date_score=1.0,  # same event — always 1.0
        event_match_confidence=1.0,
        match_quality="verified",
        matched_event_id=prop_event.event_id,

        # Outcome alignment
        outcome_aligned=True,  # side parsed explicitly
        yes_player=matched_prop.player_name,
        no_player="",

        # FanDuel odds
        fd_odds=fd_odds,
        fd_odds_other=fd_odds_other,
        fd_home_implied=over_impl,
        fd_away_implied=under_impl,
        p_true=p_true,
        p_true_other=p_true_other,

        # FanDuel metrics
        fanduel_overround=overround,
        fanduel_line_width=line_width,
        fanduel_line_width_label=(
            "Tight" if line_width <= 0.10 else
            "Moderate" if line_width <= 0.35 else "Wide"
        ),
        fanduel_confidence_label=(
            "High" if overround <= cfg.overround_high_max else
            "Medium" if overround <= cfg.overround_medium_max else "Low"
        ),

        # Line matching — exact by construction
        line_match_exact=True,
        unit_match=True,
        side_match=True,

        edge=edge,
        has_bookmaker_data=True,
        is_live=_is_live(prop_event.commence_time),

        # Staleness
        price_fetched_at=market.fetched_at,

        # Observability
        home_tokens=tuple(normalize_name(matched_prop.player_name).split()),
        away_tokens=(),
        question_tokens=tuple(sorted(set(re.findall(r"[a-z]+", question_norm)))),
    )

    return [f]
