"""
Gamma API events flow — active, open, sports events only.
Primary data source replacing the broad /markets fetch.
"""
import httpx
import os

GAMMA_BASE = os.getenv("GAMMA_API_BASE", "https://gamma-api.polymarket.com")


async def fetch_active_events(
    limit: int = 100,
    offset: int = 0,
    tag_slug: str | None = None,
) -> list[dict]:
    """Fetch active, non-closed events from Gamma API, optionally filtered by tag slug."""
    params: dict[str, str | int] = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "offset": offset,
    }
    if tag_slug:
        params["tag_slug"] = tag_slug
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{GAMMA_BASE}/events", params=params)
        response.raise_for_status()
        data = response.json()
    # Gamma may return a plain list or a paginated envelope
    return data if isinstance(data, list) else data.get("data", [])


def extract_markets(events: list[dict]) -> list[dict]:
    """
    Flatten the markets nested inside each event.
    Inherits event-level category and slug if the market has none.
    event_slug is the canonical Polymarket URL slug (polymarket.com/event/{event_slug}).
    """
    markets = []
    for event in events:
        event_category = event.get("category")
        event_slug = event.get("slug")
        event_name = event.get("title") or event.get("name")
        for market in event.get("markets") or []:
            if not market.get("category") and event_category:
                market = {**market, "category": event_category}
            if event_slug:
                market = {**market, "event_slug": event_slug}
            if event_name:
                market = {**market, "event_name": event_name}
            markets.append(market)
    return markets


async def _fetch_paginated(tag_slug: str, limit: int = 500) -> list[dict]:
    """Paginate through all events for a single tag."""
    all_events: list[dict] = []
    offset = 0
    page_size = 100

    while len(all_events) < limit:
        batch = await fetch_active_events(
            limit=page_size, offset=offset, tag_slug=tag_slug,
        )
        if not batch:
            break
        all_events.extend(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
    return all_events


async def fetch_tennis_markets(limit: int = 500, offset: int = 0) -> list[dict]:
    """Backward-compatible: fetch tennis markets only."""
    return await fetch_markets_by_tags(["tennis"], limit=limit)


async def fetch_markets_by_tags(tags: list[str], limit: int = 500) -> list[dict]:
    """
    Fetch active markets from Polymarket for multiple sport tags.
    Deduplicates by market id across tags.
    """
    import asyncio

    tag_results = await asyncio.gather(
        *[_fetch_paginated(tag, limit=limit) for tag in tags]
    )

    # Deduplicate events by id
    seen_event_ids: set[str] = set()
    unique_events: list[dict] = []
    for events in tag_results:
        for ev in events:
            eid = ev.get("id") or ev.get("slug") or id(ev)
            if eid not in seen_event_ids:
                seen_event_ids.add(eid)
                unique_events.append(ev)

    return extract_markets(unique_events)
