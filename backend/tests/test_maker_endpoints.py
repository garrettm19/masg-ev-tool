"""
Tests for the read-only maker proposal endpoints.

Covers:
  GET /api/maker/proposals — listing + filters (status, eligible, platform, market_id)
  GET /api/maker/summary   — counts + top rejection reasons + average edge

The store is injected per-test via FastAPI's ``dependency_overrides``
so every test runs against an isolated ``tmp_path``-backed
``PaperMakerStore``.  Read-only by design — POST/DELETE must return 405.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from routers.maker import get_paper_store
from services.maker.state import (
    PaperMakerStore,
    STATUS_PAPER_ACTIVE,
    STATUS_PAPER_REJECTED,
)

# Reuse the persistence test's proposal factory.
from tests.test_maker_persistence import _proposal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_store(tmp_path: Path):
    """TestClient with the maker store dependency redirected at tmp_path.

    Yields ``(client, store, tmp_path)``.  Cleans up the override afterwards
    so other test files using TestClient(app) keep their default behavior.
    """
    store = PaperMakerStore(base_dir=tmp_path)
    app.dependency_overrides[get_paper_store] = lambda: store
    try:
        with TestClient(app) as client:
            yield client, store, tmp_path
    finally:
        app.dependency_overrides.pop(get_paper_store, None)


@pytest.fixture
def populated(client_with_store):
    """Pre-populated store: 2 eligible Kalshi, 1 rejected Polymarket,
    1 rejected Kalshi (with two reason codes)."""
    client, store, tmp_path = client_with_store
    store.append(
        _proposal(eligible=True, proposal_id="P-K1",
                  market_id="K-MKT-1", platform="kalshi"),
        STATUS_PAPER_ACTIVE,
    )
    store.append(
        _proposal(eligible=True, proposal_id="P-K2",
                  market_id="K-MKT-2", platform="kalshi"),
        STATUS_PAPER_ACTIVE,
    )
    store.append(
        _proposal(
            eligible=False,
            rejection_reasons=("PLATFORM_OUT_OF_SCOPE",),
            proposal_id="P-P1",
            market_id="P-MKT-1",
            platform="polymarket",
        ),
        STATUS_PAPER_REJECTED,
    )
    store.append(
        _proposal(
            eligible=False,
            rejection_reasons=("BOOK_STALE", "PLATFORM_OUT_OF_SCOPE"),
            proposal_id="P-K3",
            market_id="K-MKT-3",
            platform="kalshi",
        ),
        STATUS_PAPER_REJECTED,
    )
    return client, store, tmp_path


# ---------------------------------------------------------------------------
# Empty store
# ---------------------------------------------------------------------------

class TestEmptyStore:
    def test_proposals_empty_returns_empty_list(self, client_with_store):
        client, _, _ = client_with_store
        resp = client.get("/api/maker/proposals")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"days": 1, "count": 0, "proposals": []}

    def test_summary_empty_returns_zeros(self, client_with_store):
        client, _, _ = client_with_store
        resp = client.get("/api/maker/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["days"] == 1
        assert body["total"] == 0
        assert body["eligible"] == 0
        assert body["rejected"] == 0
        assert body["by_status"] == {}
        assert body["by_platform"] == {}
        assert body["top_rejection_reasons"] == []
        assert body["average_estimated_maker_edge"] is None

    def test_proposals_missing_directory(self, tmp_path: Path):
        """Endpoint must not error when the store base_dir doesn't exist yet."""
        nonexistent = tmp_path / "no-such-dir"
        store = PaperMakerStore(base_dir=nonexistent)
        app.dependency_overrides[get_paper_store] = lambda: store
        try:
            with TestClient(app) as client:
                resp = client.get("/api/maker/proposals")
                assert resp.status_code == 200
                assert resp.json()["count"] == 0
        finally:
            app.dependency_overrides.pop(get_paper_store, None)


# ---------------------------------------------------------------------------
# Listing + filters
# ---------------------------------------------------------------------------

