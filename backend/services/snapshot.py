"""
In-memory opportunity snapshot.

Stores the latest pipeline result so the frontend can read cached
opportunities without re-running the pipeline on every request.

Writers:
  - MonitorScheduler (after each pipeline cycle)
  - GET /api/opportunities?force_refresh=true (manual refresh)

Readers:
  - GET /api/opportunities (returns snapshot if fresh)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from services.opportunities import EvaluatedOpportunity

logger = logging.getLogger(__name__)


@dataclass
class OpportunitySnapshot:
    """Immutable snapshot of the last pipeline result."""
    opportunities: list[EvaluatedOpportunity]
    meta: dict
    updated_at: float                  # time.time() of pipeline completion
    trigger: str                       # "startup" | "scheduled" | "manual" | "ws:..."


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_snapshot: OpportunitySnapshot | None = None
_is_refreshing: bool = False
_refresh_lock: asyncio.Lock = asyncio.Lock()


def get_snapshot() -> OpportunitySnapshot | None:
    """Read the current snapshot. No I/O, no pipeline."""
    return _snapshot


def is_refreshing() -> bool:
    """True if a pipeline run is in progress."""
    return _is_refreshing


def store_snapshot(
    opportunities: list[EvaluatedOpportunity],
    meta: dict,
    trigger: str = "unknown",
) -> OpportunitySnapshot:
    """Store a new snapshot from an already-completed pipeline run."""
    global _snapshot
    _snapshot = OpportunitySnapshot(
        opportunities=opportunities,
        meta=dict(meta),
        updated_at=time.time(),
        trigger=trigger,
    )
    logger.info(
        "Snapshot stored: %d opportunities, trigger=%s",
        len(opportunities), trigger,
    )
    return _snapshot


async def refresh_snapshot(
    trigger: str = "manual",
    scope: str = "stale",
) -> OpportunitySnapshot:
    """
    Run the pipeline and store the result as the new snapshot.

    scope controls odds cache invalidation before the pipeline runs:
      "stale"       — only fetch sports whose TTL expired (default, cheapest)
      "all"         — invalidate entire odds cache, fetch everything fresh
      "{sport_key}" — invalidate one sport's cache, fetch it fresh

    Acquires _refresh_lock to prevent concurrent pipeline runs.
    Sets is_refreshing=True while running.
    """
    global _is_refreshing

    # Import here to avoid circular import (snapshot ← opportunities → snapshot)
    from services.opportunities import fetch_opportunities, DEFAULT_CONFIG
    from services import odds_cache

    async with _refresh_lock:
        _is_refreshing = True
        try:
            # Invalidate cache per scope
            if scope == "all":
                odds_cache.invalidate_all()
            elif scope != "stale":
                odds_cache.invalidate(scope)
            # "stale" → no invalidation; TTL checks in fetch_odds handle it

            opportunities, meta = await fetch_opportunities(cfg=DEFAULT_CONFIG)
            return store_snapshot(opportunities, meta, trigger=trigger)
        finally:
            _is_refreshing = False


def clear_snapshot() -> None:
    """Clear the snapshot. For testing only."""
    global _snapshot, _is_refreshing
    _snapshot = None
    _is_refreshing = False
