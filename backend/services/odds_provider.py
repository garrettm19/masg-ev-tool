"""
The Odds API client for tennis H2H markets.

Fetches upcoming tennis events, normalises player names, start times,
bookmaker keys, and American-format moneyline odds so the data is ready
for matching against Polymarket tennis events.

Requires env var: ODDS_API_KEY

Read-only.  No orders, no automation.
"""
import logging
import os
import unicodedata
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"
_ODDS_FORMAT = "american"   # keeps consistent with the pricing engine


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BookmakerLine:
    """Moneyline H2H odds from one bookmaker for one match."""
    bookmaker_key: str       # e.g. "draftkings"
    bookmaker_title: str     # e.g. "DraftKings"
    home_odds: int           # American odds for home player winning
    away_odds: int           # American odds for away player winning
    last_update: str         # ISO-8601 UTC timestamp from API


@dataclass
class TennisOddsEvent:
    """
    Normalised tennis match ready for Polymarket matching.

    *_norm fields are lowercase ASCII — use these for fuzzy name matching.
    consensus_* fields are the average across all bookmakers (implied prob
    space), converted back to American.  None when no bookmakers returned.
    """
    event_id: str
    sport_key: str           # e.g. "tennis_atp_french_open"
    tournament: str          # e.g. "ATP French Open"
    home_player: str         # original capitalisation from API
    away_player: str
    home_player_norm: str    # lowercase ASCII for matching
    away_player_norm: str
    commence_time: str       # ISO-8601 UTC
    bookmakers: list[BookmakerLine] = field(default_factory=list)
    consensus_home_odds: int | None = None
    consensus_away_odds: int | None = None
    # Implied probabilities derived from consensus line (include vig)
    home_implied: float | None = None
    away_implied: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_player_name(name: str) -> str:
    """
    Lowercase, strip diacritics, collapse whitespace.
    e.g. "Carlos Alcaraz" → "carlos alcaraz"
         "Iga Świątek"    → "iga swiatek"
    """
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_bytes = nfkd.encode("ascii", errors="ignore")
    return " ".join(ascii_bytes.decode().lower().split())


def _american_to_implied(odds: int) -> float:
    """American moneyline → implied probability (includes vig)."""
    if odds >= 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _implied_to_american(p: float) -> int:
    """Implied probability → nearest American moneyline integer."""
    p = max(0.01, min(0.99, p))
    if p >= 0.5:
        return -round(p / (1.0 - p) * 100)
    return round((1.0 - p) / p * 100)


def _consensus_line(
    lines: list[BookmakerLine],
) -> tuple[int | None, int | None, float | None, float | None]:
    """
    Average implied probabilities across all bookmaker lines and convert back
    to American odds.  Returns (home_odds, away_odds, home_impl, away_impl).
    """
    if not lines:
        return None, None, None, None
    home_impls = [_american_to_implied(ln.home_odds) for ln in lines]
    away_impls = [_american_to_implied(ln.away_odds) for ln in lines]
    n = len(lines)
    avg_home = sum(home_impls) / n
    avg_away = sum(away_impls) / n
    return (
        _implied_to_american(avg_home),
        _implied_to_american(avg_away),
        round(avg_home, 4),
        round(avg_away, 4),
    )


def _extract_bookmaker_line(
    bookmaker: dict,
    home_player: str,
    away_player: str,
) -> BookmakerLine | None:
    """
    Pull the H2H market from one bookmaker block and map to BookmakerLine.
    Returns None if H2H odds aren't present or player names don't match.
    """
    for market in bookmaker.get("markets") or []:
        if market.get("key") != "h2h":
            continue
        outcomes: dict[str, int] = {
            o["name"]: int(o["price"])
            for o in market.get("outcomes") or []
            if "name" in o and "price" in o
        }
        if home_player not in outcomes or away_player not in outcomes:
            continue
        return BookmakerLine(
            bookmaker_key=bookmaker.get("key", "unknown"),
            bookmaker_title=bookmaker.get("title", bookmaker.get("key", "unknown")),
            home_odds=outcomes[home_player],
            away_odds=outcomes[away_player],
            last_update=market.get("last_update") or bookmaker.get("last_update") or "",
        )
    return None


