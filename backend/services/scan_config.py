"""
Scan configuration — per-sport fetch control and cost management.

Determines which sports are fetched, how often, how long cached
odds are considered fresh, AND which prediction-market platforms
(Polymarket, Kalshi) participate in each scan.

Defaults:
  - Kalshi:     enabled=True
  - Polymarket: enabled=False
The scanner is a single-user local tool; defaults are tuned for the
user's primary book of record.  Polymarket can be re-enabled at
runtime via POST /api/scan/config.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SportScanConfig:
    """Per-sport scan settings."""
    key: str
    label: str = ""
    enabled: bool = True
    odds_ttl_seconds: int = 900          # 15 min default
    market_types: list[str] = field(default_factory=lambda: ["h2h"])


@dataclass
class PlatformScanConfig:
    """Per-platform scan settings — controls whether the adapter runs."""
    name: str                # "polymarket" | "kalshi"
    label: str = ""
    enabled: bool = True


@dataclass
class ScanConfig:
    """Global scan settings wrapping per-sport and per-platform configs."""
    sports: dict[str, SportScanConfig] = field(default_factory=dict)
    platforms: dict[str, PlatformScanConfig] = field(default_factory=dict)
    global_max_odds_api_per_day: int = 200


def _default_platforms() -> dict[str, PlatformScanConfig]:
    """Default platform map — Kalshi on, Polymarket off."""
    return {
        "kalshi": PlatformScanConfig(name="kalshi", label="Kalshi", enabled=True),
        "polymarket": PlatformScanConfig(name="polymarket", label="Polymarket", enabled=False),
    }


def build_default_scan_config() -> ScanConfig:
    """Build ScanConfig from the SPORTS registry (enabled sports only) and
    the default platform map."""
    from services.sports_config import SPORTS

    sports: dict[str, SportScanConfig] = {}
    for key, sc in SPORTS.items():
        if not sc.enabled:
            continue
        sports[key] = SportScanConfig(
            key=key,
            label=sc.label,
            enabled=True,
            odds_ttl_seconds=900,
            market_types=list(sc.market_types),
        )
    return ScanConfig(sports=sports, platforms=_default_platforms())


# Module-level singleton
_config: ScanConfig | None = None


def get_scan_config() -> ScanConfig:
    global _config
    if _config is None:
        _config = build_default_scan_config()
    return _config


def update_scan_config(updates: dict) -> ScanConfig:
    """
    Merge partial updates into the current config.

    Accepts:
      {"sports": {"tennis": {"enabled": false, "odds_ttl_seconds": 1800}}}
      {"platforms": {"polymarket": {"enabled": true}}}
      {"global_max_odds_api_per_day": 100}
    """
    cfg = get_scan_config()

    if "global_max_odds_api_per_day" in updates:
        cfg.global_max_odds_api_per_day = int(updates["global_max_odds_api_per_day"])

    for sport_key, sport_updates in updates.get("sports", {}).items():
        if sport_key not in cfg.sports:
            continue
        sc = cfg.sports[sport_key]
        for k, v in sport_updates.items():
            if hasattr(sc, k):
                setattr(sc, k, v)

    for platform_name, platform_updates in updates.get("platforms", {}).items():
        if platform_name not in cfg.platforms:
            continue
        pc = cfg.platforms[platform_name]
        for k, v in platform_updates.items():
            if hasattr(pc, k):
                setattr(pc, k, v)

    return cfg


def reset_scan_config() -> None:
    """Reset to defaults. For testing."""
    global _config
    _config = None
