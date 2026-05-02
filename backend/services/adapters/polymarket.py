"""
Polymarket adapter — Gamma for discovery, CLOB for live pricing.

Gamma `/events` provides discovery and metadata: outcomes, clobTokenIds,
slug/date, acceptingOrders.  Gamma's outcomePrices is metadata (last-trade
or default 0.5/0.5 for untraded markets) and is used only as a coarse
sanity prefilter — never as the final price.

After classification and prefilters survive, we hydrate the live CLOB
order book for each candidate's index-0 and index-1 token IDs in a single
batched call.  The emitted price is the best ask of the index-0 token —
the side the engine will price against FanDuel.

Only h2h (moneyline / match-winner) and totals markets are emitted.
"""
import logging
import time

from models.market import Market
from services.events import fetch_markets_by_tags
from services.sports_config import all_pm_tags
from services.adapters.base import NormalizedMarket
from services.clob_polymarket import fetch_books

logger = logging.getLogger(__name__)


# Bid-ask spread tighter than this (in dollars) is acceptable for size.
# Wider spreads on Polymarket usually mean a thin or one-sided book.
_MAX_BID_ASK_SPREAD = 0.05


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


def _is_game_date_past(slug: str, now=None) -> bool:
    """
    Check if the game date extracted from the slug is more than 24 hours
    in the past.

    Polymarket slugs encode the U.S. calendar date of the game, not the
    exact UTC start time.  Late-evening U.S. games (e.g., NBA Sunday-night
    tip-off at 9:30 PM ET) start AFTER UTC midnight of the slug day, so a
    naive `game_date < now` test would mark a not-yet-started game as
    "past" during the most actionable pre-game window.

    Adding a 24-hour grace window keeps obviously stale markets filtered
    while letting late-evening U.S. games survive until the CLOB
    book / acceptingOrders filters can drop them after settlement.

    `now` may be supplied for deterministic tests; defaults to the current
    UTC time. Returns False if no date in slug.
    """
    from datetime import datetime, timedelta, timezone
    game_date_str = _extract_game_date_from_slug(slug)
    if not game_date_str:
        return False
    try:
        game_date = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
        if now is None:
            now = datetime.now(timezone.utc)
        return game_date < now - timedelta(hours=24)
    except (ValueError, AttributeError):
        return False


