"""
Tests for services.adapters.polymarket.

Covers:
  - outcome_prices ordering: Yes/No, No/Yes, team-name outcomes
  - side hint set for team-name outcomes
  - game-date extraction from slug
  - draw/futures/prop markets dropped by adapter
  - CLOB pricing: best ask used, swap maps tokens, spread populated, drop on
    missing book / empty book / wide spread / acceptingOrders=False
"""
import asyncio
import json

import pytest
from unittest.mock import patch, AsyncMock

from models.market import Market
from services.adapters.polymarket import PolymarketAdapter, _extract_game_date_from_slug, _is_game_date_past
from services.clob_polymarket import BookLevel, OrderBook


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_market(
    outcomes: list[str] | None = None,
    outcome_prices: list[str] | None = None,
    clob_token_ids: list[str] | None = None,
) -> Market:
    raw_outcomes = json.dumps(outcomes) if outcomes else json.dumps(["Yes", "No"])
    raw_prices = json.dumps(outcome_prices) if outcome_prices else json.dumps(["0.65", "0.35"])
    raw_tokens = json.dumps(clob_token_ids) if clob_token_ids else json.dumps(["tok_a", "tok_b"])
    return Market(
        id="m1",
        question="Will Alcaraz beat Sinner?",
        outcomes=raw_outcomes,
        outcomePrices=raw_prices,
        clobTokenIds=raw_tokens,
        category="tennis",
        liquidity=5000.0,
        endDate="2026-06-01T18:00:00Z",
        active=True,
        closed=False,
        slug="test",
        event_slug="test-event",
        event_name="Alcaraz vs Sinner",
    )


def _book(token_id: str, best_ask: float, best_bid: float, size: float = 100.0) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=[BookLevel(price=best_bid, size=size)],
        asks=[BookLevel(price=best_ask, size=size)],
    )


def _default_books(
    tokens: tuple[str, str] = ("tok_a", "tok_b"),
    asks: tuple[float, float] = (0.55, 0.45),
    bids: tuple[float, float] = (0.52, 0.42),
) -> dict[str, OrderBook]:
    """Distinct asks per token so swap behavior is observable in assertions."""
    return {
        tokens[0]: _book(tokens[0], asks[0], bids[0]),
        tokens[1]: _book(tokens[1], asks[1], bids[1]),
    }


# ---------------------------------------------------------------------------
# outcome_prices / clob_token_ids ordering and swap
# ---------------------------------------------------------------------------

