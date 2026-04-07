"""
Kalshi WebSocket consumer.

Connects to the Kalshi WebSocket for real-time orderbook updates
on watched market tickers.

Endpoint: wss://api.elections.kalshi.com/trade-api/ws/v2
Auth: Requires API key via initial auth message.

Subscribes to orderbook channels for specific market tickers and
triggers re-evaluation when best-ask prices change.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
_RECONNECT_DELAY = 5
_PING_INTERVAL = 30
_MEANINGFUL_PRICE_CHANGE = 0.01


class KalshiWsConsumer:
    """
    WebSocket consumer for Kalshi real-time orderbook updates.

    Authenticates with API key, subscribes to specific market tickers,
    and calls on_price_change when best-ask changes meaningfully.
    """

    def __init__(
        self,
        api_key: str | None = None,
        min_price_change: float = _MEANINGFUL_PRICE_CHANGE,
    ):
        self._api_key = api_key or os.getenv("KALSHI_API_KEY", "")
        self._watched_tickers: set[str] = set()
        self._last_prices: dict[str, float] = {}
        self._min_change = min_price_change
        self._running = False
        self._connected = False
        self._authenticated = False
        self._last_message_ts: float = 0.0
        self._reconnect_count: int = 0

    def watch(self, tickers: set[str]) -> None:
        """Set market tickers to watch."""
        self._watched_tickers = tickers
        logger.info("KalshiWs: watching %d tickers", len(tickers))

    def unwatch_all(self) -> None:
        self._watched_tickers.clear()
        self._last_prices.clear()

    async def run_loop(
        self,
        on_price_change: Callable[[str, float], Awaitable[None]],
    ) -> None:
        """Connect, authenticate, subscribe, and stream price updates."""
        try:
            import websockets
        except ImportError:
            logger.error("KalshiWs: websockets package not installed, skipping")
            return

        if not self._api_key:
            logger.warning("KalshiWs: no KALSHI_API_KEY, skipping")
            return

        self._running = True
        logger.info("KalshiWs: starting consumer loop")

        while self._running:
            try:
                async with websockets.connect(
                    _WS_URL,
                    additional_headers={"Authorization": self._api_key},
                    ping_interval=_PING_INTERVAL,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._connected = True
                    self._reconnect_count = 0
                    logger.info("KalshiWs: connected")

                    # Subscribe to orderbook updates for watched tickers
                    if self._watched_tickers:
                        sub_msg = {
                            "id": 1,
                            "cmd": "subscribe",
                            "params": {
                                "channels": ["orderbook_delta"],
                                "market_tickers": list(self._watched_tickers),
                            },
                        }
                        await ws.send(json.dumps(sub_msg))
                        logger.info("KalshiWs: subscribed to %d tickers", len(self._watched_tickers))

                    async for raw_msg in ws:
                        self._last_message_ts = time.time()
                        try:
                            msg = json.loads(raw_msg)
                            await self._handle_message(msg, on_price_change)
                        except json.JSONDecodeError:
                            continue

            except Exception as exc:
                self._connected = False
                self._authenticated = False
                self._reconnect_count += 1

                # Auth failures won't fix themselves — stop retrying
                exc_str = str(exc)
                if "401" in exc_str or "403" in exc_str:
                    logger.error(
                        "KalshiWs: auth rejected (HTTP %s), stopping reconnect. Check KALSHI_API_KEY.",
                        "401" if "401" in exc_str else "403",
                    )
                    self._running = False
                    return

                # Exponential backoff capped at 60s
                delay = min(_RECONNECT_DELAY * min(self._reconnect_count, 12), 60)
                logger.warning(
                    "KalshiWs: disconnected (%s), reconnecting in %ds (attempt %d)",
                    exc, delay, self._reconnect_count,
                )
                await asyncio.sleep(delay)

    async def _handle_message(
        self,
        msg: dict,
        on_price_change: Callable[[str, float], Awaitable[None]],
    ) -> None:
        """Process a WebSocket message."""
        msg_type = msg.get("type", "")

        if msg_type == "orderbook_snapshot" or msg_type == "orderbook_delta":
            ticker = msg.get("msg", {}).get("market_ticker", "")
            if ticker not in self._watched_tickers:
                return

            # Extract best yes_ask from orderbook
            orderbook = msg.get("msg", {})
            yes_asks = orderbook.get("yes", [])
            if yes_asks and isinstance(yes_asks, list):
                # Kalshi orderbook: list of [price_cents, quantity]
                # Best ask = lowest price
                try:
                    best_ask_cents = min(
                        entry[0] for entry in yes_asks
                        if isinstance(entry, list) and len(entry) >= 2 and entry[1] > 0
                    )
                    price = best_ask_cents / 100.0
                except (ValueError, TypeError, IndexError):
                    return

                prev = self._last_prices.get(ticker)
                if prev is None or abs(price - prev) >= self._min_change:
                    self._last_prices[ticker] = price
                    await on_price_change(ticker, price)

    def stop(self) -> None:
        self._running = False

    def status(self) -> dict:
        return {
            "connected": self._connected,
            "running": self._running,
            "watched_count": len(self._watched_tickers),
            "last_message_ts": self._last_message_ts,
            "reconnect_count": self._reconnect_count,
            "has_api_key": bool(self._api_key),
        }
