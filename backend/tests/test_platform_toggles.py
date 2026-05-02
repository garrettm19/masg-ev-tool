"""
Pipeline-integration tests for backend platform scan toggles.

Verifies that ScanConfig.platforms gates which adapters fetch_opportunities
invokes:
  - Default ScanConfig: Kalshi runs, Polymarket does not.
  - Polymarket toggled on: both run.
  - Both disabled: neither runs; pipeline returns empty safely.
  - Explicit `adapters=` argument bypasses the toggle (for tests / internal callers).
"""
import asyncio
from unittest.mock import patch, AsyncMock

import pytest

from services.opportunities import fetch_opportunities, DEFAULT_ADAPTERS
from services.scan_config import (
    reset_scan_config,
    update_scan_config,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_scan_config()
    yield
    reset_scan_config()


def _patch_external_io(odds_events=None):
    """Context-manager bundle that stubs the I/O dependencies of the pipeline
    so the test runs offline. Returns the patches as already-entered context
    managers; callers chain with ExitStack."""
    odds_events = odds_events or []

    async def _mock_fetch_odds(**kwargs):
        return odds_events, {"quota_remaining": "999"}

    return patch("services.opportunities.fetch_odds", side_effect=_mock_fetch_odds)


class TestDefaultPlatformGating:
    def test_polymarket_adapter_not_invoked_by_default(self):
        """Default ScanConfig has polymarket.enabled=False — fetch_opportunities
        must skip PolymarketAdapter.fetch_markets entirely."""
        async def run():
            with patch.object(
                type(next(a for a in DEFAULT_ADAPTERS if a.platform_name == "polymarket")),
                "fetch_markets",
                new_callable=AsyncMock,
                return_value=[],
            ) as pm_mock, patch.object(
                type(next(a for a in DEFAULT_ADAPTERS if a.platform_name == "kalshi")),
                "fetch_markets",
                new_callable=AsyncMock,
                return_value=[],
            ) as kl_mock, _patch_external_io():
                opps, meta = await fetch_opportunities()
            return opps, meta, pm_mock, kl_mock

        opps, meta, pm_mock, kl_mock = asyncio.run(run())

        pm_mock.assert_not_called()
        kl_mock.assert_called_once()
        # platforms_fetched reflects only the adapters that actually ran
        assert "polymarket" not in meta["platforms_fetched"]
        assert "kalshi" in meta["platforms_fetched"]


class TestPolymarketEnabledRunsBoth:
    def test_both_adapters_called_when_polymarket_enabled(self):
        update_scan_config({"platforms": {"polymarket": {"enabled": True}}})

        async def run():
            with patch.object(
                type(next(a for a in DEFAULT_ADAPTERS if a.platform_name == "polymarket")),
                "fetch_markets",
                new_callable=AsyncMock,
                return_value=[],
            ) as pm_mock, patch.object(
                type(next(a for a in DEFAULT_ADAPTERS if a.platform_name == "kalshi")),
                "fetch_markets",
                new_callable=AsyncMock,
                return_value=[],
            ) as kl_mock, _patch_external_io():
                opps, meta = await fetch_opportunities()
            return opps, meta, pm_mock, kl_mock

        opps, meta, pm_mock, kl_mock = asyncio.run(run())

        pm_mock.assert_called_once()
        kl_mock.assert_called_once()
        assert set(meta["platforms_fetched"]) == {"polymarket", "kalshi"}


class TestBothDisabledRunsNothing:
    def test_no_adapters_called_when_both_disabled_returns_empty(self):
        update_scan_config({
            "platforms": {
                "kalshi": {"enabled": False},
                "polymarket": {"enabled": False},
            }
        })

        async def run():
            with patch.object(
                type(next(a for a in DEFAULT_ADAPTERS if a.platform_name == "polymarket")),
                "fetch_markets",
                new_callable=AsyncMock,
                return_value=[],
            ) as pm_mock, patch.object(
                type(next(a for a in DEFAULT_ADAPTERS if a.platform_name == "kalshi")),
                "fetch_markets",
                new_callable=AsyncMock,
                return_value=[],
            ) as kl_mock, _patch_external_io():
                opps, meta = await fetch_opportunities()
            return opps, meta, pm_mock, kl_mock

        opps, meta, pm_mock, kl_mock = asyncio.run(run())

        pm_mock.assert_not_called()
        kl_mock.assert_not_called()
        assert opps == []
        assert meta["platforms_fetched"] == []


class TestExplicitAdaptersArgumentBypassesToggle:
    def test_explicit_adapters_argument_overrides_scan_config(self):
        """When a caller passes `adapters=[...]` explicitly (tests, internal
        callers), ScanConfig.platforms is NOT consulted — the caller has
        full control. Default config has Polymarket disabled, but an
        explicit adapter list still runs."""
        from services.adapters import PolymarketAdapter

        explicit_pm = PolymarketAdapter()

        async def run():
            with patch.object(
                PolymarketAdapter,
                "fetch_markets",
                new_callable=AsyncMock,
                return_value=[],
            ) as pm_mock, _patch_external_io():
                opps, meta = await fetch_opportunities(adapters=[explicit_pm])
            return opps, meta, pm_mock

        opps, meta, pm_mock = asyncio.run(run())
        # Despite default ScanConfig disabling Polymarket, the explicit
        # adapter list was honored.
        pm_mock.assert_called_once()
        assert meta["platforms_fetched"] == ["polymarket"]
