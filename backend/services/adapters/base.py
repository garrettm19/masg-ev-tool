"""
MarketAdapter protocol and NormalizedMarket schema.

Every prediction market platform (Polymarket, Kalshi, etc.) normalizes its
raw data into NormalizedMarket objects.  The opportunities engine consumes
these platform-agnostic objects and compares them against FanDuel truth odds.
"""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class NormalizedMarket:
    """
    Platform-agnostic market representation.

    Every adapter must produce this exact shape.  The opportunities engine
    and matcher operate exclusively on NormalizedMarket — they never see
    platform-specific raw data.
    """
    # Identity
    platform: str               # "polymarket" | "kalshi" | ...
    market_id: str              # platform-specific unique ID

    # Event
    event: str                  # human-readable event name
    market_type: str            # "h2h" | "handicap" | "totals" | "first_set"
    side: str                   # player name or "Over"/"Under" (empty if TBD)
    line: float | None          # handicap/totals line; None for h2h

    # Pricing
    price: float                # market price for the Yes/primary outcome (0–1)
    liquidity: float | None     # platform liquidity in USD (None if unknown)

    # Links and timing
    url: str | None             # canonical URL to view this market
    timestamp: str | None       # ISO-8601 UTC — market end/resolution time

    # Fields needed by the matcher and enrichment engine
    question: str               # full question text (used for player name matching)
    end_date: str | None        # market end date (used for date proximity scoring)
    outcome_prices: list[str] | None  # e.g. ["0.73", "0.27"] — Yes/No prices
    event_slug: str | None      # platform-specific slug for URL construction

    # Data quality
    bid_ask_spread: float | None = None  # yes_ask - yes_bid; None if unavailable

    # Top-of-book — best YES bid and best YES ask from the market list, in
    # dollars on tick.  Populated by adapters that have this data; None when
    # unavailable.  For Kalshi 2-way these are cross-market values
    # (max for bid, min for ask); for 3-way they are direct from the team's
    # own market.  These are maker-planning inputs and are independent of
    # ``price`` (which remains the existing taker-entry value).
    best_bid: float | None = None
    best_ask: float | None = None

    # Execution route for the canonical side's best YES bid.  In 2-way
    # Kalshi, if the best YES bid for the canonical side comes from the
    # complement market's NO bid (because NO_M2 ≡ YES_M1 in 2-way), that
    # contract — not the canonical ticker — is what a maker would actually
    # post on.  contract_side is "yes" for direct-YES routes, "no" for
    # equivalent-NO routes.  Both fields are None for non-Kalshi platforms
    # and for 2-way markets where neither route has a positive bid.
    best_bid_market_id: str | None = None
    best_bid_contract_side: str | None = None

    # Per-side TOB for the no_player (complement) perspective.  Only
    # 2-way Kalshi populates these — 3-way emits separate NormalizedMarkets
    # per team so the complement view is unnecessary, and Polymarket leaves
    # them None.  feature_extractor uses this pair when building the
    # no_player MarketFeatures so each side carries its own correct
    # best_bid/best_ask and route info.
    no_player_best_bid: float | None = None
    no_player_best_ask: float | None = None
    no_player_best_bid_market_id: str | None = None
    no_player_best_bid_contract_side: str | None = None

    # Staleness tracking
    fetched_at: float = 0.0     # time.time() when price data was obtained


@runtime_checkable
class MarketAdapter(Protocol):
    """
    Interface for prediction market platform adapters.

    Each adapter fetches active markets from its platform and normalizes
    them into NormalizedMarket objects.  Only markets that can be meaningfully
    compared against sportsbook odds should be returned (e.g., h2h tennis
    match markets, not outright futures).
    """

    platform_name: str

    async def fetch_markets(self) -> list[NormalizedMarket]:
        """Fetch and normalize active markets from this platform."""
        ...
