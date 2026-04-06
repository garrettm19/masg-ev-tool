// ---------------------------------------------------------------------------
// Opportunities — matched prediction markets vs sportsbook (normalised)
// ---------------------------------------------------------------------------

export interface Opportunity {
  // Platform & sport
  platform: string;                 // "polymarket" | "kalshi" | ...
  sport: string;                    // odds API sport_key

  // Event
  event: string;                    // "Player A vs Player B"
  event_url: string | null;
  tournament: string;
  start_time: string;               // ISO-8601 UTC

  // Market
  market_id: string;
  market_type: string;              // "h2h" | "handicap" | "totals" | "first_set"
  side: string;                     // player name (h2h) or "Over"/"Under"
  line: number | null;              // handicap/totals line; null for h2h

  // Pricing — all for the SAME normalised side
  pm_price: number;
  fd_odds: number;                  // FanDuel American odds for this side
  p_true: number;                   // devigged true probability
  edge: number;                     // p_true - pm_price_effective
  recommended_kelly: number;

  // FanDuel metrics (FanDuel only)
  fanduel_overround: number;
  fanduel_line_width: number;
  fanduel_line_width_label: string; // "Tight" | "Moderate" | "Wide"
  fanduel_confidence_label: string; // "High" | "Medium" | "Low"

  // Event match
  event_match_confidence: number;

  // Status
  status: string;                   // "BUY" | "WATCH" | "SKIP"
}

export interface OpportunitiesResponse {
  opportunities: Opportunity[];
  total: number;
  quota_remaining: string | null;
  sportsbook_markets_fetched: string[];
  markets_dropped_by_type: Record<string, number>;
  platforms_fetched: string[];
}
