"""
Price history fetcher for prediction market platforms.

Polymarket: CLOB API /prices-history (requires clobTokenId from Gamma API)
Kalshi: /trade-api/v2/series/{series}/markets/{ticker}/candlesticks
"""
import json as _json
import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_GAMMA_BASE = os.getenv("GAMMA_API_BASE", "https://gamma-api.polymarket.com")
_CLOB_BASE = "https://clob.polymarket.com"
_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass
class PricePoint:
    timestamp: int    # unix seconds
    price: float      # 0–1


async def fetch_polymarket_history(
    market_id: str,
    interval: str = "1w",
    fidelity: int = 60,
) -> list[PricePoint]:
    """
    Fetch price history for a Polymarket market.

    Steps:
      1. GET gamma-api/markets/{market_id} to find clobTokenIds
      2. GET clob.polymarket.com/prices-history?market={token_id}
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Step 1: get CLOB token ID
        resp = await client.get(f"{_GAMMA_BASE}/markets/{market_id}")
        resp.raise_for_status()
        market_data = resp.json()

        clob_ids = market_data.get("clobTokenIds")
        if isinstance(clob_ids, str):
            try:
                clob_ids = _json.loads(clob_ids)
            except (ValueError, TypeError):
                clob_ids = None
        if not clob_ids or not isinstance(clob_ids, list) or len(clob_ids) == 0:
            logger.warning("No clobTokenIds for PM market %s", market_id)
            return []

        token_id = clob_ids[0]  # Yes outcome token

        # Step 2: fetch price history
        resp = await client.get(
            f"{_CLOB_BASE}/prices-history",
            params={
                "market": token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        history = data.get("history", [])
        return [
            PricePoint(timestamp=int(pt["t"]), price=float(pt["p"]))
            for pt in history
            if "t" in pt and "p" in pt
        ]


async def fetch_kalshi_history(
    market_ticker: str,
    period_interval: int = 60,
    days_back: int = 7,
) -> list[PricePoint]:
    """
    Fetch candlestick price history for a Kalshi market.

    Uses the close price from each candlestick period.
    """
    api_key = os.getenv("KALSHI_API_KEY", "")
    if not api_key:
        return []

    # Extract series ticker (first segment before the event-specific parts)
    # KXATPMATCH-26APR07GARZVE-ZVE -> KXATPMATCH
    parts = market_ticker.split("-")
    series_ticker = parts[0] if parts else market_ticker

    now = int(time.time())
    start_ts = now - (days_back * 86400)

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_KALSHI_BASE}/series/{series_ticker}/markets/{market_ticker}/candlesticks",
            params={
                "start_ts": start_ts,
                "end_ts": now,
                "period_interval": period_interval,
            },
            headers={"Authorization": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

        points: list[PricePoint] = []
        for candle in data.get("candlesticks", []):
            ts = candle.get("end_period_ts")
            price_data = candle.get("price", {})
            close = price_data.get("close_dollars")
            if ts and close:
                try:
                    points.append(PricePoint(
                        timestamp=int(ts),
                        price=float(close),
                    ))
                except (ValueError, TypeError):
                    pass

        return points


async def fetch_price_history(
    platform: str,
    market_id: str,
) -> list[PricePoint]:
    """Dispatch to the correct platform fetcher."""
    try:
        if platform == "polymarket":
            return await fetch_polymarket_history(market_id)
        elif platform == "kalshi":
            return await fetch_kalshi_history(market_id)
        else:
            logger.warning("Unknown platform for price history: %s", platform)
            return []
    except Exception as exc:
        logger.error("Price history fetch failed (%s/%s): %s", platform, market_id, exc)
        return []
