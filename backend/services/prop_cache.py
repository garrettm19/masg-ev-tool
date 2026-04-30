"""
Per-sport prop cache with TTL.

Same pattern as odds_cache.py but for PropEvent lists.
Prevents refetching prop data on every pipeline run.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from services.odds_provider import PropEvent

logger = logging.getLogger(__name__)


@dataclass
class CachedProps:
    sport_key: str
    events: list[PropEvent]
    fetched_at: float


# Module-level cache keyed by sport_key
_cache: dict[str, CachedProps] = {}


def get_cached(sport_key: str, ttl_seconds: float) -> CachedProps | None:
    """Return cached props if within TTL, else None."""
    entry = _cache.get(sport_key)
    if entry is None:
        return None
    age = time.time() - entry.fetched_at
    if age > ttl_seconds:
        return None
    return entry


def store_cached(
    sport_key: str,
    events: list[PropEvent],
) -> CachedProps:
    """Store one sport's prop fetch result."""
    entry = CachedProps(
        sport_key=sport_key,
        events=list(events),
        fetched_at=time.time(),
    )
    _cache[sport_key] = entry
    return entry


def get_all_cached_props() -> list[PropEvent]:
    """Merge all cached sports into one flat prop event list."""
    merged: list[PropEvent] = []
    for entry in _cache.values():
        merged.extend(entry.events)
    return merged


def clear_cache() -> None:
    """Reset for testing."""
    _cache.clear()
