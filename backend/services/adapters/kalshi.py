"""
Kalshi adapter — fetches active tennis match markets from the Kalshi API
and normalizes them into NormalizedMarket objects.

Kalshi H2H events have TWO markets per match — one per player.  Buying
"Yes Player A" is equivalent to buying "No Player B", but the prices can
differ because different traders participate in each market.  This adapter
groups the pair, finds the best (cheapest) price to bet on each player
across both markets, and emits ONE NormalizedMarket per event.

Only H2H match-winner markets (KXATPMATCH, KXWTAMATCH) are fetched.

API: https://api.elections.kalshi.com/trade-api/v2
Auth: API key via Authorization header.
"""
import logging
import os
from collections import defaultdict

import httpx

from services.adapters.base import NormalizedMarket

logger = logging.getLogger(__name__)

from services.sports_config import all_kalshi_series

_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiAdapter:
    platform_name: str = "kalshi"

    def __init__(self, api_key: str | None = None):
        self._explicit_key = api_key

    @property
    def _api_key(self) -> str:
        return self._explicit_key or os.getenv("KALSHI_API_KEY", "")

    async def fetch_markets(self) -> list[NormalizedMarket]:
        """
        Fetch active H2H tennis match markets from Kalshi.

        Groups paired markets by event, picks the best price for each
        player, and emits one NormalizedMarket per event.
        """
        if not self._api_key:
            logger.debug("KalshiAdapter: no KALSHI_API_KEY, skipping")
            return []

        headers = {"Authorization": self._api_key}
        all_raw: list[tuple[dict, str, str]] = []  # (market_dict, series, slug)
        match_series = all_kalshi_series()

        async with httpx.AsyncClient(timeout=12.0) as client:
            for series_ticker, series_slug in match_series.items():
                try:
                    resp = await client.get(
                        f"{_BASE}/markets",
                        params={
                            "series_ticker": series_ticker,
                            "status": "open",
                            "limit": 200,
                        },
                        headers=headers,
                    )
                    resp.raise_for_status()
                    for m in resp.json().get("markets", []):
                        all_raw.append((m, series_ticker, series_slug))
                except httpx.HTTPStatusError as exc:
                    logger.error("Kalshi API error %s: %s", series_ticker, exc.response.status_code)
                except Exception as exc:
                    logger.error("Kalshi fetch error %s: %s", series_ticker, exc)

        # Group by event_ticker (each event has 2 markets — one per player)
        events: dict[str, list[tuple[dict, str, str]]] = defaultdict(list)
        for m, series, slug in all_raw:
            et = m.get("event_ticker", "")
            if et:
                events[et].append((m, series, slug))

        normalized: list[NormalizedMarket] = []
        for event_ticker, market_group in events.items():
            nm = _build_event_market(event_ticker, market_group)
            if nm:
                normalized.append(nm)

        logger.info(
            "KalshiAdapter: %d raw markets, %d events, %d normalized",
            len(all_raw), len(events), len(normalized),
        )
        return normalized


def _safe_float(val: object) -> float:
    try:
        return float(val or 0)
    except (ValueError, TypeError):
        return 0.0


