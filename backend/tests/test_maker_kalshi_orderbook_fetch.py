"""
Tests for the async Kalshi orderbook REST fetcher.

The fetcher must NEVER raise — every error path returns None.
Covers: success, missing API key, 404/429/500 HTTP errors, network errors,
malformed JSON, and a parser-failure passthrough.

httpx.AsyncClient is mocked via the `client=` kwarg so tests don't open
real sockets.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services.maker.orderbook import fetch_kalshi_orderbook


def _ok_response(json_payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_payload)
    return resp


def _err_response(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp,
        )
    )
    return resp


def _mock_client(get_return=None, get_side_effect=None) -> AsyncMock:
    client = AsyncMock()
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_return)
    return client


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

class TestFetchSuccess:
    def test_canonical_book_returned(self):
        client = _mock_client(_ok_response({
            "orderbook": {
                "yes": [[40, 10], [42, 5]],
                "no":  [[43, 8], [41, 10]],
            }
        }))
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="test", client=client)
        )
        assert book is not None
        assert book.market_id == "KX-TEST"
        assert book.best_yes_bid() == pytest.approx(0.42)
        assert book.best_yes_ask() == pytest.approx(0.57)
        assert book.source == "rest"

    def test_passes_authorization_header(self):
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        asyncio.run(fetch_kalshi_orderbook("KX-TEST", api_key="my-key", client=client))
        call_kwargs = client.get.call_args_list[0]
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers == {"Authorization": "my-key"}

    def test_passes_depth_param_when_provided(self):
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client, depth=20)
        )
        params = client.get.call_args_list[0].kwargs.get("params") or {}
        assert params.get("depth") == 20

    def test_omits_depth_param_when_unspecified(self):
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        asyncio.run(fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client))
        params = client.get.call_args_list[0].kwargs.get("params") or {}
        assert "depth" not in params

    def test_uses_correct_url(self):
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        asyncio.run(fetch_kalshi_orderbook("KX-FOO", api_key="k", client=client))
        url = client.get.call_args_list[0].args[0]
        assert url.endswith("/markets/KX-FOO/orderbook")


# ---------------------------------------------------------------------------
# Auth missing
# ---------------------------------------------------------------------------

class TestNoApiKey:
    def test_missing_api_key_returns_none(self, monkeypatch):
        """No KALSHI_API_KEY env var and no kwarg → return None, no fetch."""
        monkeypatch.delenv("KALSHI_API_KEY", raising=False)
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        book = asyncio.run(fetch_kalshi_orderbook("KX-TEST", api_key=None, client=client))
        assert book is None
        client.get.assert_not_called()

    def test_empty_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("KALSHI_API_KEY", raising=False)
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        book = asyncio.run(fetch_kalshi_orderbook("KX-TEST", api_key="", client=client))
        assert book is None
        client.get.assert_not_called()

    def test_falls_back_to_env_var(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY", "env-key")
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        book = asyncio.run(fetch_kalshi_orderbook("KX-TEST", api_key=None, client=client))
        assert book is not None
        headers = client.get.call_args_list[0].kwargs.get("headers")
        assert headers == {"Authorization": "env-key"}


# ---------------------------------------------------------------------------
# HTTP errors — 404, 429, 500 must all return None, not raise
# ---------------------------------------------------------------------------

class TestHttpErrors:
    @pytest.mark.parametrize("status", [404, 429, 500, 502, 503])
    def test_http_error_returns_none(self, status):
        client = _mock_client(_err_response(status))
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client)
        )
        assert book is None


# ---------------------------------------------------------------------------
# Network errors — every transport-level failure must return None
# ---------------------------------------------------------------------------

class TestNetworkErrors:
    def test_connect_error_returns_none(self):
        client = _mock_client(get_side_effect=httpx.ConnectError("refused"))
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client)
        )
        assert book is None

    def test_read_timeout_returns_none(self):
        client = _mock_client(get_side_effect=httpx.ReadTimeout("slow"))
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client)
        )
        assert book is None

    def test_generic_request_error_returns_none(self):
        client = _mock_client(get_side_effect=httpx.RequestError("boom"))
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client)
        )
        assert book is None


# ---------------------------------------------------------------------------
# JSON / parser failures
# ---------------------------------------------------------------------------

class TestMalformedJson:
    def test_json_decode_error_returns_none(self):
        bad_resp = MagicMock()
        bad_resp.raise_for_status = MagicMock()
        bad_resp.json = MagicMock(side_effect=ValueError("not JSON"))
        client = _mock_client(bad_resp)
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client)
        )
        assert book is None

    def test_non_dict_payload_returns_none(self):
        """Server returns valid JSON that isn't a dict — parser returns None."""
        client = _mock_client(_ok_response(["not", "a", "dict"]))
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client)
        )
        assert book is None

    def test_partial_payload_parses_with_empty_sides(self):
        """A payload missing yes/no still parses (empty book), per parser contract."""
        client = _mock_client(_ok_response({"orderbook": {}}))
        book = asyncio.run(
            fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client)
        )
        assert book is not None
        assert book.yes_bids == ()
        assert book.no_bids == ()


# ---------------------------------------------------------------------------
# Client lifecycle: caller-supplied client is NOT closed by the fetcher
# ---------------------------------------------------------------------------

class TestClientLifecycle:
    def test_caller_supplied_client_not_closed(self):
        client = _mock_client(_ok_response({"orderbook": {"yes": [], "no": []}}))
        client.aclose = AsyncMock()
        asyncio.run(fetch_kalshi_orderbook("KX-TEST", api_key="k", client=client))
        # Caller owns the client; fetcher must not close it.
        client.aclose.assert_not_called()
