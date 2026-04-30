"""
Tests for services.scan_config and services.odds_cache.

Covers:
  - ScanConfig defaults from SPORTS registry
  - update_scan_config merges partial updates
  - per-sport enable/disable
  - odds cache TTL behavior
  - cache invalidation (single sport, all)
  - cache_status diagnostics
"""
import time

import pytest

from services.scan_config import (
    build_default_scan_config,
    get_scan_config,
    update_scan_config,
    reset_scan_config,
)
from services.odds_cache import (
    get_cached,
    store_cached,
    get_all_cached_events,
    invalidate,
    invalidate_all,
    cache_status,
    clear_cache,
    CachedOdds,
)
from services.odds_provider import TennisOddsEvent


@pytest.fixture(autouse=True)
def _clean():
    reset_scan_config()
    clear_cache()
    yield
    reset_scan_config()
    clear_cache()


def _make_event(event_id: str = "ev1", sport_key: str = "tennis_atp") -> TennisOddsEvent:
    return TennisOddsEvent(
        event_id=event_id,
        sport_key=sport_key,
        tournament="Test",
        home_player="A",
        away_player="B",
        home_player_norm="a",
        away_player_norm="b",
        commence_time="2026-06-01T12:00:00Z",
    )


# ---------------------------------------------------------------------------
# ScanConfig
# ---------------------------------------------------------------------------

class TestScanConfigDefaults:
    def test_builds_from_sports_registry(self):
        cfg = build_default_scan_config()
        assert "tennis" in cfg.sports
        assert "baseball_kbo" in cfg.sports
        assert cfg.sports["tennis"].enabled is True
        assert cfg.sports["tennis"].odds_ttl_seconds == 900
        assert cfg.sports["tennis"].label == "Tennis"
        assert cfg.sports["baseball_kbo"].label == "KBO"
        # Disabled sports excluded
        assert "cricket_ipl" not in cfg.sports
        assert "afl" not in cfg.sports

    def test_get_scan_config_singleton(self):
        c1 = get_scan_config()
        c2 = get_scan_config()
        assert c1 is c2

    def test_reset_rebuilds(self):
        c1 = get_scan_config()
        c1.sports["tennis"].enabled = False
        reset_scan_config()
        c2 = get_scan_config()
        assert c2.sports["tennis"].enabled is True


class TestUpdateScanConfig:
    def test_disable_sport(self):
        cfg = update_scan_config({"sports": {"tennis": {"enabled": False}}})
        assert cfg.sports["tennis"].enabled is False
        # Others unchanged
        assert cfg.sports["baseball_kbo"].enabled is True

    def test_change_ttl(self):
        cfg = update_scan_config({"sports": {"baseball_kbo": {"odds_ttl_seconds": 1800}}})
        assert cfg.sports["baseball_kbo"].odds_ttl_seconds == 1800

    def test_change_global_budget(self):
        cfg = update_scan_config({"global_max_odds_api_per_day": 100})
        assert cfg.global_max_odds_api_per_day == 100

    def test_unknown_sport_ignored(self):
        cfg = update_scan_config({"sports": {"fake_sport": {"enabled": False}}})
        assert "fake_sport" not in cfg.sports

    def test_unknown_field_ignored(self):
        cfg = update_scan_config({"sports": {"tennis": {"nonexistent": 42}}})
        assert not hasattr(cfg.sports["tennis"], "nonexistent")


# ---------------------------------------------------------------------------
# OddsCache
# ---------------------------------------------------------------------------

class TestOddsCache:
    def test_store_and_get(self):
        ev = _make_event()
        store_cached("tennis_atp_open", [ev], {"remaining": "490"})
        cached = get_cached("tennis_atp_open", ttl_seconds=60)
        assert cached is not None
        assert len(cached.events) == 1
        assert cached.sport_key == "tennis_atp_open"

    def test_get_returns_none_when_empty(self):
        assert get_cached("nonexistent", ttl_seconds=60) is None

    def test_get_returns_none_when_expired(self):
        ev = _make_event()
        entry = store_cached("tennis_atp_open", [ev])
        # Manually backdate
        entry.fetched_at = time.time() - 120
        assert get_cached("tennis_atp_open", ttl_seconds=60) is None

    def test_get_returns_entry_within_ttl(self):
        ev = _make_event()
        store_cached("tennis_atp_open", [ev])
        assert get_cached("tennis_atp_open", ttl_seconds=9999) is not None

    def test_get_all_cached_events_merges(self):
        store_cached("sport_a", [_make_event("e1", "sport_a")])
        store_cached("sport_b", [_make_event("e2", "sport_b"), _make_event("e3", "sport_b")])
        merged = get_all_cached_events()
        assert len(merged) == 3

    def test_invalidate_single(self):
        store_cached("sport_a", [_make_event()])
        store_cached("sport_b", [_make_event()])
        assert invalidate("sport_a") is True
        assert get_cached("sport_a", ttl_seconds=9999) is None
        assert get_cached("sport_b", ttl_seconds=9999) is not None

    def test_invalidate_nonexistent(self):
        assert invalidate("nope") is False

    def test_invalidate_all(self):
        store_cached("sport_a", [_make_event()])
        store_cached("sport_b", [_make_event()])
        count = invalidate_all()
        assert count == 2
        assert get_all_cached_events() == []

    def test_cache_status(self):
        store_cached("sport_a", [_make_event(), _make_event("e2")])
        status = cache_status()
        assert "sport_a" in status
        assert status["sport_a"]["event_count"] == 2
        assert status["sport_a"]["age_seconds"] < 5
