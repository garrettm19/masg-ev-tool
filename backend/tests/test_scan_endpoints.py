"""
Tests for scan API endpoints.

Covers:
  - GET /scan/config — returns all enabled sports with labels and defaults
  - POST /scan/config — updates per-sport settings
  - GET /sports — static sport registry (enabled only)
"""
import pytest
from fastapi.testclient import TestClient

from main import app
from services.scan_config import reset_scan_config
from services.odds_cache import clear_cache

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    reset_scan_config()
    clear_cache()
    yield
    reset_scan_config()
    clear_cache()


class TestGetScanConfig:
    def test_returns_enabled_sports(self):
        resp = client.get("/api/scan/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "tennis" in body["sports"]
        assert "baseball_kbo" in body["sports"]
        assert body["sports"]["tennis"]["enabled"] is True
        assert body["sports"]["tennis"]["odds_ttl_seconds"] == 900
        assert body["global_max_odds_api_per_day"] == 200
        # Disabled sports excluded
        assert "cricket_ipl" not in body["sports"]
        assert "afl" not in body["sports"]

    def test_includes_empty_cache(self):
        resp = client.get("/api/scan/config")
        body = resp.json()
        assert body["odds_cache"] == {}


class TestPostScanConfig:
    def test_disable_sport(self):
        resp = client.post(
            "/api/scan/config",
            json={"sports": {"tennis": {"enabled": False}}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sports"]["tennis"]["enabled"] is False
        assert body["sports"]["baseball_kbo"]["enabled"] is True

    def test_change_ttl(self):
        resp = client.post(
            "/api/scan/config",
            json={"sports": {"baseball_kbo": {"odds_ttl_seconds": 1800}}},
        )
        assert resp.status_code == 200
        assert resp.json()["sports"]["baseball_kbo"]["odds_ttl_seconds"] == 1800

    def test_change_global_budget(self):
        resp = client.post(
            "/api/scan/config",
            json={"global_max_odds_api_per_day": 100},
        )
        assert resp.status_code == 200
        assert resp.json()["global_max_odds_api_per_day"] == 100

    def test_persists_across_gets(self):
        client.post(
            "/api/scan/config",
            json={"sports": {"tennis": {"enabled": False}}},
        )
        resp = client.get("/api/scan/config")
        assert resp.json()["sports"]["tennis"]["enabled"] is False

    def test_change_ttl_persists(self):
        client.post(
            "/api/scan/config",
            json={"sports": {"tennis": {"odds_ttl_seconds": 300}}},
        )
        resp = client.get("/api/scan/config")
        assert resp.json()["sports"]["tennis"]["odds_ttl_seconds"] == 300

    def test_label_included_in_response(self):
        resp = client.get("/api/scan/config")
        body = resp.json()
        assert body["sports"]["tennis"]["label"] == "Tennis"
        assert body["sports"]["baseball_kbo"]["label"] == "KBO"

    def test_multiple_sports_in_one_update(self):
        resp = client.post(
            "/api/scan/config",
            json={"sports": {
                "tennis": {"enabled": False},
                "baseball_kbo": {"odds_ttl_seconds": 1800},
            }},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sports"]["tennis"]["enabled"] is False
        assert body["sports"]["baseball_kbo"]["odds_ttl_seconds"] == 1800
        # Others unchanged
        assert body["sports"]["hockey_nhl"]["enabled"] is True


# ---------------------------------------------------------------------------
# GET /api/sports (registry)
# ---------------------------------------------------------------------------

class TestSportsRegistry:
    def test_returns_enabled_sports(self):
        resp = client.get("/api/sports")
        assert resp.status_code == 200
        body = resp.json()
        assert "tennis" in body
        assert "ufl" in body
        assert "hockey_nhl" in body
        # Disabled sports excluded
        assert "cricket_ipl" not in body
        assert "rugby_nrl" not in body
        assert "hockey_ahl" not in body
        assert "afl" not in body

    def test_entry_has_label(self):
        resp = client.get("/api/sports")
        body = resp.json()
        assert body["tennis"]["label"] == "Tennis"
        assert body["baseball_kbo"]["label"] == "KBO"

    def test_entry_has_match_style(self):
        resp = client.get("/api/sports")
        body = resp.json()
        assert body["tennis"]["match_style"] == "individual"
        assert body["baseball_kbo"]["match_style"] == "team"

    def test_entry_has_market_types(self):
        resp = client.get("/api/sports")
        body = resp.json()
        assert "h2h" in body["tennis"]["market_types"]

    def test_static_not_affected_by_scan_config(self):
        """Disabling a sport in scan config should not affect the registry."""
        client.post("/api/scan/config", json={"sports": {"tennis": {"enabled": False}}})
        resp = client.get("/api/sports")
        body = resp.json()
        # Registry still shows tennis (it's a static config, not scan state)
        assert "tennis" in body
        assert body["tennis"]["label"] == "Tennis"


# ---------------------------------------------------------------------------
# Platform toggle exposure on /api/scan/config
# ---------------------------------------------------------------------------

class TestPlatformsInScanConfigEndpoint:
    def test_get_returns_platforms_with_defaults(self):
        resp = client.get("/api/scan/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "platforms" in body
        assert "kalshi" in body["platforms"]
        assert "polymarket" in body["platforms"]
        assert body["platforms"]["kalshi"]["enabled"] is True
        assert body["platforms"]["polymarket"]["enabled"] is False
        assert body["platforms"]["kalshi"]["label"] == "Kalshi"
        assert body["platforms"]["polymarket"]["label"] == "Polymarket"

    def test_post_can_enable_polymarket(self):
        resp = client.post(
            "/api/scan/config",
            json={"platforms": {"polymarket": {"enabled": True}}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["platforms"]["polymarket"]["enabled"] is True
        assert body["platforms"]["kalshi"]["enabled"] is True

    def test_post_can_disable_kalshi(self):
        resp = client.post(
            "/api/scan/config",
            json={"platforms": {"kalshi": {"enabled": False}}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["platforms"]["kalshi"]["enabled"] is False

    def test_post_persists_across_get(self):
        client.post(
            "/api/scan/config",
            json={"platforms": {"polymarket": {"enabled": True}}},
        )
        body = client.get("/api/scan/config").json()
        assert body["platforms"]["polymarket"]["enabled"] is True

    def test_post_sport_update_does_not_disturb_platforms(self):
        client.post(
            "/api/scan/config",
            json={"sports": {"tennis": {"enabled": False}}},
        )
        body = client.get("/api/scan/config").json()
        assert body["platforms"]["kalshi"]["enabled"] is True
        assert body["platforms"]["polymarket"]["enabled"] is False


class TestPropsEnabledExposedReadOnly:
    """`props_enabled` mirrors EngineConfig.enable_props for the dashboard's
    status strip. It is read-only: there is no setter via /scan/config.
    Toggling props remains a deliberate code-level change."""

    def test_get_includes_props_enabled_default_false(self):
        body = client.get("/api/scan/config").json()
        assert "props_enabled" in body
        assert body["props_enabled"] is False

    def test_get_returns_bool_type(self):
        body = client.get("/api/scan/config").json()
        assert isinstance(body["props_enabled"], bool)

    def test_post_with_props_enabled_payload_is_ignored(self):
        """Sending props_enabled in a POST must NOT flip the flag.
        update_scan_config silently ignores unknown top-level keys."""
        resp = client.post(
            "/api/scan/config",
            json={"props_enabled": True},
        )
        assert resp.status_code == 200
        # Field is still false — write attempt was ignored
        assert resp.json()["props_enabled"] is False
        # And persists across a fresh GET
        body = client.get("/api/scan/config").json()
        assert body["props_enabled"] is False

    def test_props_enabled_unchanged_by_other_updates(self):
        client.post(
            "/api/scan/config",
            json={"sports": {"tennis": {"enabled": False}},
                  "platforms": {"polymarket": {"enabled": True}}},
        )
        body = client.get("/api/scan/config").json()
        assert body["props_enabled"] is False