def _build_event_market(
    event_ticker: str,
    market_group: list[tuple[dict, str, str]],
) -> NormalizedMarket | None:
    """
    Build one NormalizedMarket from a paired Kalshi event.

    For a match "A vs B", Kalshi has:
      Market 1: "Will A win?"  yes_ask / no_ask
      Market 2: "Will B win?"  yes_ask / no_ask

    Buying Yes-A = buying No-B (same outcome, possibly different price).
    We pick the cheapest route for each player:
      best_price_A = min(M1.yes_ask, M2.no_ask)
      best_price_B = min(M2.yes_ask, M1.no_ask)

    Emits a single NormalizedMarket with outcome_prices = [best_A, best_B]
    where A is the player whose name appears first in the event title.
    """
    if len(market_group) < 2:
        # Single market — can't pair. Use it directly.
        m, series, slug = market_group[0]
        return _single_market_fallback(m, series, slug)

    # Parse both markets
    parsed = []
    for m, series, slug in market_group:
        yes_ask = _safe_float(m.get("yes_ask_dollars"))
        no_ask = _safe_float(m.get("no_ask_dollars"))
        yes_bid = _safe_float(m.get("yes_bid_dollars"))
        no_bid = _safe_float(m.get("no_bid_dollars"))
        if yes_ask <= 0 or yes_ask >= 1:
            continue
        parsed.append({
            "ticker": m.get("ticker", ""),
            "title": m.get("title", ""),
            "yes_ask": yes_ask,
            "no_ask": no_ask if no_ask > 0 else 1.0 - yes_ask,
            "yes_bid": yes_bid,
            "no_bid": no_bid,
            "volume": _safe_float(m.get("volume_fp")),
            "liquidity": _safe_float(m.get("liquidity_dollars")),
            "close_time": m.get("close_time") or m.get("expiration_time"),
            "series": series,
            "slug": slug,
        })

    if len(parsed) < 2:
        if parsed:
            m, series, slug = market_group[0]
            return _single_market_fallback(m, series, slug)
        return None

    m1, m2 = parsed[0], parsed[1]

    # Best price to buy the player in M1 (yes on M1, or no on M2)
    best_m1_player = min(m1["yes_ask"], m2["no_ask"])
    # Best price to buy the player in M2 (yes on M2, or no on M1)
    best_m2_player = min(m2["yes_ask"], m1["no_ask"])

    # Validate prices
    if best_m1_player <= 0.02 or best_m1_player >= 0.98:
        return None
    if best_m2_player <= 0.02 or best_m2_player >= 0.98:
        return None

    # Build question from M1's title (contains both players via match name)
    # The event title from Kalshi is like "Rublev vs Bergs"
    # M1's title is "Will Andrey Rublev win the Rublev vs Bergs : Round Of 32 match?"
    question = m1["title"]

    # outcome_prices: [price_for_yes_player, price_for_no_player]
    # yes player = the player in M1's question (first name found)
    outcome_prices = [
        str(round(best_m1_player, 4)),
        str(round(best_m2_player, 4)),
    ]

    # Use the ticker of the market with more volume for URL / history
    primary = m1 if m1["volume"] >= m2["volume"] else m2
    series = primary["series"]
    slug_name = primary["slug"]
    url = f"https://kalshi.com/markets/{series.lower()}/{slug_name}/{event_ticker.lower()}"

    total_liq = m1["liquidity"] + m2["liquidity"]
    total_vol = m1["volume"] + m2["volume"]

    return NormalizedMarket(
        platform="kalshi",
        market_id=m1["ticker"],  # use M1 ticker for price history
        event=question,
        market_type="h2h",
        side="",
        line=None,
        price=best_m1_player,
        liquidity=total_liq if total_liq > 0 else total_vol,
        url=url,
        timestamp=m1["close_time"],
        question=question,
        end_date=m1["close_time"],
        outcome_prices=outcome_prices,
        event_slug=event_ticker,
    )


def _single_market_fallback(
    m: dict,
    series_ticker: str,
    series_slug: str,
) -> NormalizedMarket | None:
    """Fallback for unpaired markets — use yes_ask directly."""
    yes_ask = _safe_float(m.get("yes_ask_dollars"))
    if yes_ask <= 0.02 or yes_ask >= 0.98:
        return None

    ticker = m.get("ticker", "")
    event_ticker = m.get("event_ticker", "")
    no_price = round(1.0 - yes_ask, 4)

    return NormalizedMarket(
        platform="kalshi",
        market_id=ticker,
        event=m.get("title", ""),
        market_type="h2h",
        side="",
        line=None,
        price=round(yes_ask, 4),
        liquidity=_safe_float(m.get("liquidity_dollars")) or _safe_float(m.get("volume_fp")),
        url=f"https://kalshi.com/markets/{series_ticker.lower()}/{series_slug}/{event_ticker.lower()}",
        timestamp=m.get("close_time") or m.get("expiration_time"),
        question=m.get("title", ""),
        end_date=m.get("close_time") or m.get("expiration_time"),
        outcome_prices=[str(round(yes_ask, 4)), str(no_price)],
        event_slug=event_ticker,
    )
