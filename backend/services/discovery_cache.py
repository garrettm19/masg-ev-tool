"""
Per-sport FanDuel market discovery cache with TTL.

Stores which market keys FanDuel offers for each sport, discovered via
the /events/{eventId}/markets endpoint (1 credit per discovery call).

Same pattern as odds_cache.py and prop_cache.py.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredMarkets:
    sport_key: str
    event_id: str                    # event used for discovery (for logging)
    market_keys: list[str]           # FanDuel market keys available
    discovered_at: float


# Module-level cache keyed by sport_key
_cache: dict[str, DiscoveredMarkets] = {}


def get_discovered(sport_key: str, ttl_seconds: float = 14400) -> DiscoveredMarkets | None:
    """Return discovered markets if within TTL (default 4 hours), else None."""
    entry = _cache.get(sport_key)
    if entry is None:
        return None
    age = time.time() - entry.discovered_at
    if age > ttl_seconds:
        return None
    return entry


def store_discovered(
    sport_key: str,
    event_id: str,
    market_keys: list[str],
) -> DiscoveredMarkets:
    """Store one sport's discovered market keys."""
    entry = DiscoveredMarkets(
        sport_key=sport_key,
        event_id=event_id,
        market_keys=list(market_keys),
        discovered_at=time.time(),
    )
    _cache[sport_key] = entry
    return entry


def clear_cache() -> None:
    """Reset for testing."""
    _cache.clear()