class TestOutcomePricesOrdering:
    @patch("services.adapters.polymarket.all_pm_tags", return_value=["tennis"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_normal_yes_no_uses_yes_token_best_ask(self, mock_books, mock_fetch, mock_tags):
        """Yes/No format → no swap → price = best ask of clobTokenIds[0]."""
        mock_books.return_value = _default_books()
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.65", "0.35"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        # tok_a is the YES side; default best ask there is 0.55
        assert markets[0].price == pytest.approx(0.55)
        assert markets[0].bid_ask_spread == pytest.approx(0.03)

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["tennis"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_reversed_no_yes_swaps_clob_token_ids(self, mock_books, mock_fetch, mock_tags):
        """[No,Yes] → swap prices AND token IDs together; pricing uses tok_b."""
        mock_books.return_value = _default_books()
        mkt = _make_market(outcomes=["No", "Yes"], outcome_prices=["0.35", "0.65"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        # After swap, index 0 is tok_b (the original YES token); tok_b ask = 0.45
        assert markets[0].price == pytest.approx(0.45)
        assert markets[0].bid_ask_spread == pytest.approx(0.03)

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["tennis"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_missing_outcomes_field_uses_index_0_token(self, mock_books, mock_fetch, mock_tags):
        """If outcomes is None, no swap is attempted; index 0 token is used."""
        mock_books.return_value = _default_books()
        mkt = _make_market(outcome_prices=["0.60", "0.40"])
        raw = mkt.model_dump()
        raw["outcomes"] = None
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].price == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# Team-name outcomes (root cause of MLB/NBA false positives)
# ---------------------------------------------------------------------------

class TestTeamNameOutcomes:
    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_team_name_outcomes_set_side_hint(self, mock_books, mock_fetch, mock_tags):
        """Team-name format → side_hint=first team, no swap, price=index-0 ask."""
        mock_books.return_value = _default_books()
        mkt = _make_market(
            outcomes=["Athletics", "New York Yankees"],
            outcome_prices=["0.365", "0.635"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Athletics vs. New York Yankees"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].side == "Athletics"
        assert markets[0].price == pytest.approx(0.55)  # tok_a (Athletics)

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_yes_no_outcomes_no_side_hint(self, mock_books, mock_fetch, mock_tags):
        """outcomes=['Yes','No'] → side_hint stays empty (positional parsing)."""
        mock_books.return_value = _default_books()
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.55", "0.45"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].side == ""

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_short_team_names(self, mock_books, mock_fetch, mock_tags):
        """outcomes=['Nets','Bucks'] → side_hint='Nets'."""
        mock_books.return_value = _default_books()
        mkt = _make_market(
            outcomes=["Nets", "Bucks"],
            outcome_prices=["0.45", "0.55"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Nets vs. Bucks"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].side == "Nets"


# ---------------------------------------------------------------------------
# Game-date extraction from slug
# ---------------------------------------------------------------------------

class TestGameDateExtraction:
    def test_mlb_slug(self):
        assert _extract_game_date_from_slug("mlb-ari-nym-2026-04-07") == "2026-04-07T23:59:00Z"

    def test_nhl_slug(self):
        assert _extract_game_date_from_slug("nhl-nsh-ana-2026-04-16") == "2026-04-16T23:59:00Z"

    def test_no_date_in_slug(self):
        assert _extract_game_date_from_slug("some-event-slug") is None

    def test_empty_slug(self):
        assert _extract_game_date_from_slug("") is None

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_adapter_uses_slug_date_as_end_date(self, mock_books, mock_fetch, mock_tags):
        """end_date should be the game date from slug, not the settlement endDate."""
        mock_books.return_value = _default_books()
        mkt = _make_market(outcomes=["Team A", "Team B"], outcome_prices=["0.55", "0.45"])
        raw = mkt.model_dump()
        raw["question"] = "Team A vs. Team B"
        raw["endDate"] = "2099-04-14T23:10:00Z"  # settlement date
        raw["event_slug"] = "mlb-ta-tb-2099-04-07"  # game date
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].end_date == "2099-04-07T23:59:00Z"  # game date, not settlement


# ---------------------------------------------------------------------------
# Live/completed game filtering
# ---------------------------------------------------------------------------

class TestLiveGameFiltering:
    def test_past_date_detected(self):
        assert _is_game_date_past("mlb-ari-nym-2020-01-01") is True

    def test_future_date_not_detected(self):
        assert _is_game_date_past("mlb-ari-nym-2099-12-31") is False

    def test_no_date_in_slug(self):
        assert _is_game_date_past("some-event") is False

    # ---- 24-hour grace window (deterministic, fixed `now`) -----------------

    def test_late_evening_us_game_not_past_before_tipoff(self):
        """NBA Sunday-night game on slug 2026-05-04 (tip-off May 5 01:30 UTC).
        At 2026-05-05T00:30Z (May 4 8:30 PM ET, BEFORE tip-off), the slug
        date must NOT be considered past."""
        from datetime import datetime, timezone
        now = datetime(2026, 5, 5, 0, 30, tzinfo=timezone.utc)
        assert _is_game_date_past("nba-min-sas-2026-05-04", now=now) is False

    def test_late_evening_us_game_not_past_during_game(self):
        """At 2026-05-05T03:00Z (May 4 11:00 PM ET, mid-game), slug
        2026-05-04 is still inside the 24h grace window."""
        from datetime import datetime, timezone
        now = datetime(2026, 5, 5, 3, 0, tzinfo=timezone.utc)
        assert _is_game_date_past("nba-min-sas-2026-05-04", now=now) is False

    def test_today_afternoon_game_not_past(self):
        """A game scheduled for today (slug 2026-05-05) at any time during
        the same UTC day must not be classified past."""
        from datetime import datetime, timezone
        now = datetime(2026, 5, 5, 18, 0, tzinfo=timezone.utc)
        assert _is_game_date_past("nba-bos-mia-2026-05-05", now=now) is False

    def test_yesterday_within_24h_grace_not_past(self):
        """Slug 2026-05-04 (T23:59Z anchor) is 12.5h before now=2026-05-05T12:30Z;
        within the 24h grace, so NOT past. Lets settlement-window markets
        survive until CLOB / acceptingOrders catches them."""
        from datetime import datetime, timezone
        now = datetime(2026, 5, 5, 12, 30, tzinfo=timezone.utc)
        assert _is_game_date_past("nba-bos-mia-2026-05-04", now=now) is False

    def test_two_day_old_slug_is_past(self):
        """Slug 2026-05-03 vs now=2026-05-05T12:30Z is ~36h after T23:59Z anchor;
        beyond the 24h grace → past."""
        from datetime import datetime, timezone
        now = datetime(2026, 5, 5, 12, 30, tzinfo=timezone.utc)
        assert _is_game_date_past("nba-bos-mia-2026-05-03", now=now) is True

    def test_just_past_24h_grace_is_past(self):
        """Boundary: anchor T23:59Z May 4 + 24h = T23:59Z May 5; at
        T00:00Z May 6 (1 minute after), slug 2026-05-04 flips to past."""
        from datetime import datetime, timezone
        now = datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc)
        assert _is_game_date_past("nba-bos-mia-2026-05-04", now=now) is True

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_past_game_dropped_by_adapter(self, mock_books, mock_fetch, mock_tags):
        """Market for a game in the past should be dropped before CLOB."""
        mock_books.return_value = _default_books()
        mkt = _make_market(
            outcomes=["Los Angeles Dodgers", "Toronto Blue Jays"],
            outcome_prices=["0.915", "0.085"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Los Angeles Dodgers vs. Toronto Blue Jays"
        raw["event_slug"] = "mlb-lad-tor-2020-04-07"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_future_game_passes_adapter(self, mock_books, mock_fetch, mock_tags):
        """Market for a game in the future should pass through."""
        mock_books.return_value = _default_books()
        mkt = _make_market(
            outcomes=["Los Angeles Dodgers", "Toronto Blue Jays"],
            outcome_prices=["0.585", "0.415"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Los Angeles Dodgers vs. Toronto Blue Jays"
        raw["event_slug"] = "mlb-lad-tor-2099-04-08"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1


# ---------------------------------------------------------------------------
# Draw / futures / prop markets dropped by adapter
# ---------------------------------------------------------------------------

class TestAdapterDropsNonH2H:
    @patch("services.adapters.polymarket.all_pm_tags", return_value=["soccer"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_draw_market_dropped(self, mock_books, mock_fetch, mock_tags):
        mock_books.return_value = {}
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.22", "0.78"])
        raw = mkt.model_dump()
        raw["question"] = "Will Chicago Fire FC vs. Atlanta United FC end in a draw?"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["soccer"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_mls_cup_futures_dropped(self, mock_books, mock_fetch, mock_tags):
        mock_books.return_value = {}
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.18", "0.82"])
        raw = mkt.model_dump()
        raw["question"] = "Will Inter Miami CF win the 2026 MLS Cup?"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_world_series_futures_dropped(self, mock_books, mock_fetch, mock_tags):
        mock_books.return_value = {}
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.0035", "0.9965"])
        raw = mkt.model_dump()
        raw["question"] = "Will the Chicago White Sox win the 2026 World Series?"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_first_inning_prop_dropped(self, mock_books, mock_fetch, mock_tags):
        mock_books.return_value = {}
        mkt = _make_market(outcomes=["Yes Run", "No Run"], outcome_prices=["0.505", "0.495"])
        raw = mkt.model_dump()
        raw["question"] = "Will there be a run scored in the first inning?: Athletics vs. New York Yankees"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["soccer"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_both_teams_to_score_dropped(self, mock_books, mock_fetch, mock_tags):
        mock_books.return_value = {}
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.50", "0.50"])
        raw = mkt.model_dump()
        raw["question"] = "Sydney FC vs. Auckland FC: Both Teams to Score"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_real_h2h_passes(self, mock_books, mock_fetch, mock_tags):
        mock_books.return_value = _default_books()
        mkt = _make_market(
            outcomes=["Athletics", "New York Yankees"],
            outcome_prices=["0.365", "0.635"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Athletics vs. New York Yankees"
        raw["event_slug"] = "mlb-oak-nyy-2099-12-31"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 1
        assert markets[0].side == "Athletics"
        assert markets[0].price == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# CLOB live pricing — drops, swaps, spread, dedup
# ---------------------------------------------------------------------------

class TestClobPricing:
    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_totals_over_under_uses_over_token(self, mock_books, mock_fetch, mock_tags):
        """Over/Under totals → side_hint='Over', price = book(over_token).asks[0]."""
        mock_books.return_value = {
            "tok_over": _book("tok_over", best_ask=0.48, best_bid=0.46),
            "tok_under": _book("tok_under", best_ask=0.52, best_bid=0.50),
        }
        mkt = _make_market(
            outcomes=["Over", "Under"],
            outcome_prices=["0.50", "0.50"],
            clob_token_ids=["tok_over", "tok_under"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Lakers vs. Celtics: Over/Under 220.5"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="totals"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].side == "Over"
        assert markets[0].price == pytest.approx(0.48)
        assert markets[0].bid_ask_spread == pytest.approx(0.02)

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_gamma_5050_with_real_clob_kept_with_clob_price(self, mock_books, mock_fetch, mock_tags):
        """Stale Gamma 0.5/0.5 + real CLOB book → kept, priced from CLOB best ask."""
        mock_books.return_value = _default_books(asks=(0.32, 0.68), bids=(0.30, 0.66))
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.50", "0.50"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].price == pytest.approx(0.32)  # CLOB, not Gamma 0.5
        assert markets[0].bid_ask_spread == pytest.approx(0.02)

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_gamma_non_50_with_missing_clob_book_dropped(self, mock_books, mock_fetch, mock_tags):
        """Non-stale Gamma price but no CLOB book → DROP (no fallback to Gamma)."""
        mock_books.return_value = {}  # no books returned for any token
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.42", "0.58"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_accepting_orders_false_dropped_before_pricing(self, mock_books, mock_fetch, mock_tags):
        """acceptingOrders=False → drop before any CLOB call for this market."""
        mock_books.return_value = _default_books()
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.42", "0.58"])
        raw = mkt.model_dump()
        raw["acceptingOrders"] = False
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0
        # No CLOB call needed — no surviving candidates → adapter short-circuits.
        mock_books.assert_not_called()

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_missing_clob_token_ids_dropped(self, mock_books, mock_fetch, mock_tags):
        """clobTokenIds missing → drop (cannot price live)."""
        mock_books.return_value = {}
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.42", "0.58"])
        raw = mkt.model_dump()
        raw["clobTokenIds"] = None
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_only_one_clob_token_id_dropped(self, mock_books, mock_fetch, mock_tags):
        """Fewer than 2 clobTokenIds → drop."""
        mock_books.return_value = {}
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.42", "0.58"])
        raw = mkt.model_dump()
        raw["clobTokenIds"] = ["only_one"]
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_empty_asks_dropped(self, mock_books, mock_fetch, mock_tags):
        """Book returned with empty asks (cannot buy) → drop."""
        mock_books.return_value = {
            "tok_a": OrderBook(
                token_id="tok_a",
                bids=[BookLevel(price=0.50, size=100)],
                asks=[],
            ),
            "tok_b": _book("tok_b", 0.45, 0.42),
        }
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.42", "0.58"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_empty_bids_dropped(self, mock_books, mock_fetch, mock_tags):
        """Book returned with empty bids (half-book) → drop."""
        mock_books.return_value = {
            "tok_a": OrderBook(
                token_id="tok_a",
                bids=[],
                asks=[BookLevel(price=0.55, size=100)],
            ),
            "tok_b": _book("tok_b", 0.45, 0.42),
        }
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.42", "0.58"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_wide_spread_dropped(self, mock_books, mock_fetch, mock_tags):
        """Spread > 5¢ → drop (thin / unreliable book)."""
        mock_books.return_value = {
            "tok_a": _book("tok_a", best_ask=0.55, best_bid=0.45),  # 10¢ spread
            "tok_b": _book("tok_b", best_ask=0.45, best_bid=0.42),
        }
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.50", "0.50"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_spread_at_threshold_kept(self, mock_books, mock_fetch, mock_tags):
        """Spread exactly 5¢ → kept; bid_ask_spread populated."""
        mock_books.return_value = {
            "tok_a": _book("tok_a", best_ask=0.55, best_bid=0.50),  # exactly 5¢
            "tok_b": _book("tok_b", best_ask=0.45, best_bid=0.42),
        }
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.50", "0.50"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].price == pytest.approx(0.55)
        assert markets[0].bid_ask_spread == pytest.approx(0.05)

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_normal_spread_populates_bid_ask_spread(self, mock_books, mock_fetch, mock_tags):
        """Tight spread → kept and bid_ask_spread reflects best_ask - best_bid."""
        mock_books.return_value = {
            "tok_a": _book("tok_a", best_ask=0.61, best_bid=0.59),  # 2¢
            "tok_b": _book("tok_b", best_ask=0.41, best_bid=0.39),
        }
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.60", "0.40"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].bid_ask_spread == pytest.approx(0.02)

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    @patch("services.adapters.polymarket.fetch_books", new_callable=AsyncMock)
    def test_fetch_books_called_with_deduped_token_ids(self, mock_books, mock_fetch, mock_tags):
        """Multiple candidates sharing tokens → fetch_books called with unique IDs only."""
        mock_books.return_value = {
            "tok_a": _book("tok_a", 0.55, 0.52),
            "tok_b": _book("tok_b", 0.45, 0.42),
            "tok_c": _book("tok_c", 0.30, 0.28),
        }
        # Three markets: m1 and m2 share (tok_a, tok_b); m3 uses (tok_a, tok_c)
        m1 = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.55", "0.45"],
                          clob_token_ids=["tok_a", "tok_b"]).model_dump()
        m2 = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.55", "0.45"],
                          clob_token_ids=["tok_a", "tok_b"]).model_dump()
        m2["id"] = "m2"
        m3 = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.55", "0.45"],
                          clob_token_ids=["tok_a", "tok_c"]).model_dump()
        m3["id"] = "m3"
        mock_fetch.return_value = [m1, m2, m3]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 3
        # fetch_books called once with deduped tokens — order preserved by dict.fromkeys
        mock_books.assert_called_once()
        called_with = mock_books.call_args.args[0]
        assert sorted(called_with) == sorted(["tok_a", "tok_b", "tok_c"])
        assert len(called_with) == 3  # not 6
