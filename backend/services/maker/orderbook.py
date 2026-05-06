"""
Kalshi orderbook model, parser, and read-only fetcher.

Kalshi binary markets expose resting BIDS on each side:
  - yes bids: traders willing to buy YES at price p
  - no  bids: traders willing to buy NO  at price p

The best YES ask is the implied complement of the highest NO bid:

    best_yes_ask = 1.00 - best_no_bid

because filling a NO bid at 0.43 is economically equivalent to selling
YES at 0.57.  The lowest YES bid is *not* the YES ask — that is the bug
fixed in commit 88e2d126 for the WS handler.

This module is read-only and never places orders.  The fetcher is not
called from any production pipeline yet — it exists so the maker planner
can be supplied real depth in a future integration commit.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.elections.kalshi.com/trade-api/v2"
_DEFAULT_TIMEOUT = 8.0

Side = Literal["yes_bid", "no_bid", "yes_ask"]


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BookLevel:
    """One price level on a side of the book."""
    price: float       # dollars (0.0–1.0), on tick
    quantity: int      # contracts


@dataclass(frozen=True)
class OrderBook:
    """
    Snapshot of one Kalshi market's orderbook at a point in time.

    yes_bids and no_bids are the two sides Kalshi publishes (resting bids).
    yes_asks is synthesized from no_bids — the cheapest YES purchase
    mirrors the most aggressive NO bid.
    """
    market_id: str
    yes_bids: tuple[BookLevel, ...]      # sorted DESCENDING by price (best first)
    no_bids: tuple[BookLevel, ...]       # sorted DESCENDING by price (best first)
    yes_asks: tuple[BookLevel, ...]      # synthesized; sorted ASCENDING by price (best first)
    fetched_at: float
    source: str = "rest"

    # --- Best-of-book ---

    def best_yes_bid(self) -> float | None:
        return self.yes_bids[0].price if self.yes_bids else None

    def best_yes_ask(self) -> float | None:
        return self.yes_asks[0].price if self.yes_asks else None

    def best_no_bid(self) -> float | None:
        return self.no_bids[0].price if self.no_bids else None

    # --- Spread + sanity ---

    def spread(self) -> float | None:
        """Best-ask minus best-bid in dollars; None when either side is empty."""
        bid = self.best_yes_bid()
        ask = self.best_yes_ask()
        if bid is None or ask is None:
            return None
        return round(ask - bid, 4)

    def is_crossed(self) -> bool:
        """True when best_yes_bid >= best_yes_ask (locked or crossed market)."""
        bid = self.best_yes_bid()
        ask = self.best_yes_ask()
        if bid is None or ask is None:
            return False
        return bid >= ask

    # --- Level lookups ---

    def queue_qty_at(self, side: Side, price: float) -> int:
        """Resting quantity at exactly `price` on `side`.  Returns 0 if no level there."""
        for lv in self._levels_for(side):
            if abs(lv.price - price) < 1e-6:
                return lv.quantity
        return 0

    def depth_at_or_better(self, side: Side, price: float) -> int:
        """
        Cumulative quantity at or better than `price` on `side`.

        For bid sides ("yes_bid", "no_bid"), "better" means HIGHER price.
        For the synthesized ask side ("yes_ask"), "better" means LOWER price.

        For a maker placing a new bid at `price`, this is the queue ahead
        of the new order: the contracts that fill before us when matched.
        """
        levels = self._levels_for(side)
        if side in ("yes_bid", "no_bid"):
            return sum(lv.quantity for lv in levels if lv.price + 1e-9 >= price)
        # yes_ask: better = cheaper
        return sum(lv.quantity for lv in levels if lv.price - 1e-9 <= price)

    def _levels_for(self, side: Side) -> tuple[BookLevel, ...]:
        if side == "yes_bid":
            return self.yes_bids
        if side == "no_bid":
            return self.no_bids
        if side == "yes_ask":
            return self.yes_asks
        raise ValueError(f"Unknown side: {side!r}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_TICK_TOLERANCE = 1e-6


def _parse_price_to_cents(raw: object) -> int | None:
    """
    Parse a price from a Kalshi orderbook level into integer cents (1–99).

    Kalshi exposes two equivalent shapes for the same on-tick price:

      * WebSocket / older REST: integer cents
            5  → 5 cents (0.05)
            "5"  → 5 cents (0.05)

      * REST `/markets/{ticker}/orderbook`: decimal-dollar strings
            "0.0500" → 5 cents (0.05)
            "0.4300" → 43 cents (0.43)

    Floats are also accepted (some serializers emit 0.05 instead of "0.0500").

    Returns the canonical integer cents in [1, 99] for valid on-tick prices,
    or `None` for any malformed, off-tick, or out-of-range input.  `bool`
    is explicitly rejected because it is an `int` subclass (`True == 1`).
    """
    if isinstance(raw, bool):
        return None

    if isinstance(raw, int):
        # Pure int → always integer cents.
        cents = raw

    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if "." in s:
            # Decimal-dollar string ("0.0500"): convert to cents and require
            # the result to be on a 1¢ tick.
            try:
                dollars = float(s)
            except ValueError:
                return None
            cents_f = dollars * 100
            cents = round(cents_f)
            if abs(cents_f - cents) > _TICK_TOLERANCE:
                return None
        else:
            # Integer-cents string ("5"): direct int parse.
            try:
                cents = int(s)
            except ValueError:
                return None

    elif isinstance(raw, float):
        # Heuristic: floats in (0, 1) are decimal dollars; everything else
        # is treated as a whole-number cent value (and must round cleanly).
        if 0.0 < raw < 1.0:
            cents_f = raw * 100
            cents = round(cents_f)
            if abs(cents_f - cents) > _TICK_TOLERANCE:
                return None
        else:
            cents = round(raw)
            if abs(raw - cents) > _TICK_TOLERANCE:
                return None

    else:
        return None

    if not (1 <= cents <= 99):
        return None
    return cents


def _parse_quantity(raw: object) -> int | None:
    """
    Parse a contract quantity from a Kalshi orderbook level.

    Accepts integers, integer strings (`"10"`), whole-number decimal
    strings (`"300935.00"`) — Kalshi REST emits this form — and
    whole-number floats.  Rejects zero, negatives, non-whole-numbers, and
    non-numeric input.  `bool` is explicitly rejected.
    """
    if isinstance(raw, bool):
        return None

    if isinstance(raw, int):
        return raw if raw > 0 else None

    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            f = float(s)
        except ValueError:
            return None
        n = round(f)
        if abs(f - n) > _TICK_TOLERANCE:
            return None
        return n if n > 0 else None

    if isinstance(raw, float):
        n = round(raw)
        if abs(raw - n) > _TICK_TOLERANCE:
            return None
        return n if n > 0 else None

    return None


def _parse_levels_from_array(
    arr: object,
    descending: bool,
) -> tuple[BookLevel, ...]:
    """
    Convert Kalshi's `[[price, qty], ...]` shape to a sorted tuple of
    `BookLevel`.  Both integer-cents and decimal-dollar shapes are
    accepted (see `_parse_price_to_cents`).  Drops zero/negative qty,
    off-tick prices, prices outside (1, 99) cents, and malformed entries.
    Same-price duplicates are summed.
    """
    if not isinstance(arr, list):
        return ()
    by_price: dict[int, int] = {}
    for entry in arr:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        cents = _parse_price_to_cents(entry[0])
        if cents is None:
            continue
        qty = _parse_quantity(entry[1])
        if qty is None:
            continue
        by_price[cents] = by_price.get(cents, 0) + qty
    out = [BookLevel(price=p / 100.0, quantity=q) for p, q in by_price.items()]
    out.sort(key=lambda lv: lv.price, reverse=descending)
    return tuple(out)


def _synthesize_yes_asks(no_bids: tuple[BookLevel, ...]) -> tuple[BookLevel, ...]:
    """Synthesize YES ask levels from NO bids.

        YES ask price = 1.0 - NO bid price
        YES ask qty   = NO bid qty

    Sorted ascending so `[0]` is the cheapest YES purchase.
    """
    asks = [
        BookLevel(price=round(1.0 - lv.price, 4), quantity=lv.quantity)
        for lv in no_bids
    ]
    asks.sort(key=lambda lv: lv.price)
    return tuple(asks)


def parse_kalshi_orderbook(
    market_id: str,
    payload: object,
    fetched_at: float | None = None,
    source: str = "rest",
) -> OrderBook | None:
    """
    Parse a Kalshi orderbook JSON payload into an `OrderBook`.

    Accepts both the wrapped shape (`{"orderbook": {"yes": [...], "no": [...]}}`)
    and a bare shape (`{"yes": [...], "no": [...]}`).  Returns None for
    payloads that aren't a dict; never raises.

    Empty `yes`/`no` arrays are valid and produce an `OrderBook` with empty
    side tuples — best_yes_bid / best_yes_ask are then None.
    """
    if fetched_at is None:
        fetched_at = time.time()
    if not isinstance(payload, dict):
        return None

    inner = payload.get("orderbook") if isinstance(payload.get("orderbook"), dict) else payload
    if not isinstance(inner, dict):
        return None

    yes_bids = _parse_levels_from_array(inner.get("yes"), descending=True)
    no_bids = _parse_levels_from_array(inner.get("no"), descending=True)
    yes_asks = _synthesize_yes_asks(no_bids)

    return OrderBook(
        market_id=market_id,
        yes_bids=yes_bids,
        no_bids=no_bids,
        yes_asks=yes_asks,
        fetched_at=fetched_at,
        source=source,
    )


# ---------------------------------------------------------------------------
# REST fetcher
# ---------------------------------------------------------------------------

async def fetch_kalshi_orderbook(
    ticker: str,
    *,
    api_key: str | None = None,
    depth: int | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> OrderBook | None:
    """
    Fetch a single Kalshi market's orderbook over REST.

    Returns the parsed `OrderBook` on success, or `None` on any failure
    (missing API key, HTTP error, network error, malformed JSON, parser
    failure).  Never raises — failures are logged and converted to None
    so callers don't need try/except.

    Read-only: makes one GET request and returns the parsed snapshot.
    No orders, no caching, no production pipeline integration in v1.

    When `client` is provided, the caller owns its lifecycle.  When omitted,
    a short-lived client is created and closed within this call.
    """
    key = api_key or os.getenv("KALSHI_API_KEY", "")
    if not key:
        logger.debug("fetch_kalshi_orderbook: no KALSHI_API_KEY, skipping")
        return None

    url = f"{_BASE}/markets/{ticker}/orderbook"
    headers = {"Authorization": key}
    params: dict = {}
    if depth is not None:
        params["depth"] = depth

    own_client = client is None
    try:
        if own_client:
            client = httpx.AsyncClient(timeout=timeout)
        try:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            payload = resp.json()
        finally:
            if own_client:
                await client.aclose()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Kalshi orderbook %s: HTTP %s",
            ticker, exc.response.status_code,
        )
        return None
    except httpx.HTTPError as exc:
        logger.warning("Kalshi orderbook %s: network error %s", ticker, exc)
        return None
    except (ValueError, TypeError) as exc:
        # json.JSONDecodeError is a ValueError; defensive on TypeError too
        logger.warning("Kalshi orderbook %s: malformed JSON: %s", ticker, exc)
        return None

    return parse_kalshi_orderbook(ticker, payload)
