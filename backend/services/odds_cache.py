"""
Per-sport-key odds cache with TTL.

Stores the last fetch result for each Odds API sport key so the pipeline
can skip re-fetching sports whose odds are still fresh.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from services.odds_provider import TennisOddsEvent

logger = logging.getLogger(__name__)


@dataclass
class CachedOdds:
    sport_key: str
    events: list[TennisOddsEvent]
    fetched_at: float
    quota_snapshot: dict = field(default_factory=dict)


# Module-level cache keyed by sport_key
_cache: dict[str, CachedOdds] = {}


def get_cached(sport_key: str, ttl_seconds: float) -> CachedOdds | None:
    """Return cached odds if within TTL, else None."""
    entry = _cache.get(sport_key)
    if entry is None:
        return None
    age = time.time() - entry.fetched_at
    if age > ttl_seconds:
        return None
    return entry


def store_cached(
    sport_key: str,
    events: list[TennisOddsEvent],
    quota: dict | None = None,
) -> CachedOdds:
    """Store one sport's fetch result."""
    entry = CachedOdds(
        sport_key=sport_key,
        events=list(events),
        fetched_at=time.time(),
        quota_snapshot=dict(quota) if quota else {},
    )
    _cache[sport_key] = entry
    return entry


def get_all_cached_events() -> list[TennisOddsEvent]:
    """Merge all cached sports into one flat event list."""
    merged: list[TennisOddsEvent] = []
    for entry in _cache.values():
        merged.extend(entry.events)
    return merged


def invalidate(sport_key: str) -> bool:
    """Remove one sport from cache. Returns True if it existed."""
    return _cache.pop(sport_key, None) is not None


def invalidate_all() -> int:
    """Remove all cached odds. Returns count cleared."""
    count = len(_cache)
    _cache.clear()
    return count


def cache_status() -> dict[str, dict]:
    """Return cache state for each sport key — for diagnostics."""
    now = time.time()
    return {
        key: {
            "event_count": len(entry.events),
            "fetched_at": entry.fetched_at,
            "age_seconds": round(now - entry.fetched_at, 1),
            "quota": entry.quota_snapshot,
        }
        for key, entry in _cache.items()
    }


def clear_cache() -> None:
    """Reset for testing."""
    _cache.clear()
