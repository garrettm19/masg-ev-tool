"""
In-memory opportunity snapshot.

Stores the latest pipeline result so the frontend can read cached
opportunities without re-running the pipeline on every request.

Writers:
  - MonitorScheduler (after each pipeline cycle)
  - POST /api/opportunities/refresh (manual refresh, runs in background)

Readers:
  - GET /api/opportunities (returns snapshot if fresh)
  - GET /api/opportunities/snapshot (read-only)
  - GET /api/opportunities/status (lightweight metadata)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

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
_refresh_lock: asyncio.Lock = asyncio.Lock()      # serializes pipeline runs

# Background refresh metadata (manual refresh runs detached so POST returns fast)
_start_lock: asyncio.Lock = asyncio.Lock()        # serializes spawn decision (brief)
_refresh_started_at: float | None = None
_last_refresh_error: str | None = None
_last_refresh_duration_seconds: float | None = None
_last_trigger: str | None = None
_background_task: asyncio.Task | None = None     # held to prevent GC


def get_snapshot() -> OpportunitySnapshot | None:
    """Read the current snapshot. No I/O, no pipeline."""
    return _snapshot


def is_refreshing() -> bool:
    """True if a pipeline run is in progress."""
    return _is_refreshing


def get_refresh_state() -> dict:
    """Lightweight read-only snapshot of background-refresh metadata."""
    return {
        "is_refreshing": _is_refreshing,
        "refresh_started_at": _refresh_started_at,
        "last_refresh_error": _last_refresh_error,
        "last_refresh_duration_seconds": _last_refresh_duration_seconds,
        "last_trigger": _last_trigger,
    }


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

    Synchronous from the caller's point of view (awaits the full pipeline).
    For non-blocking manual refreshes, use start_background_refresh().
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


async def _run_and_record(trigger: str, scope: str, started_at: float) -> None:
    """
    Detached coroutine that runs refresh_snapshot and records timing/errors.
    Never propagates exceptions — errors are stashed in _last_refresh_error.

    `started_at` is supplied by start_background_refresh so that the timestamp
    is visible to status readers the instant the spawn returns, not only
    after this coroutine begins executing.
    """
    global _is_refreshing, _refresh_started_at, _last_refresh_error
    global _last_refresh_duration_seconds
    try:
        await refresh_snapshot(trigger=trigger, scope=scope)
        _last_refresh_error = None
    except Exception as exc:
        logger.exception("Background refresh failed")
        _last_refresh_error = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        _last_refresh_duration_seconds = time.time() - started_at
        _refresh_started_at = None
        # Belt-and-suspenders: refresh_snapshot already resets this in its own
        # finally block, but if it raised before entering the lock body we
        # would leak _is_refreshing=True without this.
        _is_refreshing = False


async def start_background_refresh(
    trigger: str = "manual",
    scope: str = "stale",
) -> dict:
    """
    Spawn a detached background refresh if one is not already running.

    Returns immediately with status:
      {
        "started": bool,            # True if we spawned a new refresh
        "already_running": bool,    # True if a refresh was already in flight
        "started_at": float | None, # unix seconds when current refresh began
      }

    Race-safe: uses _start_lock to serialize the spawn decision. _is_refreshing,
    _refresh_started_at and _last_trigger are set synchronously under the lock
    so the very next status read (or near-simultaneous double POST) sees a
    consistent in-flight state without waiting for the spawned task to start.
    """
    global _background_task, _is_refreshing, _refresh_started_at, _last_trigger
    async with _start_lock:
        if _is_refreshing or _refresh_lock.locked():
            return {
                "started": False,
                "already_running": True,
                "started_at": _refresh_started_at,
            }
        started_at = time.time()
        _is_refreshing = True
        _refresh_started_at = started_at
        _last_trigger = trigger
        _background_task = asyncio.create_task(
            _run_and_record(trigger, scope, started_at)
        )
        return {
            "started": True,
            "already_running": False,
            "started_at": started_at,
        }


def clear_snapshot() -> None:
    """Clear the snapshot AND background-refresh state. For testing only."""
    global _snapshot, _is_refreshing
    global _refresh_started_at, _last_refresh_error
    global _last_refresh_duration_seconds, _last_trigger, _background_task
    _snapshot = None
    _is_refreshing = False
    _refresh_started_at = None
    _last_refresh_error = None
    _last_refresh_duration_seconds = None
    _last_trigger = None
    _background_task = None
