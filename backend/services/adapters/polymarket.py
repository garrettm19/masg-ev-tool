"""
Polymarket adapter — fetches tennis markets from the Gamma API and
normalizes them into NormalizedMarket objects.

Only h2h (moneyline / match-winner) markets are emitted.  Outright futures,
handicaps, totals, and first-set markets are classified and dropped here
so the downstream matcher and engine never see them.
"""
import logging
import time

from models.market import Market
from services.events import fetch_markets_by_tags
from services.sports_config import all_pm_tags
from services.adapters.base import NormalizedMarket

logger = logging.getLogger(__name__)


def _extract_game_date_from_slug(slug: str) -> str | None:
    """
    Extract ISO date from PM event slug.

    Slugs like 'mlb-ari-nym-2026-04-07' contain the game date.
    Returns 'YYYY-MM-DDT23:59:00Z' or None if no date found.
    """
    import re
    m = re.search(r'(\d{4}-\d{2}-\d{2})$', slug)
    if m:
        return f"{m.group(1)}T23:59:00Z"
    return None


def _is_game_date_past(slug: str) -> bool:
    """
    Check if the game date extracted from the slug is in the past.

    Returns True if the game date is before today (UTC), meaning the
    market is live or completed. Returns False if no date in slug.
    """
    from datetime import datetime, timezone
    game_date_str = _extract_game_date_from_slug(slug)
    if not game_date_str:
        return False
    try:
        game_date = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
        return game_date < datetime.now(timezone.utc)
    except (ValueError, AttributeError):
        return False


class PolymarketAdapter:
    platform_name: str = "polymarket"

    async def fetch_markets(self) -> list[NormalizedMarket]:
        """
        Fetch active Polymarket tennis markets, classify each by market type,
        and return only h2h markets as NormalizedMarket objects.

        Returns (markets, dropped_by_type) where dropped_by_type maps each
        non-h2h market type to its count — useful for diagnostics.
        """
        # Import here to avoid circular import (matcher → adapters.base → adapters → polymarket → matcher)
        from services.matcher import classify_pm_market_type

        tags = all_pm_tags()
        raw_markets = await fetch_markets_by_tags(tags, limit=500)
        fetch_ts = time.time()

        markets: list[Market] = []
        for raw in raw_markets:
            try:
                markets.append(Market(**raw))
            except Exception:
                pass

        normalized: list[NormalizedMarket] = []
        self._dropped_by_type: dict[str, int] = {}

        for mkt in markets:
            pm_type = classify_pm_market_type(mkt.question)

            # H2H and totals only — handicap/props/futures not supported
            if pm_type not in ("h2h", "totals"):
                self._dropped_by_type[pm_type] = self._dropped_by_type.get(pm_type, 0) + 1
                continue

            # Require valid binary prices
            if not mkt.outcomePrices or len(mkt.outcomePrices) < 2:
                continue
            try:
                price = float(mkt.outcomePrices[0])
            except (ValueError, TypeError):
                continue
            if price <= 0.02 or price >= 0.98:
                continue

            # Ensure outcome_prices is [YES, NO] — swap if outcomes labels are reversed.
            # Polymarket uses two formats:
            #   1. outcomes=["Yes","No"] — outcomePrices[0]=YES price, [1]=NO price
            #   2. outcomes=["Team A","Team B"] — outcomePrices[0]=Team A price, [1]=Team B price
            # For format 2, we set side=outcomes[0] so the feature extractor knows
            # which team's price is at index 0 (same as the Kalshi YES hint).
            outcome_prices = list(mkt.outcomePrices)
            side_hint = ""
            if mkt.outcomes and len(mkt.outcomes) >= 2:
                o0 = mkt.outcomes[0].lower().strip()
                o1 = mkt.outcomes[1].lower().strip()
                if o0 == "no":
                    # Format 1 with reversed labels: swap to [YES, NO]
                    outcome_prices = [outcome_prices[1], outcome_prices[0]]
                    price = float(outcome_prices[0])
                elif o0 != "yes" and o1 != "yes":
                    # Format 2: team-name outcomes (e.g., ["Athletics", "New York Yankees"])
                    # outcomePrices[0] is the first team's price, not necessarily YES
                    # Set side hint to first team so feature extractor aligns correctly
                    side_hint = mkt.outcomes[0]

            event_slug = mkt.event_slug
            url = f"https://polymarket.com/event/{event_slug}" if event_slug else None

            # Skip live/completed games — game date from slug is in the past
            if event_slug and _is_game_date_past(event_slug):
                continue

            # Use game date from slug if available (e.g., "mlb-ari-nym-2026-04-07")
            # PM endDate is the settlement date (days after the game), not the game date
            game_date = _extract_game_date_from_slug(event_slug) if event_slug else None
            effective_end_date = game_date or mkt.endDate

            normalized.append(NormalizedMarket(
                platform="polymarket",
                market_id=mkt.id,
                event=mkt.event_name or mkt.question,
                market_type=pm_type,
                side=side_hint,  # team-name outcome hint for alignment, or "" for Yes/No format
                line=None,
                price=price,
                liquidity=mkt.liquidity,
                url=url,
                timestamp=mkt.endDate,
                question=mkt.question,
                end_date=effective_end_date,
                outcome_prices=outcome_prices,
                event_slug=event_slug,
                fetched_at=fetch_ts,
            ))

        logger.info(
            "PolymarketAdapter: %d raw → %d parsed → %d normalized · dropped: %s",
            len(raw_markets), len(markets), len(normalized), self._dropped_by_type,
        )
        return normalized

    @property
    def dropped_by_type(self) -> dict[str, int]:
        """Market types dropped during the last fetch (for diagnostics)."""
        return getattr(self, "_dropped_by_type", {})