class TestProposalsList:
    def test_returns_all_records(self, populated):
        client, _, _ = populated
        resp = client.get("/api/maker/proposals")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 4
        ids = {p["proposal_id"] for p in body["proposals"]}
        assert ids == {"P-K1", "P-K2", "P-P1", "P-K3"}

    def test_filter_by_status_active(self, populated):
        client, _, _ = populated
        resp = client.get(
            "/api/maker/proposals", params={"status": STATUS_PAPER_ACTIVE}
        )
        body = resp.json()
        assert body["count"] == 2
        for p in body["proposals"]:
            assert p["status"] == STATUS_PAPER_ACTIVE

    def test_filter_by_status_rejected(self, populated):
        client, _, _ = populated
        resp = client.get(
            "/api/maker/proposals", params={"status": STATUS_PAPER_REJECTED}
        )
        body = resp.json()
        assert body["count"] == 2
        for p in body["proposals"]:
            assert p["status"] == STATUS_PAPER_REJECTED

    def test_filter_by_eligible_true(self, populated):
        client, _, _ = populated
        resp = client.get("/api/maker/proposals", params={"eligible": "true"})
        body = resp.json()
        assert body["count"] == 2
        for p in body["proposals"]:
            assert p["eligible"] is True

    def test_filter_by_eligible_false(self, populated):
        client, _, _ = populated
        resp = client.get("/api/maker/proposals", params={"eligible": "false"})
        body = resp.json()
        assert body["count"] == 2
        for p in body["proposals"]:
            assert p["eligible"] is False

    def test_filter_by_platform(self, populated):
        client, _, _ = populated
        resp = client.get("/api/maker/proposals", params={"platform": "kalshi"})
        body = resp.json()
        assert body["count"] == 3
        for p in body["proposals"]:
            assert p["platform"] == "kalshi"

        resp = client.get("/api/maker/proposals", params={"platform": "polymarket"})
        body = resp.json()
        assert body["count"] == 1
        assert body["proposals"][0]["platform"] == "polymarket"

    def test_filter_by_market_id(self, populated):
        client, _, _ = populated
        resp = client.get(
            "/api/maker/proposals", params={"market_id": "K-MKT-1"}
        )
        body = resp.json()
        assert body["count"] == 1
        assert body["proposals"][0]["market_id"] == "K-MKT-1"

    def test_filter_combination(self, populated):
        """Filters AND together: eligible=true + platform=kalshi → both Kalshi
        eligible records, polymarket excluded."""
        client, _, _ = populated
        resp = client.get(
            "/api/maker/proposals",
            params={"eligible": "true", "platform": "kalshi"},
        )
        body = resp.json()
        assert body["count"] == 2

    def test_unknown_status_returns_empty(self, populated):
        client, _, _ = populated
        resp = client.get(
            "/api/maker/proposals", params={"status": "no_such_status"}
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

class TestSummaryAggregation:
    def test_total_eligible_rejected_counts(self, populated):
        client, _, _ = populated
        body = client.get("/api/maker/summary").json()
        assert body["total"] == 4
        assert body["eligible"] == 2
        assert body["rejected"] == 2

    def test_by_status_breakdown(self, populated):
        client, _, _ = populated
        body = client.get("/api/maker/summary").json()
        assert body["by_status"] == {
            STATUS_PAPER_ACTIVE: 2,
            STATUS_PAPER_REJECTED: 2,
        }

    def test_by_platform_breakdown(self, populated):
        client, _, _ = populated
        body = client.get("/api/maker/summary").json()
        assert body["by_platform"] == {"kalshi": 3, "polymarket": 1}

    def test_top_rejection_reasons_counted(self, populated):
        """PLATFORM_OUT_OF_SCOPE appears on both rejected records (count 2);
        BOOK_STALE only on K3 (count 1).  Eligible records contribute none."""
        client, _, _ = populated
        body = client.get("/api/maker/summary").json()
        reasons = {r["reason"]: r["count"] for r in body["top_rejection_reasons"]}
        assert reasons["PLATFORM_OUT_OF_SCOPE"] == 2
        assert reasons["BOOK_STALE"] == 1

    def test_top_rejection_reasons_ordered_by_count(self, populated):
        client, _, _ = populated
        body = client.get("/api/maker/summary").json()
        counts = [r["count"] for r in body["top_rejection_reasons"]]
        assert counts == sorted(counts, reverse=True)

    def test_average_estimated_maker_edge_for_eligible(self, populated):
        """The default _proposal estimated_maker_edge is 0.08; both eligible
        records carry that value."""
        client, _, _ = populated
        body = client.get("/api/maker/summary").json()
        assert body["average_estimated_maker_edge"] == pytest.approx(0.08)

    def test_average_edge_none_when_no_eligible(self, client_with_store):
        client, store, _ = client_with_store
        store.append(
            _proposal(eligible=False, rejection_reasons=("BOOK_STALE",)),
            STATUS_PAPER_REJECTED,
        )
        body = client.get("/api/maker/summary").json()
        assert body["average_estimated_maker_edge"] is None

    def test_top_n_query_param_caps_list(self, client_with_store):
        client, store, _ = client_with_store
        # Six distinct rejection reasons across six rejected records
        for i, code in enumerate(["A", "B", "C", "D", "E", "F"]):
            store.append(
                _proposal(
                    eligible=False,
                    rejection_reasons=(code,),
                    proposal_id=f"r-{i}",
                ),
                STATUS_PAPER_REJECTED,
            )
        body = client.get("/api/maker/summary", params={"top_n": 3}).json()
        assert len(body["top_rejection_reasons"]) == 3


# ---------------------------------------------------------------------------
# Days parameter
# ---------------------------------------------------------------------------

class TestDaysParameter:
    def test_default_days_is_1(self, populated):
        client, _, _ = populated
        body = client.get("/api/maker/proposals").json()
        assert body["days"] == 1

    def test_explicit_days_param_echoed(self, populated):
        client, _, _ = populated
        body = client.get("/api/maker/proposals", params={"days": 7}).json()
        assert body["days"] == 7

    def test_summary_days_echoed(self, populated):
        client, _, _ = populated
        body = client.get("/api/maker/summary", params={"days": 14}).json()
        assert body["days"] == 14

    def test_days_zero_rejected(self, client_with_store):
        client, _, _ = client_with_store
        resp = client.get("/api/maker/proposals", params={"days": 0})
        assert resp.status_code == 422

    def test_days_negative_rejected(self, client_with_store):
        client, _, _ = client_with_store
        resp = client.get("/api/maker/summary", params={"days": -1})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Read-only / no secrets
# ---------------------------------------------------------------------------

class TestReadOnly:
    def test_post_proposals_method_not_allowed(self, client_with_store):
        client, _, _ = client_with_store
        assert client.post("/api/maker/proposals").status_code == 405

    def test_post_summary_method_not_allowed(self, client_with_store):
        client, _, _ = client_with_store
        assert client.post("/api/maker/summary").status_code == 405

    def test_delete_proposals_method_not_allowed(self, client_with_store):
        client, _, _ = client_with_store
        assert client.delete("/api/maker/proposals").status_code == 405

    def test_put_proposals_method_not_allowed(self, client_with_store):
        client, _, _ = client_with_store
        assert client.put("/api/maker/proposals").status_code == 405


class TestNoSecrets:
    def test_response_does_not_contain_api_key_or_paths(
        self, monkeypatch, client_with_store
    ):
        monkeypatch.setenv("KALSHI_API_KEY", "secret-XYZ-7777")
        client, store, tmp_path = client_with_store
        store.append(_proposal(), STATUS_PAPER_ACTIVE)

        for path in ("/api/maker/proposals", "/api/maker/summary"):
            resp = client.get(path)
            raw = resp.text
            # No env-var values
            assert "secret-XYZ-7777" not in raw
            # No auth header literals
            assert "Authorization" not in raw
            assert "api_key" not in raw
            # No filesystem paths leaked into the JSON
            assert str(tmp_path) not in raw
            assert "data/maker_paper_orders" not in raw


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestRouterMounted:
    def test_proposals_route_exists(self, client_with_store):
        client, _, _ = client_with_store
        assert client.get("/api/maker/proposals").status_code == 200

    def test_summary_route_exists(self, client_with_store):
        client, _, _ = client_with_store
        assert client.get("/api/maker/summary").status_code == 200

    def test_unknown_maker_route_404(self, client_with_store):
        client, _, _ = client_with_store
        assert client.get("/api/maker/no-such-route").status_code == 404
