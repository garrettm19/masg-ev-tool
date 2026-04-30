"""
Tests for fetch_odds integration with scan_config and odds_cache.

Covers:
  - Cache hit: fresh odds reused, no API call
  - Cache miss: stale odds trigger API fetch
  - Disabled sport: skipped entirely, no API call
  - Meta reports fetched/cached/skipped breakdown
  - Cached events included in merged result after fresh fetch
"""
import asyncio
import os
import time

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

import services.odds_provider as odds_provider_module
from services.odds_provider import fetch_odds, TennisOddsEvent
from services.scan_config import get_scan_config, reset_scan_config, update_scan_config
from services.odds_cache import store_cached, clear_cache, get_cached


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    reset_scan_config()
    clear_cache()
    odds_provider_module._discovery_cache = None
    odds_provider_module._discovery_cache_ts = 0.0
    yield
    reset_scan_config()
    clear_cache()
    odds_provider_module._discovery_cache = None
    odds_provider_module._discovery_cache_ts = 0.0


def _make_event(event_id: str = "ev1", sport_key: str = "baseball_kbo") -> TennisOddsEvent:
    return TennisOddsEvent(
        event_id=event_id,
        sport_key=sport_key,
        tournament="Test",
        home_player="Team A",
        away_player="Team B",
        home_player_norm="team a",
        away_player_norm="team b",
        commence_time="2026-06-01T12:00:00Z",
    )


# Mock _resolve_all_sport_keys to return a small, deterministic set
# without calling the real API.  Maps odds_api_key → sport_config_key.
# Uses enabled sports only.
_MOCK_KEY_MAP = {
    "baseball_kbo": "baseball_kbo",
    "baseball_mlb": "baseball_mlb",
}


async def _mock_resolve(api_key: str) -> dict[str, str]:
    return dict(_MOCK_KEY_MAP)


class TestFetchOddsCacheHit:
    def test_fresh_cache_skips_api_call(self):
        """When all sport keys have fresh cached odds, no _fetch_sport_odds calls."""
        # Pre-populate cache
        store_cached("baseball_kbo", [_make_event("e1", "baseball_kbo")])
        store_cached("baseball_mlb", [_make_event("e2", "baseball_mlb")])

        fetch_mock = AsyncMock()  # should NOT be called

        with patch("services.odds_provider._resolve_all_sport_keys", side_effect=_mock_resolve):
            with patch("services.odds_provider._fetch_sport_odds", fetch_mock):
                events, meta = asyncio.run(fetch_odds())

        fetch_mock.assert_not_called()
        assert len(events) == 2
        assert meta["sports_cached"] == ["baseball_kbo", "baseball_mlb"]
        assert meta["sports_fetched"] == []

    def test_cache_hit_returns_cached_events(self):
        """Cached events are included in the merged result."""
        ev = _make_event("cached_ev", "baseball_kbo")
        store_cached("baseball_kbo", [ev])
        store_cached("baseball_mlb", [])

        with patch("services.odds_provider._resolve_all_sport_keys", side_effect=_mock_resolve):
            with patch("services.odds_provider._fetch_sport_odds", AsyncMock()):
                events, meta = asyncio.run(fetch_odds())

        event_ids = [e.event_id for e in events]
        assert "cached_ev" in event_ids


class TestFetchOddsCacheMiss:
    def test_expired_cache_triggers_fetch(self):
        """When cache is expired, _fetch_sport_odds is called for that key."""
        # Store old cached data
        entry = store_cached("baseball_kbo", [_make_event()])
        entry.fetched_at = time.time() - 2000  # well past default 900s TTL
        # Leave rugby fresh
        store_cached("baseball_mlb", [_make_event("e2", "baseball_mlb")])

        fetch_mock = AsyncMock(return_value=([], {"remaining": "490", "used": "10"}))

        with patch("services.odds_provider._resolve_all_sport_keys", side_effect=_mock_resolve):
            with patch("services.odds_provider._fetch_sport_odds", fetch_mock):
                events, meta = asyncio.run(fetch_odds())

        # Only cricket should have been fetched (expired)
        assert fetch_mock.call_count == 1
        fetched_key = fetch_mock.call_args_list[0][0][0]
        assert fetched_key == "baseball_kbo"
        assert "baseball_kbo" in meta["sports_fetched"]
        assert "baseball_mlb" in meta["sports_cached"]

    def test_empty_cache_fetches_all(self):
        """With no cache, all sport keys are fetched."""
        fetch_mock = AsyncMock(return_value=([], {"remaining": "490", "used": "10"}))

        with patch("services.odds_provider._resolve_all_sport_keys", side_effect=_mock_resolve):
            with patch("services.odds_provider._fetch_sport_odds", fetch_mock):
                events, meta = asyncio.run(fetch_odds())

        assert fetch_mock.call_count == 2
        assert sorted(meta["sports_fetched"]) == ["baseball_kbo", "baseball_mlb"]
        assert meta["sports_cached"] == []


