"""
Polymarket CLOB order-book client (read-only).

Gamma's outcomePrices is last-trade metadata and not safe for live EV
calculations.  This module fetches the actual order book from
clob.polymarket.com for a given asset (token) ID, so the scanner can
price opportunities against a real best ask instead of stale metadata.

`fetch_books` is bounded both by an `asyncio.Semaphore` and by the underlying
`httpx` connection pool so that scans involving thousands of token IDs do
not overwhelm the CLOB edge — unbounded fan-out was observed to cause silent
request failures under uvicorn.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

CLOB_BASE = "https://clob.polymarket.com"

# Cap concurrent in-flight CLOB requests.  Matches httpx pool max_connections
# below so the semaphore and pool agree.
DEFAULT_CONCURRENCY = 50


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: list[BookLevel]   # sorted descending by price (best bid first)
    asks: list[BookLevel]   # sorted ascending by price (best ask first)


def _coerce_float(v: object) -> float | None:
    """Accept int, float, or numeric string. Return None on anything else."""
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_levels(raw: object) -> list[BookLevel] | None:
    """
    Parse a list of {"price","size"} dicts.

    Returns None if `raw` is not a list (i.e. malformed or missing).
    Returns an empty list when `raw` is an empty list.
    Skips individual entries that fail to parse.
    """
    if not isinstance(raw, list):
        return None
    out: list[BookLevel] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        price = _coerce_float(entry.get("price"))
        size = _coerce_float(entry.get("size"))
        if price is None or size is None:
            continue
        out.append(BookLevel(price=price, size=size))
    return out


def _build_book(token_id: str, payload: object) -> OrderBook | None:
    """Build an OrderBook from a parsed CLOB /book JSON payload."""
    if not isinstance(payload, dict):
        return None
    bids = _parse_levels(payload.get("bids"))
    asks = _parse_levels(payload.get("asks"))
    if bids is None or asks is None:
        return None
    bids_sorted = sorted(bids, key=lambda lvl: lvl.price, reverse=True)
    asks_sorted = sorted(asks, key=lambda lvl: lvl.price)
    return OrderBook(token_id=token_id, bids=bids_sorted, asks=asks_sorted)


async def fetch_book(
    client: httpx.AsyncClient,
    token_id: str,
) -> OrderBook | None:
    """
    Fetch a single CLOB order book.  Returns None on any failure
    (HTTP error, timeout, malformed JSON, missing bids/asks arrays).
    """
    try:
        resp = await client.get(f"{CLOB_BASE}/book", params={"token_id": token_id})
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("CLOB fetch_book failed for %s: %s", token_id, exc)
        return None
    return _build_book(token_id, payload)


async def fetch_books(
    token_ids: list[str],
    timeout: float = 8.0,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict[str, OrderBook]:
    """
    Fetch CLOB order books for many tokens with bounded concurrency.

    Per-token failures do not fail the batch; failed tokens are omitted
    from the returned dict.  Duplicate token_ids are fetched only once.
    Empty / falsy token_ids are ignored.

    `concurrency` caps the number of simultaneously in-flight HTTP requests
    via an `asyncio.Semaphore`, complementing the httpx connection-pool limit.
    Both are needed because unbounded fan-out (~2k+ requests in one gather)
    was observed to silently produce zero results under uvicorn.
    """
    requested = len(token_ids)
    unique_ids = list(dict.fromkeys(t for t in token_ids if t))
    if not unique_ids:
        logger.debug(
            "CLOB fetch_books: requested=%d unique=0 ok=0 fail=0 elapsed=0.00s",
            requested,
        )
        return {}

    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    t0 = time.monotonic()

    async def _bounded(client: httpx.AsyncClient, tid: str) -> OrderBook | None:
        async with sem:
            return await fetch_book(client, tid)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        results = await asyncio.gather(
            *(_bounded(client, tid) for tid in unique_ids),
            return_exceptions=True,
        )

    books: dict[str, OrderBook] = {}
    failures = 0
    for tid, result in zip(unique_ids, results):
        if isinstance(result, OrderBook):
            books[tid] = result
        else:
            failures += 1
            if isinstance(result, BaseException):
                # Log only a short prefix of the token to avoid leaking full IDs.
                logger.debug("CLOB fetch_book exception for %s…: %s", tid[:16], result)

    elapsed = time.monotonic() - t0
    logger.debug(
        "CLOB fetch_books: requested=%d unique=%d ok=%d fail=%d elapsed=%.2fs",
        requested, len(unique_ids), len(books), failures, elapsed,
    )
    return books
