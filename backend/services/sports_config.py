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
    enabled: bool = True                  # False = no usable sportsbook lines; excluded from pipeline
    odds_api_group: str | None = None     # dynamic discovery (e.g., "Tennis")
    odds_api_keys: list[str] = field(default_factory=list)  # explicit keys
    kalshi_series: dict[str, str] = field(default_factory=dict)  # ticker -> url slug
    pm_tag: str | None = None             # Polymarket tag_slug
    market_types: list[str] = field(default_factory=lambda: ["h2h"])
    prop_markets: list[str] = field(default_factory=list)  # Odds API prop keys to fetch
    enable_discovery: bool = False    # opt-in: validate market_types against FanDuel availability
    match_style: str = "individual"       # "individual" (last-name) or "team" (full-name)
    max_plausible_edge: float = 0.20      # edges above this are likely data errors
    min_edge: float = 0.05                # minimum edge for BUY (liquid sports use lower)
    # Maximum hours between PM market end_date and FD event commence_time before
    # _date_not_stale rejects as a wrong-game match.  Default is lenient (72h)
    # for sports where PM endDate is the TOURNAMENT end date (tennis/MMA).
    # Liquid team sports with discrete games (MLB/NBA/NHL/...) override to 12h
    # so that a multi-game series doesn't pair a future PM market with the
    # next-imminent FD event when only one FD game has odds published.
    max_date_delta_hours: float = 72.0


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
        market_types=["h2h"],
        match_style="individual",
        max_plausible_edge=0.25,          # wider lines, higher variance
    ),
    "cricket_ipl": SportConfig(
        key="cricket_ipl",
        label="Cricket IPL",
        enabled=False,                    # FanDuel has events but no bookmaker lines
        odds_api_keys=["cricket_ipl"],
        kalshi_series={
            "KXIPLGAME": "indian-premier-league-cricket-game",
        },
        pm_tag="cricket",
        market_types=["h2h"],
        match_style="team",
        max_plausible_edge=0.20,
        max_date_delta_hours=12.0,
    ),
    "rugby_nrl": SportConfig(
        key="rugby_nrl",
        label="Rugby NRL",
        enabled=False,                    # FanDuel has events but no bookmaker lines
        odds_api_keys=["rugbyleague_nrl"],
        kalshi_series={
            "KXRUGBYNRLMATCH": "rugby-nrl-match",
        },
        pm_tag="rugby",
        market_types=["h2h"],
        match_style="team",
        max_plausible_edge=0.20,
        max_date_delta_hours=12.0,
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
        max_plausible_edge=0.20,          # thinner markets, allow higher
        max_date_delta_hours=12.0,
    ),
    "hockey_ahl": SportConfig(
        key="hockey_ahl",
        label="Hockey AHL",
        enabled=False,                    # FanDuel has events but no bookmaker lines
        odds_api_keys=["icehockey_ahl"],
        kalshi_series={
            "KXAHLGAME": "ahl-game",
        },
        pm_tag="hockey",
        market_types=["h2h"],
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
    "basketball_nba": SportConfig(
        key="basketball_nba",
        label="NBA",
        odds_api_keys=["basketball_nba"],
        kalshi_series={
            "KXNBAGAME": "nba-game",
        },
        pm_tag="basketball",
        market_types=["h2h", "totals"],
        prop_markets=[
            "player_points", "player_rebounds", "player_assists",
            "player_threes", "player_points_rebounds_assists",
        ],
        enable_discovery=True,
        match_style="team",
        max_plausible_edge=0.12,          # liquid market, tight lines
        min_edge=0.03,                    # liquid — lower threshold
        max_date_delta_hours=12.0,
    ),
    "basketball_wnba": SportConfig(
        key="basketball_wnba",
        label="WNBA",
        odds_api_keys=["basketball_wnba"],
        kalshi_series={
            "KXWNBAGAME": "wnba-game",
        },
        pm_tag="basketball",
        market_types=["h2h"],
        match_style="team",
        max_plausible_edge=0.15,          # thinner than NBA
        max_date_delta_hours=12.0,
    ),
    "baseball_mlb": SportConfig(
        key="baseball_mlb",
        label="MLB",
        odds_api_keys=["baseball_mlb"],
        kalshi_series={
            "KXMLBGAME": "mlb-game",
        },
        pm_tag="baseball",
        market_types=["h2h", "totals"],
        prop_markets=[
            "batter_hits", "batter_total_bases", "batter_home_runs",
            "batter_rbis", "batter_strikeouts",
            "pitcher_strikeouts", "pitcher_outs",
        ],
        enable_discovery=True,
        match_style="team",
        max_plausible_edge=0.15,          # liquid market
        min_edge=0.03,                    # liquid — lower threshold
        max_date_delta_hours=12.0,
    ),
    "hockey_nhl": SportConfig(
        key="hockey_nhl",
        label="NHL",
        odds_api_keys=["icehockey_nhl"],
        kalshi_series={
            "KXNHLGAME": "nhl-game",
        },
        pm_tag="hockey",
        market_types=["h2h", "totals"],
        enable_discovery=True,
        match_style="team",
        max_plausible_edge=0.12,          # liquid market, tight lines
        min_edge=0.03,                    # liquid — lower threshold
        max_date_delta_hours=12.0,
    ),
    "football_nfl": SportConfig(
        key="football_nfl",
        label="NFL",
        odds_api_keys=["americanfootball_nfl"],
        kalshi_series={
            "KXNFLGAME": "nfl-game",
        },
        pm_tag=None,
        market_types=["h2h"],
        prop_markets=[
            "player_pass_tds", "player_pass_yds",
            "player_rush_yds", "player_rush_tds",
            "player_receptions", "player_reception_yds",
            "player_anytime_td",
        ],
        enable_discovery=True,
        match_style="team",
        max_plausible_edge=0.12,
        max_date_delta_hours=12.0,
    ),
    "soccer_mls": SportConfig(
        key="soccer_mls",
        label="MLS",
        odds_api_keys=["soccer_usa_mls"],
        kalshi_series={
            "KXMLSGAME": "mls-game",
        },
        pm_tag="soccer",
        market_types=["h2h"],             # FanDuel returns no totals via Odds API
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
    "soccer_epl": SportConfig(
        key="soccer_epl",
        label="EPL",
        odds_api_keys=["soccer_epl"],
        kalshi_series={
            "KXEPLGAME": "epl-game",
        },
        pm_tag="soccer",
        market_types=["h2h"],             # FanDuel returns no totals via Odds API
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
    "afl": SportConfig(
        key="afl",
        label="AFL",
        enabled=False,                    # FanDuel has events but no bookmaker lines
        odds_api_keys=["aussierules_afl"],
        kalshi_series={
            "KXAFLGAME": "afl-game",
        },
        pm_tag=None,
        market_types=["h2h"],
        match_style="team",
        max_plausible_edge=0.20,
        max_date_delta_hours=12.0,
    ),
    "baseball_kbo": SportConfig(
        key="baseball_kbo",
        label="KBO",
        odds_api_keys=["baseball_kbo"],
        kalshi_series={
            "KXKBOGAME": "kbo-game",
        },
        pm_tag="baseball",             # shares tag with MLB (deduped by market id)
        market_types=["h2h"],
        match_style="team",
        max_plausible_edge=0.20,       # thinner market
        max_date_delta_hours=12.0,
    ),
    "mma": SportConfig(
        key="mma",
        label="UFC/MMA",
        odds_api_keys=["mma_mixed_martial_arts"],
        kalshi_series={
            "KXUFCFIGHT": "ufc-fight",
        },
        pm_tag="ufc",
        market_types=["h2h"],
        match_style="individual",
        max_plausible_edge=0.25,       # wider lines, individual sport
    ),
    "soccer_france": SportConfig(
        key="soccer_france",
        label="Ligue 1",
        odds_api_keys=["soccer_france_ligue_one"],
        kalshi_series={
            "KXLIGUE1GAME": "ligue-1-game",
        },
        pm_tag="soccer",
        market_types=["h2h"],             # FanDuel returns no totals via Odds API
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
    "soccer_italy": SportConfig(
        key="soccer_italy",
        label="Serie A",
        odds_api_keys=["soccer_italy_serie_a"],
        kalshi_series={
            "KXSERIEAGAME": "serie-a-game",
        },
        pm_tag="soccer",
        market_types=["h2h"],             # FanDuel returns no totals via Odds API
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
    "soccer_germany": SportConfig(
        key="soccer_germany",
        label="Bundesliga",
        odds_api_keys=["soccer_germany_bundesliga"],
        kalshi_series={
            "KXBUNDESLIGAGAME": "bundesliga-game",
        },
        pm_tag="soccer",
        market_types=["h2h"],             # FanDuel returns no totals via Odds API
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
    "soccer_spain": SportConfig(
        key="soccer_spain",
        label="La Liga",
        odds_api_keys=["soccer_spain_la_liga"],
        kalshi_series={
            "KXLALIGAGAME": "la-liga-game",
        },
        pm_tag="soccer",
        market_types=["h2h"],             # FanDuel returns no totals via Odds API
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
    "soccer_ucl": SportConfig(
        key="soccer_ucl",
        label="Champions League",
        odds_api_keys=["soccer_uefa_champs_league"],
        kalshi_series={
            "KXUCLGAME": "ucl-game",
        },
        pm_tag="soccer",
        market_types=["h2h"],             # FanDuel returns no totals via Odds API
        match_style="team",
        max_plausible_edge=0.15,
        max_date_delta_hours=12.0,
    ),
}


# ---------------------------------------------------------------------------
# Helpers — used by adapters and the odds provider
# ---------------------------------------------------------------------------

def _enabled() -> dict[str, "SportConfig"]:
    """Return only enabled sports — single filter used by all helpers."""
    return {k: sc for k, sc in SPORTS.items() if sc.enabled}


def all_kalshi_series() -> dict[str, str]:
    """Merged ticker -> slug across all enabled sports."""
    merged: dict[str, str] = {}
    for sc in _enabled().values():
        merged.update(sc.kalshi_series)
    return merged


def all_pm_tags() -> list[str]:
    """Unique, non-None PM tags across all enabled sports."""
    return list({sc.pm_tag for sc in _enabled().values() if sc.pm_tag})


def all_explicit_odds_api_keys() -> list[str]:
    """All explicit odds API sport keys (non-group-based, enabled only)."""
    keys: list[str] = []
    for sc in _enabled().values():
        keys.extend(sc.odds_api_keys)
    return keys


def kalshi_series_to_sport() -> dict[str, str]:
    """Reverse lookup: Kalshi series ticker → sport config key (enabled only)."""
    mapping: dict[str, str] = {}
    for key, sc in _enabled().items():
        for ticker in sc.kalshi_series:
            mapping[ticker] = key
    return mapping


def sports_with_props() -> dict[str, list[str]]:
    """Return {odds_api_key: [prop_market_keys]} for enabled sports with props configured."""
    result: dict[str, list[str]] = {}
    for sc in _enabled().values():
        if sc.prop_markets:
            for api_key in sc.odds_api_keys:
                result[api_key] = list(sc.prop_markets)
    return result


def all_odds_api_groups() -> list[str]:
    """Unique group names for dynamic sport key discovery (enabled only)."""
    return list({sc.odds_api_group for sc in _enabled().values() if sc.odds_api_group})


def config_for_odds_key(odds_api_key: str) -> "SportConfig | None":
    """Look up SportConfig by Odds API key (explicit keys and group-based).

    For explicit keys (e.g., "basketball_nba"), returns the matching config.
    For group-based keys (e.g., "tennis_atp_monte_carlo_masters"), matches
    the group prefix (e.g., "tennis").
    Returns None if no config matches.
    """
    for sc in SPORTS.values():
        if odds_api_key in sc.odds_api_keys:
            return sc
    # Fallback: match by group prefix (tennis_* → tennis config)
    for sc in SPORTS.values():
        if sc.odds_api_group and odds_api_key.startswith(sc.key):
            return sc
    return None