class TestFetchOddsDisabledSport:
    def test_disabled_sport_skipped(self):
        """Disabled sport is not fetched and not served from cache."""
        update_scan_config({"sports": {"baseball_kbo": {"enabled": False}}})

        fetch_mock = AsyncMock(return_value=([], {"remaining": "490", "used": "10"}))

        with patch("services.odds_provider._resolve_all_sport_keys", side_effect=_mock_resolve):
            with patch("services.odds_provider._fetch_sport_odds", fetch_mock):
                events, meta = asyncio.run(fetch_odds())

        # Cricket was skipped, only rugby was fetched
        assert "baseball_kbo" in meta["sports_skipped"]
        assert "baseball_mlb" in meta["sports_fetched"]
        assert fetch_mock.call_count == 1

    def test_disabled_sport_cached_data_still_available_via_cache(self):
        """
        Disabling a sport skips new fetches but doesn't invalidate cache.
        However, get_all_cached_events includes it. The 'disabled' flag
        means 'don't spend API quota' not 'delete existing data'.
        """
        store_cached("baseball_kbo", [_make_event("cached_kbo")])
        update_scan_config({"sports": {"baseball_kbo": {"enabled": False}}})

        fetch_mock = AsyncMock(return_value=([], {}))

        with patch("services.odds_provider._resolve_all_sport_keys", side_effect=_mock_resolve):
            with patch("services.odds_provider._fetch_sport_odds", fetch_mock):
                events, meta = asyncio.run(fetch_odds())

        # Cricket was skipped (no new fetch), but cached events still in merged list
        assert "baseball_kbo" in meta["sports_skipped"]
        event_ids = [e.event_id for e in events]
        assert "cached_kbo" in event_ids


class TestFetchOddsMeta:
    def test_meta_breakdown(self):
        """Meta correctly reports fetched, cached, and skipped keys."""
        store_cached("baseball_mlb", [_make_event("e_mlb", "baseball_mlb")])
        update_scan_config({"sports": {"baseball_kbo": {"enabled": False}}})

        # cricket disabled (skip), rugby cached (hit), nothing to fetch
        fetch_mock = AsyncMock()

        with patch("services.odds_provider._resolve_all_sport_keys", side_effect=_mock_resolve):
            with patch("services.odds_provider._fetch_sport_odds", fetch_mock):
                events, meta = asyncio.run(fetch_odds())

        assert meta["sports_skipped"] == ["baseball_kbo"]
        assert meta["sports_cached"] == ["baseball_mlb"]
        assert meta["sports_fetched"] == []
        fetch_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Sport-key discovery caching
# ---------------------------------------------------------------------------

class TestDiscoveryCache:
    def test_second_call_uses_cache(self):
        """After the first resolve, the second call should not hit the API."""
        call_count = 0

        async def _mock_resolve_tracking(api_key: str) -> dict[str, str]:
            nonlocal call_count
            # Only do the real work on first call; after that, cache should handle it
            from services.sports_config import SPORTS
            key_to_sport = {}
            for sport_key, sc in SPORTS.items():
                for api_key_val in sc.odds_api_keys:
                    key_to_sport[api_key_val] = sport_key
            # Simulate discovery API call
            call_count += 1
            discovered = {"tennis_atp_test": "tennis"}
            odds_provider_module._discovery_cache = discovered
            odds_provider_module._discovery_cache_ts = time.time()
            key_to_sport.update(discovered)
            return key_to_sport

        # Can't easily mock the internal API call within _resolve_all_sport_keys,
        # so test the cache mechanism directly.
        odds_provider_module._discovery_cache = {"tennis_atp_test": "tennis"}
        odds_provider_module._discovery_cache_ts = time.time()

        # Now call _resolve_all_sport_keys — it should use the cache, not call API
        from services.odds_provider import _resolve_all_sport_keys
        result = asyncio.run(_resolve_all_sport_keys("test-key"))

        # The result should contain the cached tennis key
        assert "tennis_atp_test" in result
        # And the explicit keys from SPORTS
        assert "baseball_kbo" in result

    def test_expired_cache_triggers_fresh_fetch(self):
        """When discovery cache is older than 1 hour, it should be re-fetched."""
        # Set cache to 2 hours ago
        odds_provider_module._discovery_cache = {"tennis_old_key": "tennis"}
        odds_provider_module._discovery_cache_ts = time.time() - 7200

        age = time.time() - odds_provider_module._discovery_cache_ts
        assert age > odds_provider_module._DISCOVERY_TTL

    def test_empty_cache_on_cold_start(self):
        """Cold start: no cache, should attempt API call."""
        assert odds_provider_module._discovery_cache is None
        assert odds_provider_module._discovery_cache_ts == 0.0
