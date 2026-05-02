"""
Scan configuration API — per-sport fetch settings and cost control.

Read/write the scan config that controls which sports are fetched,
how often, and how long cached odds are reused.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

from services.scan_config import get_scan_config, update_scan_config
from services.odds_cache import cache_status
from services.sports_config import SPORTS, kalshi_series_to_sport

router = APIRouter()
logger = logging.getLogger(__name__)


class SportScanOut(BaseModel):
    key: str
    label: str
    enabled: bool
    odds_ttl_seconds: int
    market_types: list[str]


class PlatformScanOut(BaseModel):
    name: str
    label: str
    enabled: bool


class ScanConfigResponse(BaseModel):
    sports: dict[str, SportScanOut]
    platforms: dict[str, PlatformScanOut]
    global_max_odds_api_per_day: int
    odds_cache: dict[str, dict]


def _build_response() -> ScanConfigResponse:
    cfg = get_scan_config()
    return ScanConfigResponse(
        sports={
            k: SportScanOut(**asdict(v))
            for k, v in cfg.sports.items()
        },
        platforms={
            k: PlatformScanOut(**asdict(v))
            for k, v in cfg.platforms.items()
        },
        global_max_odds_api_per_day=cfg.global_max_odds_api_per_day,
        odds_cache=cache_status(),
    )


@router.get("/scan/config", response_model=ScanConfigResponse)
async def get_config() -> ScanConfigResponse:
    """Return current scan configuration and cache state."""
    return _build_response()


@router.post("/scan/config", response_model=ScanConfigResponse)
async def post_config(updates: dict) -> ScanConfigResponse:
    """
    Update scan configuration.

    Examples:
      {"sports": {"tennis": {"enabled": false}}}
      {"sports": {"cricket_ipl": {"odds_ttl_seconds": 1800}}}
      {"platforms": {"polymarket": {"enabled": true}}}
      {"global_max_odds_api_per_day": 100}
    """
    update_scan_config(updates)
    logger.info("Scan config updated: %s", updates)
    return _build_response()


class BookStatus(BaseModel):
    has_data: bool
    event_count: int
    cache_age_seconds: float | None      # None if no cached data
    raw_count: int | None = None         # Kalshi only: markets from API before matching


class SportDataStatus(BaseModel):
    key: str
    label: str
    fanduel: BookStatus
    polymarket: BookStatus
    kalshi: BookStatus


@router.get("/data-status", response_model=list[SportDataStatus])
async def get_data_status() -> list[SportDataStatus]:
    """
    Per-sport, per-book data status matrix.

    Shows which sports have data from each source and how fresh it is.
    Derived from the odds cache (FanDuel) and the latest snapshot
    (Polymarket/Kalshi market counts).
    """
    from services.snapshot import get_snapshot
    import time

    snapshot = get_snapshot()
    odds = cache_status()

    # Count PM and Kalshi markets per sport from snapshot
    pm_counts: dict[str, int] = {}
    k_counts: dict[str, int] = {}
    if snapshot:
        for opp in snapshot.opportunities:
            sport = opp.sport
            # Map odds API sport key back to sport config key
            config_key = ""
            for sk, sc in SPORTS.items():
                if sport in sc.odds_api_keys or sport.startswith(sk):
                    config_key = sk
                    break
            if not config_key:
                continue
            if opp.platform == "polymarket":
                pm_counts[config_key] = pm_counts.get(config_key, 0) + 1
            elif opp.platform == "kalshi":
                k_counts[config_key] = k_counts.get(config_key, 0) + 1

    # Raw Kalshi counts per sport (from adapter series_counts in snapshot meta)
    k_raw: dict[str, int] = {}
    if snapshot:
        series_map = kalshi_series_to_sport()
        series_counts = snapshot.meta.get("kalshi_series_counts", {})
        for ticker, counts in series_counts.items():
            sport_key = series_map.get(ticker, "")
            if sport_key:
                raw = counts.get("raw", 0)
                if raw > 0:
                    k_raw[sport_key] = k_raw.get(sport_key, 0) + raw

    now = time.time()
    result: list[SportDataStatus] = []
    for key, sc in sorted(SPORTS.items(), key=lambda x: x[1].label):
        if not sc.enabled:
            continue
        # FanDuel: check odds cache for any matching sport key
        fd_events = 0
        fd_age: float | None = None
        for cache_key, info in odds.items():
            # Match cache key to sport config key
            for api_key in sc.odds_api_keys:
                if cache_key == api_key:
                    fd_events += info["event_count"]
                    fd_age = info["age_seconds"] if fd_age is None else min(fd_age, info["age_seconds"])
            if sc.odds_api_group and cache_key.startswith(key):
                fd_events += info["event_count"]
                fd_age = info["age_seconds"] if fd_age is None else min(fd_age, info["age_seconds"])

        result.append(SportDataStatus(
            key=key,
            label=sc.label,
            fanduel=BookStatus(
                has_data=fd_events > 0,
                event_count=fd_events,
                cache_age_seconds=round(fd_age, 1) if fd_age is not None else None,
            ),
            polymarket=BookStatus(
                has_data=pm_counts.get(key, 0) > 0,
                event_count=pm_counts.get(key, 0),
                cache_age_seconds=round(now - snapshot.updated_at, 1) if snapshot and pm_counts.get(key, 0) > 0 else None,
            ),
            kalshi=BookStatus(
                has_data=k_counts.get(key, 0) > 0 or k_raw.get(key, 0) > 0,
                event_count=k_counts.get(key, 0),
                cache_age_seconds=round(now - snapshot.updated_at, 1) if snapshot and (k_counts.get(key, 0) > 0 or k_raw.get(key, 0) > 0) else None,
                raw_count=k_raw.get(key) or None,
            ),
        ))

    return result


class SportRegistryEntry(BaseModel):
    key: str
    label: str
    match_style: str
    market_types: list[str]


@router.get("/sports", response_model=dict[str, SportRegistryEntry])
async def get_sports_registry() -> dict[str, SportRegistryEntry]:
    """
    Static sport registry — returns all configured sports with labels
    and metadata. Zero cost, read from in-memory config.

    Frontend uses this to derive sport labels, filter options, and
    display logic from a single source instead of hardcoding.
    """
    return {
        key: SportRegistryEntry(
            key=key,
            label=sc.label,
            match_style=sc.match_style,
            market_types=list(sc.market_types),
        )
        for key, sc in SPORTS.items()
        if sc.enabled
    }
