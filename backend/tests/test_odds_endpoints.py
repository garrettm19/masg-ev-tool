"""
Smoke tests for the legacy /api/odds router.

The legacy odds router is tennis-only and not used by the dashboard; it
exists for debugging.  These tests pin the response contract and guard
against regressions in the response-construction code paths — in
particular the GET /api/odds/matches builder, which previously
referenced an out-of-scope variable (`markets`) and raised NameError
on every call.

External fetchers are monkeypatched so the tests don't hit the real
Odds API or Polymarket Gamma API.
"""
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


class TestOddsMatchesEndpoint:
    """GET /api/odds/matches — guards against NameError regression."""

    def test_returns_200_with_empty_inputs(self) -> None:
        """Empty inputs must build a valid response (no NameError)."""
        with patch(
            "routers.odds.fetch_tennis_markets",
            new=AsyncMock(return_value=[]),
        ), patch(
            "routers.odds.fetch_tennis_odds",
            new=AsyncMock(return_value=([], {"quota_remaining": "100"})),
        ):
            resp = client.get("/api/odds/matches")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["matches"] == []
        assert body["total"] == 0
        assert body["markets_searched"] == 0
        assert body["events_searched"] == 0
        assert body["quota_remaining"] == "100"

    def test_markets_searched_counts_normalized_markets(self) -> None:
        """
        markets_searched should reflect the count of NormalizedMarket
        objects passed to the matcher — i.e. raw markets that classified
        as h2h with parseable prices, not the raw API count.
        """
        # Two raw markets: one valid h2h, one outright (will be filtered out).
        raw_markets = [
            {
                "id": "pm1",
                "question": "Will Alcaraz beat Sinner?",
                "outcomes": ["Yes", "No"],
                "outcomePrices": ["0.55", "0.45"],
                "endDate": "2026-06-01T12:00:00Z",
                "event_slug": "alcaraz-vs-sinner",
                "event_name": "Alcaraz vs Sinner",
            },
            {
                # Outright — classify_pm_market_type drops this
                "id": "pm2",
                "question": "Will Alcaraz win the 2026 French Open?",
                "outcomes": ["Yes", "No"],
                "outcomePrices": ["0.30", "0.70"],
                "endDate": "2026-06-15T12:00:00Z",
                "event_slug": "alcaraz-fo-2026",
                "event_name": "French Open Winner",
            },
        ]

        with patch(
            "routers.odds.fetch_tennis_markets",
            new=AsyncMock(return_value=raw_markets),
        ), patch(
            "routers.odds.fetch_tennis_odds",
            new=AsyncMock(return_value=([], {"quota_remaining": "99"})),
        ):
            resp = client.get("/api/odds/matches")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Only the h2h market survives normalization
        assert body["markets_searched"] == 1
        assert body["events_searched"] == 0
