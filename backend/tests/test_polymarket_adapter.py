"""
Tests for services.adapters.polymarket.

Covers:
  - outcome_prices ordering: Yes/No, No/Yes, team-name outcomes
  - side hint set for team-name outcomes
  - game-date extraction from slug
  - draw/futures/prop markets dropped by adapter
"""
import asyncio
import json

import pytest
from unittest.mock import patch, AsyncMock

from models.market import Market
from services.adapters.polymarket import PolymarketAdapter, _extract_game_date_from_slug, _is_game_date_past


def _make_market(
    outcomes: list[str] | None = None,
    outcome_prices: list[str] | None = None,
) -> Market:
    raw_outcomes = json.dumps(outcomes) if outcomes else json.dumps(["Yes", "No"])
    raw_prices = json.dumps(outcome_prices) if outcome_prices else json.dumps(["0.65", "0.35"])
    return Market(
        id="m1",
        question="Will Alcaraz beat Sinner?",
        outcomes=raw_outcomes,
        outcomePrices=raw_prices,
        category="tennis",
        liquidity=5000.0,
        endDate="2026-06-01T18:00:00Z",
        active=True,
        closed=False,
        slug="test",
        event_slug="test-event",
        event_name="Alcaraz vs Sinner",
    )


class TestOutcomePricesOrdering:
    @patch("services.adapters.polymarket.all_pm_tags", return_value=["tennis"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_normal_yes_no_ordering(self, mock_fetch, mock_tags):
        """Standard [Yes, No] ordering passes through unchanged."""
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.65", "0.35"])
        # Return raw dicts that Market(**raw) will parse
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].outcome_prices == ["0.65", "0.35"]
        assert markets[0].price == 0.65

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["tennis"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_reversed_no_yes_ordering_swapped(self, mock_fetch, mock_tags):
        """Reversed [No, Yes] outcomes → prices swapped to [Yes, No]."""
        mkt = _make_market(outcomes=["No", "Yes"], outcome_prices=["0.35", "0.65"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].outcome_prices == ["0.65", "0.35"]
        assert markets[0].price == 0.65

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["tennis"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_missing_outcomes_field_unchanged(self, mock_fetch, mock_tags):
        """If outcomes field is None, prices pass through as-is."""
        mkt = _make_market(outcome_prices=["0.60", "0.40"])
        raw = mkt.model_dump()
        raw["outcomes"] = None
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].outcome_prices == ["0.60", "0.40"]


# ---------------------------------------------------------------------------
# Team-name outcomes (the root cause of MLB/NBA false positives)
# ---------------------------------------------------------------------------

class TestTeamNameOutcomes:
    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_team_name_outcomes_set_side_hint(self, mock_fetch, mock_tags):
        """outcomes=['Athletics','New York Yankees'] → side='Athletics', prices unchanged."""
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
        assert markets[0].outcome_prices == ["0.365", "0.635"]

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_yes_no_outcomes_no_side_hint(self, mock_fetch, mock_tags):
        """outcomes=['Yes','No'] → side remains empty (positional parsing used)."""
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.55", "0.45"])
        mock_fetch.return_value = [mkt.model_dump()]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 1
        assert markets[0].side == ""

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["basketball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_short_team_names(self, mock_fetch, mock_tags):
        """outcomes=['Nets','Bucks'] → side='Nets' (team-name, not Yes/No)."""
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
    def test_adapter_uses_slug_date_as_end_date(self, mock_fetch, mock_tags):
        """end_date should be the game date from slug, not the settlement endDate."""
        mkt = _make_market(outcomes=["Team A", "Team B"], outcome_prices=["0.50", "0.50"])
        raw = mkt.model_dump()
        raw["question"] = "Team A vs. Team B"
        raw["endDate"] = "2099-04-14T23:10:00Z"  # settlement date (7 days after game)
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
        """A game date in the past should return True."""
        assert _is_game_date_past("mlb-ari-nym-2020-01-01") is True

    def test_future_date_not_detected(self):
        """A game date in the future should return False."""
        assert _is_game_date_past("mlb-ari-nym-2099-12-31") is False

    def test_no_date_in_slug(self):
        """No date in slug → not past (safe default)."""
        assert _is_game_date_past("some-event") is False

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_past_game_dropped_by_adapter(self, mock_fetch, mock_tags):
        """Market for a game in the past should be dropped."""
        mkt = _make_market(
            outcomes=["Los Angeles Dodgers", "Toronto Blue Jays"],
            outcome_prices=["0.915", "0.085"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Los Angeles Dodgers vs. Toronto Blue Jays"
        raw["event_slug"] = "mlb-lad-tor-2020-04-07"  # past date
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        with patch("services.matcher.classify_pm_market_type", return_value="h2h"):
            markets = asyncio.run(adapter.fetch_markets())

        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_future_game_passes_adapter(self, mock_fetch, mock_tags):
        """Market for a game in the future should pass through."""
        mkt = _make_market(
            outcomes=["Los Angeles Dodgers", "Toronto Blue Jays"],
            outcome_prices=["0.585", "0.415"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Los Angeles Dodgers vs. Toronto Blue Jays"
        raw["event_slug"] = "mlb-lad-tor-2099-04-08"  # future date
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
    def test_draw_market_dropped(self, mock_fetch, mock_tags):
        """'Will X vs Y end in a draw?' classified as prop, dropped."""
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.22", "0.78"])
        raw = mkt.model_dump()
        raw["question"] = "Will Chicago Fire FC vs. Atlanta United FC end in a draw?"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["soccer"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_mls_cup_futures_dropped(self, mock_fetch, mock_tags):
        """'Will X win the 2026 MLS Cup?' classified as outright, dropped."""
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.18", "0.82"])
        raw = mkt.model_dump()
        raw["question"] = "Will Inter Miami CF win the 2026 MLS Cup?"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_world_series_futures_dropped(self, mock_fetch, mock_tags):
        """'Will X win the 2026 World Series?' classified as outright, dropped."""
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.0035", "0.9965"])
        raw = mkt.model_dump()
        raw["question"] = "Will the Chicago White Sox win the 2026 World Series?"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_first_inning_prop_dropped(self, mock_fetch, mock_tags):
        """'Will there be a run in the first inning?' classified as prop, dropped."""
        mkt = _make_market(outcomes=["Yes Run", "No Run"], outcome_prices=["0.505", "0.495"])
        raw = mkt.model_dump()
        raw["question"] = "Will there be a run scored in the first inning?: Athletics vs. New York Yankees"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["soccer"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_both_teams_to_score_dropped(self, mock_fetch, mock_tags):
        """'Both Teams to Score' classified as prop, dropped."""
        mkt = _make_market(outcomes=["Yes", "No"], outcome_prices=["0.50", "0.50"])
        raw = mkt.model_dump()
        raw["question"] = "Sydney FC vs. Auckland FC: Both Teams to Score"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()
        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 0

    @patch("services.adapters.polymarket.all_pm_tags", return_value=["baseball"])
    @patch("services.adapters.polymarket.fetch_markets_by_tags", new_callable=AsyncMock)
    def test_real_h2h_passes(self, mock_fetch, mock_tags):
        """'Athletics vs. New York Yankees' with team outcomes passes through."""
        mkt = _make_market(
            outcomes=["Athletics", "New York Yankees"],
            outcome_prices=["0.365", "0.635"],
        )
        raw = mkt.model_dump()
        raw["question"] = "Athletics vs. New York Yankees"
        raw["event_slug"] = "mlb-oak-nyy-2026-12-31"
        mock_fetch.return_value = [raw]
        adapter = PolymarketAdapter()

        markets = asyncio.run(adapter.fetch_markets())
        assert len(markets) == 1
        assert markets[0].side == "Athletics"