def _normalize_event(raw: dict) -> TennisOddsEvent | None:
    """
    Parse one raw API event dict into a TennisOddsEvent.
    Returns None if required fields are missing.
    """
    event_id = raw.get("id")
    home = raw.get("home_team")
    away = raw.get("away_team")
    sport_key = raw.get("sport_key", "")
    tournament = raw.get("sport_title", sport_key)
    commence_time = raw.get("commence_time", "")

    if not (event_id and home and away):
        return None

    lines: list[BookmakerLine] = []
    for bm in raw.get("bookmakers") or []:
        line = _extract_bookmaker_line(bm, home, away)
        if line:
            lines.append(line)

    c_home, c_away, h_impl, a_impl = _consensus_line(lines)

    return TennisOddsEvent(
        event_id=event_id,
        sport_key=sport_key,
        tournament=tournament,
        home_player=home,
        away_player=away,
        home_player_norm=normalize_player_name(home),
        away_player_norm=normalize_player_name(away),
        commence_time=commence_time,
        bookmakers=lines,
        consensus_home_odds=c_home,
        consensus_away_odds=c_away,
        home_implied=h_impl,
        away_implied=a_impl,
    )


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

async def _fetch_active_tennis_sports(api_key: str) -> list[str]:
    """
    Return sport keys for all active, non-outright tennis sports.
    Calls GET /v4/sports/?apiKey=...
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_BASE}/sports/", params={"apiKey": api_key})
        resp.raise_for_status()
        sports: list[dict] = resp.json()

    keys = [
        s["key"]
        for s in sports
        if isinstance(s, dict)
        and s.get("active")
        and not s.get("has_outrights", False)
        and "tennis" in s.get("group", "").lower()
    ]
    logger.info(f"Active tennis sport keys: {keys}")
    return keys


async def _fetch_sport_odds(
    sport_key: str,
    api_key: str,
    client: httpx.AsyncClient,
    bookmaker: str = "fanduel",
) -> tuple[list[dict], dict]:
    """
    Fetch H2H odds for one sport from a single bookmaker (FanDuel).

    One API call per sport. No secondary bookmakers, no spreads/totals.
    """
    resp = await client.get(
        f"{_BASE}/sports/{sport_key}/odds/",
        params={
            "apiKey": api_key,
            "bookmakers": bookmaker,
            "markets": "h2h",
            "oddsFormat": _ODDS_FORMAT,
        },
    )
    resp.raise_for_status()
    quota = {
        "remaining": resp.headers.get("x-requests-remaining"),
        "used": resp.headers.get("x-requests-used"),
    }
    return resp.json(), quota


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def fetch_tennis_odds(
    max_sports: int = 10,
    bookmaker: str = "fanduel",
) -> tuple[list[TennisOddsEvent], dict]:
    """
    Fetch and normalise upcoming tennis H2H odds from The Odds API.

    Steps:
      1. Discover active tennis sport keys.
      2. Fetch H2H odds for up to max_sports of them.
      3. Normalise each event: player names, start time, per-book lines,
         consensus odds, implied probabilities.

    Returns:
      (events, meta) where meta carries quota info and which sports were
      fetched — useful for the API response and for debugging.

    Raises:
      ValueError  – if ODDS_API_KEY env var is not set.
      httpx.HTTPStatusError – on API errors.
    """
    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        raise ValueError("ODDS_API_KEY environment variable is not set")

    sport_keys = await _fetch_active_tennis_sports(api_key)
    sport_keys = sport_keys[:max_sports]

    if not sport_keys:
        logger.warning("No active tennis sport keys returned from The Odds API")
        return [], {"sports_fetched": [], "quota_remaining": None, "quota_used": None}

    events: list[TennisOddsEvent] = []
    last_quota: dict = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for key in sport_keys:
            try:
                raw_events, quota = await _fetch_sport_odds(key, api_key, client, bookmaker=bookmaker)
                last_quota = quota
                for raw in raw_events:
                    event = _normalize_event(raw)
                    if event:
                        events.append(event)
                logger.info(
                    f"[{key}] fetched {len(raw_events)} events · "
                    f"quota remaining: {quota.get('remaining')}"
                )
            except httpx.HTTPStatusError as exc:
                logger.error(f"Odds API error for {key}: {exc.response.status_code}")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Unexpected error fetching odds for {key}: {exc}")

    meta = {
        "sports_fetched": sport_keys,
        "quota_remaining": last_quota.get("remaining"),
        "quota_used": last_quota.get("used"),
        "total_events": len(events),
    }
    return events, meta


# ---------------------------------------------------------------------------
# Multi-sport entry point
# ---------------------------------------------------------------------------

async def _resolve_all_sport_keys(api_key: str) -> list[str]:
    """
    Resolve all sport keys from sports config.

    - Sports with explicit `odds_api_keys` are returned directly.
    - Sports with `odds_api_group` (e.g., Tennis) are discovered
      dynamically from the /v4/sports/ endpoint.
    """
    from services.sports_config import SPORTS

    explicit_keys: list[str] = []
    groups_needed: set[str] = set()

    for sc in SPORTS.values():
        explicit_keys.extend(sc.odds_api_keys)
        if sc.odds_api_group:
            groups_needed.add(sc.odds_api_group.lower())

    # Discover group-based keys if needed
    discovered: list[str] = []
    if groups_needed:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{_BASE}/sports/", params={"apiKey": api_key})
            resp.raise_for_status()
            for s in resp.json():
                if (
                    isinstance(s, dict)
                    and s.get("active")
                    and not s.get("has_outrights", False)
                    and s.get("group", "").lower() in groups_needed
                ):
                    discovered.append(s["key"])

    all_keys = list(dict.fromkeys(explicit_keys + discovered))  # dedupe, preserve order
    logger.info("Resolved %d sport keys: %s", len(all_keys), all_keys)
    return all_keys


async def fetch_odds(
    bookmaker: str = "fanduel",
    max_sports: int = 25,
) -> tuple[list[TennisOddsEvent], dict]:
    """
    Fetch odds for ALL configured sports (not just tennis).

    Same return shape as fetch_tennis_odds for compatibility.
    """
    api_key = os.getenv("ODDS_API_KEY", "")
    if not api_key:
        raise ValueError("ODDS_API_KEY environment variable is not set")

    sport_keys = await _resolve_all_sport_keys(api_key)
    sport_keys = sport_keys[:max_sports]

    if not sport_keys:
        logger.warning("No active sport keys resolved")
        return [], {"sports_fetched": [], "quota_remaining": None, "quota_used": None}

    events: list[TennisOddsEvent] = []
    last_quota: dict = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for key in sport_keys:
            try:
                raw_events, quota = await _fetch_sport_odds(key, api_key, client, bookmaker=bookmaker)
                last_quota = quota
                for raw in raw_events:
                    event = _normalize_event(raw)
                    if event:
                        events.append(event)
                logger.info(
                    "[%s] fetched %d events, quota remaining: %s",
                    key, len(raw_events), quota.get("remaining"),
                )
            except httpx.HTTPStatusError as exc:
                logger.error("Odds API error for %s: %s", key, exc.response.status_code)
            except Exception as exc:
                logger.error("Unexpected error fetching odds for %s: %s", key, exc)

    meta = {
        "sports_fetched": sport_keys,
        "quota_remaining": last_quota.get("remaining"),
        "quota_used": last_quota.get("used"),
        "total_events": len(events),
    }
    return events, meta


# Alias for backward compatibility
OddsEvent = TennisOddsEvent
