"""
Tests for services.clob_polymarket.

No live network calls — uses httpx.MockTransport for fetch_book and patches
fetch_book itself for fetch_books orchestration.
"""
import asyncio

import httpx
from unittest.mock import AsyncMock, patch

from services.clob_polymarket import (
    BookLevel,
    OrderBook,
    _build_book,
    fetch_book,
    fetch_books,
)


# ---------------------------------------------------------------------------
# Synchronous parsing — _build_book
# ---------------------------------------------------------------------------

class TestBuildBook:
    def test_normal_book(self):
        payload = {
            "asset_id": "tok1",
            "bids": [{"price": "0.45", "size": "100"}],
            "asks": [{"price": "0.52", "size": "300"}],
        }
        book = _build_book("tok1", payload)
        assert book is not None
        assert book.token_id == "tok1"
        assert book.bids == [BookLevel(price=0.45, size=100.0)]
        assert book.asks == [BookLevel(price=0.52, size=300.0)]

    def test_string_prices_and_sizes_parsed(self):
        payload = {
            "bids": [{"price": "0.30", "size": "1.5"}],
            "asks": [{"price": "0.35", "size": "2.0"}],
        }
        book = _build_book("t", payload)
        assert book is not None
        assert book.bids[0].price == 0.30
        assert book.bids[0].size == 1.5
        assert book.asks[0].price == 0.35
        assert book.asks[0].size == 2.0

    def test_numeric_prices_and_sizes_parsed(self):
        payload = {
            "bids": [{"price": 0.30, "size": 1.5}],
            "asks": [{"price": 0.35, "size": 2}],
        }
        book = _build_book("t", payload)
        assert book is not None
        assert book.bids[0].price == 0.30
        assert book.asks[0].size == 2.0

    def test_asks_sorted_ascending(self):
        payload = {
            "bids": [],
            "asks": [
                {"price": "0.55", "size": "10"},
                {"price": "0.50", "size": "20"},
                {"price": "0.60", "size": "5"},
            ],
        }
        book = _build_book("t", payload)
        assert book is not None
        assert [lvl.price for lvl in book.asks] == [0.50, 0.55, 0.60]

    def test_bids_sorted_descending(self):
        payload = {
            "bids": [
                {"price": "0.40", "size": "10"},
                {"price": "0.45", "size": "20"},
                {"price": "0.42", "size": "5"},
            ],
            "asks": [],
        }
        book = _build_book("t", payload)
        assert book is not None
        assert [lvl.price for lvl in book.bids] == [0.45, 0.42, 0.40]

    def test_empty_lists_allowed(self):
        payload = {"bids": [], "asks": []}
        book = _build_book("t", payload)
        assert book is not None
        assert book.bids == []
        assert book.asks == []

    def test_missing_bids_returns_none(self):
        payload = {"asks": []}
        assert _build_book("t", payload) is None

    def test_missing_asks_returns_none(self):
        payload = {"bids": []}
        assert _build_book("t", payload) is None

    def test_null_bids_returns_none(self):
        payload = {"bids": None, "asks": []}
        assert _build_book("t", payload) is None

    def test_payload_not_dict_returns_none(self):
        assert _build_book("t", []) is None
        assert _build_book("t", "string") is None
        assert _build_book("t", None) is None

    def test_skips_malformed_levels(self):
        payload = {
            "bids": [
                {"price": "0.40", "size": "10"},
                {"price": "not-a-number", "size": "5"},   # skip
                "not-a-dict",                              # skip
                {"price": "0.42"},                         # skip (no size)
                {"price": "0.41", "size": "8"},
            ],
            "asks": [],
        }
        book = _build_book("t", payload)
        assert book is not None
        # 0.42 entry skipped (missing size); 0.41 and 0.40 survive, descending
        assert [lvl.price for lvl in book.bids] == [0.41, 0.40]


# ---------------------------------------------------------------------------
# fetch_book — uses httpx.MockTransport to avoid network
# ---------------------------------------------------------------------------

