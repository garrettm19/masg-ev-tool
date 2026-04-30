/**
 * Sport label resolution.
 *
 * Resolves Odds API sport keys (e.g., "tennis_atp_french_open") to
 * human-readable labels (e.g., "Tennis") using the backend registry
 * when available, falling back to prefix matching for offline/SSR.
 *
 * Single source of truth for sport labels across all frontend components.
 */

export interface SportRegistryEntry {
  key: string;
  label: string;
  match_style: string;
  market_types: string[];
}

/**
 * Fallback label derivation when the registry is not yet loaded.
 * Matches Odds API sport keys by prefix to sport config keys.
 */
const PREFIX_FALLBACK: [string, string][] = [
  ["tennis", "Tennis"],
  ["mma", "MMA"],
  ["cricket", "Cricket"],
  ["rugby", "Rugby"],
  ["americanfootball_nfl", "NFL"],
  ["americanfootball_ufl", "UFL"],
  ["icehockey_nhl", "NHL"],
  ["icehockey_ahl", "Hockey AHL"],
  ["basketball_nba", "NBA"],
  ["baseball_mlb", "MLB"],
  ["soccer_usa_mls", "MLS"],
  ["soccer_epl", "EPL"],
  ["soccer_france", "Ligue 1"],
  ["soccer_italy", "Serie A"],
  ["soccer_germany", "Bundesliga"],
  ["soccer_spain", "La Liga"],
  ["soccer_uefa", "UCL"],
  ["aussierules_afl", "AFL"],
  ["baseball_kbo", "KBO"],
  ["mma", "UFC/MMA"],
];

/**
 * Resolve a sport label from an Odds API sport key.
 *
 * Uses the backend registry if provided (keyed by sport config key,
 * e.g., "tennis" → "Tennis"). Falls back to prefix matching for
 * Odds API keys like "tennis_atp_french_open".
 */
export function sportLabel(
  sportKey: string,
  registry?: Record<string, SportRegistryEntry>,
): string {
  // Direct registry hit (sport config key)
  if (registry && registry[sportKey]) {
    return registry[sportKey].label;
  }

  // Prefix match against registry labels (Odds API key → sport config key)
  if (registry) {
    for (const entry of Object.values(registry)) {
      if (sportKey.startsWith(entry.key)) {
        return entry.label;
      }
    }
  }

  // Fallback (offline/SSR)
  for (const [prefix, label] of PREFIX_FALLBACK) {
    if (sportKey.startsWith(prefix)) {
      return label;
    }
  }

  return sportKey.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

/** Market type label — same everywhere. */
export function marketTypeLabel(mt: string): string {
  switch (mt) {
    case "h2h": return "H2H";
    case "handicap": return "Handicap";
    case "totals": return "Totals";
    case "first_set": return "1st Set";
    case "player_points": return "Points";
    case "player_rebounds": return "Rebounds";
    case "player_assists": return "Assists";
    case "player_threes": return "Threes";
    case "player_points_rebounds_assists": return "PRA";
    case "player_pass_tds": return "Pass TDs";
    case "player_pass_yds": return "Pass Yds";
    case "player_rush_yds": return "Rush Yds";
    case "player_rush_tds": return "Rush TDs";
    case "player_receptions": return "Receptions";
    case "player_reception_yds": return "Rec Yds";
    case "player_anytime_td": return "Any TD";
    case "batter_hits": return "Hits";
    case "batter_total_bases": return "Total Bases";
    case "batter_home_runs": return "Home Runs";
    case "batter_rbis": return "RBIs";
    case "batter_strikeouts": return "Bat K";
    case "pitcher_strikeouts": return "Pitch K";
    case "pitcher_outs": return "Outs";
    default: return mt.replace(/_/g, " ").replace(/\b(?:player|batter|pitcher)\b/gi, "").trim() || mt;
  }
}

/** True if market_type is a player prop (not h2h/totals/handicap). */
export function isPropType(mt: string): boolean {
  return mt.startsWith("player_") || mt.startsWith("batter_") || mt.startsWith("pitcher_");
}
