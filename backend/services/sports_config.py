"""
Central sports configuration.

Every supported sport is defined here.  All adapters, the odds provider,
and the matcher import from this module — it is the single source of truth.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SportConfig:
    key: str                              # internal identifier
    label: str                            # human-readable name
    odds_api_group: str | None = None     # dynamic discovery (e.g., "Tennis")
    odds_api_keys: list[str] = field(default_factory=list)  # explicit keys
    kalshi_series: dict[str, str] = field(default_factory=dict)  # ticker -> url slug
    pm_tag: str | None = None             # Polymarket tag_slug
    market_types: list[str] = field(default_factory=lambda: ["h2h"])
    match_style: str = "individual"       # "individual" (last-name) or "team" (full-name)


SPORTS: dict[str, SportConfig] = {
    "tennis": SportConfig(
        key="tennis",
        label="Tennis",
        odds_api_group="Tennis",
        kalshi_series={
            "KXATPMATCH": "atp-tennis-match",
            "KXWTAMATCH": "wta-tennis-match",
        },
        pm_tag="tennis",
        market_types=["h2h", "totals", "handicap"],
        match_style="individual",
    ),
    "mma": SportConfig(
        key="mma",
        label="MMA / UFC",
        odds_api_keys=["mma_mixed_martial_arts"],
        kalshi_series={
            "KXUFCFIGHT": "ufc-fight",
        },
        pm_tag="ufc",
        market_types=["h2h"],
        match_style="individual",
    ),
    "cricket_ipl": SportConfig(
        key="cricket_ipl",
        label="Cricket IPL",
        odds_api_keys=["cricket_ipl"],
        kalshi_series={
            "KXIPLGAME": "indian-premier-league-cricket-game",
        },
        pm_tag="cricket",
        market_types=["h2h"],
        match_style="team",
    ),
    "rugby_nrl": SportConfig(
        key="rugby_nrl",
        label="Rugby NRL",
        odds_api_keys=["rugbyleague_nrl"],
        kalshi_series={
            "KXRUGBYNRLMATCH": "rugby-nrl-match",
        },
        pm_tag="rugby",
        market_types=["h2h"],
        match_style="team",
    ),
    "ufl": SportConfig(
        key="ufl",
        label="UFL",
        odds_api_keys=["americanfootball_ufl"],
        kalshi_series={
            "KXUFLGAME": "ufl-football-game",
        },
        pm_tag=None,
        market_types=["h2h"],
        match_style="team",
    ),
    "hockey_ahl": SportConfig(
        key="hockey_ahl",
        label="Hockey AHL",
        odds_api_keys=["icehockey_ahl"],
        kalshi_series={
            "KXAHLGAME": "ahl-game",
        },
        pm_tag="hockey",
        market_types=["h2h"],
        match_style="team",
    ),
}


# ---------------------------------------------------------------------------
# Helpers — used by adapters and the odds provider
# ---------------------------------------------------------------------------

def all_kalshi_series() -> dict[str, str]:
    """Merged ticker -> slug across all sports."""
    merged: dict[str, str] = {}
    for sc in SPORTS.values():
        merged.update(sc.kalshi_series)
    return merged


def all_pm_tags() -> list[str]:
    """Unique, non-None PM tags across all sports."""
    return list({sc.pm_tag for sc in SPORTS.values() if sc.pm_tag})


def all_explicit_odds_api_keys() -> list[str]:
    """All explicit odds API sport keys (non-group-based)."""
    keys: list[str] = []
    for sc in SPORTS.values():
        keys.extend(sc.odds_api_keys)
    return keys


def all_odds_api_groups() -> list[str]:
    """Unique group names for dynamic sport key discovery."""
    return list({sc.odds_api_group for sc in SPORTS.values() if sc.odds_api_group})
