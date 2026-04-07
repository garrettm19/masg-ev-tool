"""
Polymarket adapter — fetches tennis markets from the Gamma API and
normalizes them into NormalizedMarket objects.

Only h2h (moneyline / match-winner) markets are emitted.  Outright futures,
handicaps, totals, and first-set markets are classified and dropped here
so the downstream matcher and engine never see them.
"""
import logging

from models.market import Market
from services.events import fetch_markets_by_tags
from services.sports_config import all_pm_tags
from services.adapters.base import NormalizedMarket

logger = logging.getLogger(__name__)


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

            # H2H only — handicap/totals disabled (illiquid PM markets + secondary
            # bookmaker odds produce unreliable edge calculations)
            if pm_type != "h2h":
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

            event_slug = mkt.event_slug
            url = f"https://polymarket.com/event/{event_slug}" if event_slug else None

            normalized.append(NormalizedMarket(
                platform="polymarket",
                market_id=mkt.id,
                event=mkt.event_name or mkt.question,
                market_type=pm_type,
                side="",  # determined later by outcome alignment
                line=None,
                price=price,
                liquidity=mkt.liquidity,
                url=url,
                timestamp=mkt.endDate,
                question=mkt.question,
                end_date=mkt.endDate,
                outcome_prices=mkt.outcomePrices,
                event_slug=event_slug,
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