class PolymarketAdapter:
    platform_name: str = "polymarket"

    async def fetch_markets(self) -> list[NormalizedMarket]:
        """
        Fetch active Polymarket markets, classify each by market type, and
        return only h2h/totals markets priced from the live CLOB book.
        """
        # Imported here to avoid circular import (matcher → adapters.base → adapters → polymarket → matcher)
        from services.matcher import classify_pm_market_type

        tags = all_pm_tags()
        raw_markets = await fetch_markets_by_tags(tags, limit=500)

        markets: list[Market] = []
        for raw in raw_markets:
            try:
                markets.append(Market(**raw))
            except Exception:
                pass

        self._dropped_by_type: dict[str, int] = {}
        candidates: list[dict] = []

        # ---- Pass 1: classify, prefilter, swap, collect candidates ---------
        for mkt in markets:
            pm_type = classify_pm_market_type(mkt.question)
            if pm_type not in ("h2h", "totals"):
                self._dropped_by_type[pm_type] = self._dropped_by_type.get(pm_type, 0) + 1
                continue

            # Gamma flag: market explicitly paused. Drop before any pricing work.
            if mkt.acceptingOrders is False:
                continue

            # Live CLOB pricing requires the per-side asset IDs.
            if not mkt.clobTokenIds or len(mkt.clobTokenIds) < 2:
                continue

            # Coarse Gamma sanity prefilter — does NOT determine the final price.
            if not mkt.outcomePrices or len(mkt.outcomePrices) < 2:
                continue
            try:
                gamma_price = float(mkt.outcomePrices[0])
            except (ValueError, TypeError):
                continue
            if gamma_price <= 0.02 or gamma_price >= 0.98:
                continue

            outcome_prices = list(mkt.outcomePrices)
            clob_token_ids = list(mkt.clobTokenIds)
            side_hint = ""
            if mkt.outcomes and len(mkt.outcomes) >= 2:
                o0 = mkt.outcomes[0].lower().strip()
                o1 = mkt.outcomes[1].lower().strip()
                if o0 == "no":
                    # Format 1 reversed: [No,Yes] → [Yes,No].  Swap prices AND
                    # token IDs together so index 0 maps to YES on both arrays.
                    outcome_prices = [outcome_prices[1], outcome_prices[0]]
                    clob_token_ids = [clob_token_ids[1], clob_token_ids[0]]
                elif o0 != "yes" and o1 != "yes":
                    # Format 2: team-name (or Over/Under) outcomes.  No swap;
                    # index 0 corresponds to the engine's primary side.
                    side_hint = mkt.outcomes[0]

            event_slug = mkt.event_slug
            if event_slug and _is_game_date_past(event_slug):
                continue

            game_date = _extract_game_date_from_slug(event_slug) if event_slug else None
            effective_end_date = game_date or mkt.endDate

            candidates.append({
                "mkt": mkt,
                "pm_type": pm_type,
                "outcome_prices": outcome_prices,
                "clob_token_ids": clob_token_ids,
                "side_hint": side_hint,
                "event_slug": event_slug,
                "effective_end_date": effective_end_date,
            })

        # ---- Pass 2: batch-fetch live CLOB books for surviving candidates --
        unique_tokens: list[str] = []
        seen: set[str] = set()
        for c in candidates:
            for tid in c["clob_token_ids"][:2]:
                if tid and tid not in seen:
                    seen.add(tid)
                    unique_tokens.append(tid)

        books = await fetch_books(unique_tokens) if unique_tokens else {}
        fetch_ts = time.time()

        normalized: list[NormalizedMarket] = []
        for c in candidates:
            tok_yes = c["clob_token_ids"][0]
            tok_no = c["clob_token_ids"][1]

            book_yes = books.get(tok_yes)
            if book_yes is None:
                continue
            if not book_yes.asks or not book_yes.bids:
                continue

            best_ask = book_yes.asks[0].price
            best_bid = book_yes.bids[0].price

            if not (0.02 < best_ask < 0.98):
                continue
            if not (0.02 < best_bid < 0.98):
                continue
            spread = best_ask - best_bid
            # Round to 4 decimals before threshold check — Polymarket prices
            # are quoted to 1¢, so float subtraction artifacts shouldn't push
            # an at-threshold spread over the line.
            if round(spread, 4) > _MAX_BID_ASK_SPREAD:
                continue

            # Live outcome_prices for both sides when both books are available.
            # Falls back to swapped Gamma values for observability only when the
            # NO-side book is missing — never used for pricing.
            book_no = books.get(tok_no)
            if book_no is not None and book_no.asks:
                live_outcome_prices = [
                    f"{best_ask:.4f}",
                    f"{book_no.asks[0].price:.4f}",
                ]
            else:
                live_outcome_prices = c["outcome_prices"]

            mkt = c["mkt"]
            url = f"https://polymarket.com/event/{c['event_slug']}" if c["event_slug"] else None

            normalized.append(NormalizedMarket(
                platform="polymarket",
                market_id=mkt.id,
                event=mkt.event_name or mkt.question,
                market_type=c["pm_type"],
                side=c["side_hint"],
                line=None,
                price=best_ask,
                liquidity=mkt.liquidity,
                url=url,
                timestamp=mkt.endDate,
                question=mkt.question,
                end_date=c["effective_end_date"],
                outcome_prices=live_outcome_prices,
                event_slug=c["event_slug"],
                bid_ask_spread=spread,
                fetched_at=fetch_ts,
            ))

        logger.info(
            "PolymarketAdapter: %d raw → %d parsed → %d candidates → %d normalized · dropped: %s",
            len(raw_markets), len(markets), len(candidates), len(normalized), self._dropped_by_type,
        )
        return normalized

    @property
    def dropped_by_type(self) -> dict[str, int]:
        """Market types dropped during the last fetch (for diagnostics)."""
        return getattr(self, "_dropped_by_type", {})