def _client_with_handler(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestFetchBook:
    def test_normal_response_returns_book(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/book"
            assert request.url.params.get("token_id") == "tok1"
            return httpx.Response(200, json={
                "bids": [{"price": "0.45", "size": "100"}],
                "asks": [{"price": "0.52", "size": "300"}],
            })

        async def run():
            async with _client_with_handler(handler) as client:
                return await fetch_book(client, "tok1")

        book = asyncio.run(run())
        assert book is not None
        assert book.token_id == "tok1"
        assert book.bids[0].price == 0.45
        assert book.asks[0].price == 0.52

    def test_http_error_returns_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        async def run():
            async with _client_with_handler(handler) as client:
                return await fetch_book(client, "tok1")

        assert asyncio.run(run()) is None

    def test_malformed_json_returns_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not-json{")

        async def run():
            async with _client_with_handler(handler) as client:
                return await fetch_book(client, "tok1")

        assert asyncio.run(run()) is None

    def test_timeout_returns_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("simulated timeout")

        async def run():
            async with _client_with_handler(handler) as client:
                return await fetch_book(client, "tok1")

        assert asyncio.run(run()) is None

    def test_missing_arrays_returns_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"asset_id": "tok1"})  # no bids/asks

        async def run():
            async with _client_with_handler(handler) as client:
                return await fetch_book(client, "tok1")

        assert asyncio.run(run()) is None

    def test_empty_arrays_returns_book(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"bids": [], "asks": []})

        async def run():
            async with _client_with_handler(handler) as client:
                return await fetch_book(client, "tok1")

        book = asyncio.run(run())
        assert book is not None
        assert book.bids == []
        assert book.asks == []


# ---------------------------------------------------------------------------
# fetch_books — orchestration tests with patched fetch_book
# ---------------------------------------------------------------------------

class TestFetchBooks:
    def test_empty_input_returns_empty_dict(self):
        result = asyncio.run(fetch_books([]))
        assert result == {}

    @patch("services.clob_polymarket.fetch_book", new_callable=AsyncMock)
    def test_returns_books_keyed_by_token_id(self, mock_fb):
        mock_fb.side_effect = [
            OrderBook(token_id="a", bids=[], asks=[]),
            OrderBook(token_id="b", bids=[], asks=[]),
        ]
        result = asyncio.run(fetch_books(["a", "b"]))
        assert set(result.keys()) == {"a", "b"}
        assert mock_fb.call_count == 2

    @patch("services.clob_polymarket.fetch_book", new_callable=AsyncMock)
    def test_omits_failed_tokens(self, mock_fb):
        mock_fb.side_effect = [
            OrderBook(token_id="a", bids=[], asks=[]),
            None,                                              # b: fetch failed
            OrderBook(token_id="c", bids=[], asks=[]),
        ]
        result = asyncio.run(fetch_books(["a", "b", "c"]))
        assert set(result.keys()) == {"a", "c"}
        assert "b" not in result

    @patch("services.clob_polymarket.fetch_book", new_callable=AsyncMock)
    def test_per_token_exception_does_not_fail_batch(self, mock_fb):
        mock_fb.side_effect = [
            OrderBook(token_id="a", bids=[], asks=[]),
            RuntimeError("network exploded"),
            OrderBook(token_id="c", bids=[], asks=[]),
        ]
        result = asyncio.run(fetch_books(["a", "b", "c"]))
        assert set(result.keys()) == {"a", "c"}

    @patch("services.clob_polymarket.fetch_book", new_callable=AsyncMock)
    def test_deduplicates_token_ids(self, mock_fb):
        mock_fb.side_effect = [
            OrderBook(token_id="a", bids=[], asks=[]),
            OrderBook(token_id="b", bids=[], asks=[]),
            OrderBook(token_id="c", bids=[], asks=[]),
        ]
        # Input has duplicates and out-of-order repeats
        result = asyncio.run(fetch_books(["a", "b", "a", "c", "b", "a"]))
        assert mock_fb.call_count == 3  # not 6
        assert set(result.keys()) == {"a", "b", "c"}

    @patch("services.clob_polymarket.fetch_book", new_callable=AsyncMock)
    def test_falsy_token_ids_ignored(self, mock_fb):
        mock_fb.side_effect = [
            OrderBook(token_id="a", bids=[], asks=[]),
        ]
        result = asyncio.run(fetch_books(["", "a", ""]))
        assert mock_fb.call_count == 1
        assert set(result.keys()) == {"a"}
