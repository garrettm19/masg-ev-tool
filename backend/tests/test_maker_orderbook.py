"""
Tests for the orderbook model and parser (synchronous, no network).

Kalshi orderbook channel publishes resting BIDS per side:
  - yes → list of [price_cents, qty] for YES bids
  - no  → list of [price_cents, qty] for NO  bids

Best YES bid = max(yes prices)
Best YES ask = 1.0 - max(no prices)   # NO bid 43¢ ⇒ YES ask 57¢

The lowest YES bid is *not* the YES ask.  These tests pin that invariant
in the model layer for the maker planner.
"""
from __future__ import annotations

import time

import pytest

from services.maker.orderbook import (
    BookLevel,
    OrderBook,
    _parse_price_to_cents,
    _parse_quantity,
    _synthesize_yes_asks,
    parse_kalshi_orderbook,
)


# ---------------------------------------------------------------------------
# Parser — canonical case
# ---------------------------------------------------------------------------

class TestParseCanonical:
    def test_canonical_synthesis(self):
        payload = {
            "orderbook": {
                "yes": [[40, 10], [42, 5]],
                "no":  [[43, 8], [41, 10]],
            }
        }
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.market_id == "T1"
        assert book.best_yes_bid() == pytest.approx(0.42)
        assert book.best_yes_ask() == pytest.approx(0.57)
        assert book.best_no_bid() == pytest.approx(0.43)

    def test_does_not_use_min_yes_as_ask(self):
        """Regression: ask must NOT be derived from the YES side."""
        payload = {
            "orderbook": {
                "yes": [[35, 1], [40, 5], [42, 8]],   # min(yes) = 35¢ — would be wrong
                "no":  [[50, 10]],
            }
        }
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_ask() == pytest.approx(0.50)
        # Confirm: 0.35 is not anywhere on the synthesized ask side
        assert all(lv.price != pytest.approx(0.35) for lv in book.yes_asks)

    def test_yes_bids_sorted_descending(self):
        payload = {"orderbook": {"yes": [[40, 1], [45, 2], [42, 3]], "no": []}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        prices = [lv.price for lv in book.yes_bids]
        assert prices == [pytest.approx(0.45), pytest.approx(0.42), pytest.approx(0.40)]

    def test_no_bids_sorted_descending(self):
        payload = {"orderbook": {"yes": [], "no": [[41, 1], [44, 2], [42, 3]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        prices = [lv.price for lv in book.no_bids]
        assert prices == [pytest.approx(0.44), pytest.approx(0.42), pytest.approx(0.41)]

    def test_yes_asks_sorted_ascending(self):
        payload = {"orderbook": {"yes": [], "no": [[41, 1], [44, 2], [42, 3]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        # NO bids 41/42/44 → YES asks 59/58/56 → ascending: 56/58/59
        prices = [lv.price for lv in book.yes_asks]
        assert prices == [pytest.approx(0.56), pytest.approx(0.58), pytest.approx(0.59)]


# ---------------------------------------------------------------------------
# Parser — empty / missing sides
# ---------------------------------------------------------------------------

class TestParseEmptySides:
    def test_empty_no_side_no_ask(self):
        payload = {"orderbook": {"yes": [[40, 10]], "no": []}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_bid() == pytest.approx(0.40)
        assert book.best_yes_ask() is None
        assert book.spread() is None

    def test_empty_yes_side_no_bid(self):
        payload = {"orderbook": {"yes": [], "no": [[43, 5]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_bid() is None
        assert book.best_yes_ask() == pytest.approx(0.57)
        assert book.spread() is None

    def test_both_sides_empty(self):
        payload = {"orderbook": {"yes": [], "no": []}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_bid() is None
        assert book.best_yes_ask() is None
        assert book.is_crossed() is False

    def test_missing_arrays(self):
        payload = {"orderbook": {}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.yes_bids == ()
        assert book.no_bids == ()
        assert book.yes_asks == ()


# ---------------------------------------------------------------------------
# Parser — malformed input
# ---------------------------------------------------------------------------

class TestParseMalformed:
    def test_zero_qty_dropped(self):
        payload = {"orderbook": {"yes": [[40, 10], [42, 0]], "no": [[50, 10], [55, 0]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_bid() == pytest.approx(0.40)
        assert book.best_yes_ask() == pytest.approx(0.50)

    def test_negative_qty_dropped(self):
        payload = {"orderbook": {"yes": [[40, 10], [42, -3]], "no": [[50, 10]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_bid() == pytest.approx(0.40)

    def test_out_of_range_price_dropped(self):
        payload = {"orderbook": {
            "yes": [[40, 10], [0, 5], [100, 5], [-3, 5]],
            "no": [[50, 10]],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert len(book.yes_bids) == 1
        assert book.yes_bids[0].price == pytest.approx(0.40)

    def test_malformed_entries_skipped(self):
        payload = {"orderbook": {
            "yes": [[40, 10], ["bad", "data"], [42], "string", None, [43, 5]],
            "no": [[50, 10]],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        prices = sorted(lv.price for lv in book.yes_bids)
        assert prices == [pytest.approx(0.40), pytest.approx(0.43)]

    def test_duplicate_prices_summed(self):
        payload = {"orderbook": {"yes": [[40, 10], [40, 5]], "no": [[50, 10]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        # Same-price duplicates aggregate qty
        assert len(book.yes_bids) == 1
        assert book.yes_bids[0].quantity == 15

    def test_non_dict_payload_returns_none(self):
        assert parse_kalshi_orderbook("T1", "not a dict") is None
        assert parse_kalshi_orderbook("T1", None) is None
        assert parse_kalshi_orderbook("T1", []) is None
        assert parse_kalshi_orderbook("T1", 42) is None

    def test_unwrapped_payload_accepted(self):
        """Both `{"orderbook": {...}}` and bare `{"yes": ..., "no": ...}` work."""
        payload = {"yes": [[40, 10]], "no": [[50, 5]]}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_bid() == pytest.approx(0.40)
        assert book.best_yes_ask() == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Best-of-book + spread + crossed
# ---------------------------------------------------------------------------

class TestBestOfBook:
    def test_spread_normal(self):
        payload = {"orderbook": {"yes": [[40, 10]], "no": [[50, 10]]}}
        book = parse_kalshi_orderbook("T1", payload)
        # bid=0.40, ask=1-0.50=0.50, spread=0.10
        assert book.spread() == pytest.approx(0.10)
        assert book.is_crossed() is False

    def test_locked_market(self):
        # YES bid 0.50, NO bid 0.50 → YES ask 0.50 → bid==ask
        payload = {"orderbook": {"yes": [[50, 10]], "no": [[50, 10]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book.spread() == pytest.approx(0.0)
        assert book.is_crossed() is True

    def test_crossed_market(self):
        # YES bid 0.55, NO bid 0.50 → YES ask 0.50 → bid>ask
        payload = {"orderbook": {"yes": [[55, 10]], "no": [[50, 10]]}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book.spread() == pytest.approx(-0.05)
        assert book.is_crossed() is True

    def test_one_sided_book_not_crossed(self):
        payload = {"orderbook": {"yes": [[40, 10]], "no": []}}
        book = parse_kalshi_orderbook("T1", payload)
        assert book.is_crossed() is False


# ---------------------------------------------------------------------------
# Level lookups
# ---------------------------------------------------------------------------

class TestLevelLookups:
    def _book(self) -> OrderBook:
        payload = {"orderbook": {
            "yes": [[40, 10], [42, 5], [38, 3]],
            "no":  [[43, 8], [44, 4], [41, 6]],
        }}
        return parse_kalshi_orderbook("T1", payload)

    def test_queue_qty_at_yes_bid(self):
        book = self._book()
        assert book.queue_qty_at("yes_bid", 0.40) == 10
        assert book.queue_qty_at("yes_bid", 0.42) == 5
        assert book.queue_qty_at("yes_bid", 0.41) == 0   # no level

    def test_queue_qty_at_no_bid(self):
        book = self._book()
        assert book.queue_qty_at("no_bid", 0.43) == 8
        assert book.queue_qty_at("no_bid", 0.44) == 4
        assert book.queue_qty_at("no_bid", 0.42) == 0

    def test_queue_qty_at_yes_ask(self):
        book = self._book()
        # NO 43¢ ⇒ YES ask 57¢ qty 8
        assert book.queue_qty_at("yes_ask", 0.57) == 8
        # NO 44¢ ⇒ YES ask 56¢ qty 4
        assert book.queue_qty_at("yes_ask", 0.56) == 4
        assert book.queue_qty_at("yes_ask", 0.55) == 0

    def test_depth_at_or_better_yes_bid(self):
        book = self._book()
        # 0.40 or better (≥): 0.42 + 0.40 = 5 + 10 = 15
        assert book.depth_at_or_better("yes_bid", 0.40) == 15
        # 0.38 or better (≥): all three = 5 + 10 + 3 = 18
        assert book.depth_at_or_better("yes_bid", 0.38) == 18
        # 0.42 or better (≥): just 0.42 = 5
        assert book.depth_at_or_better("yes_bid", 0.42) == 5
        # 0.50 or better (≥): nothing
        assert book.depth_at_or_better("yes_bid", 0.50) == 0

    def test_depth_at_or_better_no_bid(self):
        book = self._book()
        # 0.43 or better (≥): 0.44 + 0.43 = 4 + 8 = 12
        assert book.depth_at_or_better("no_bid", 0.43) == 12
        assert book.depth_at_or_better("no_bid", 0.44) == 4
        assert book.depth_at_or_better("no_bid", 0.41) == 18  # all three

    def test_depth_at_or_better_yes_ask(self):
        book = self._book()
        # YES asks (cents): 56 (qty 4), 57 (qty 8), 59 (qty 6)
        # "Better than 0.57" means cheaper-or-equal: 56 + 57 = 4 + 8 = 12
        assert book.depth_at_or_better("yes_ask", 0.57) == 12
        # ≤ 0.56: just 56¢ = 4
        assert book.depth_at_or_better("yes_ask", 0.56) == 4
        # ≤ 0.59: all three = 4 + 8 + 6 = 18
        assert book.depth_at_or_better("yes_ask", 0.59) == 18
        # ≤ 0.50: nothing (no asks below 56¢)
        assert book.depth_at_or_better("yes_ask", 0.50) == 0

    def test_unknown_side_raises(self):
        book = self._book()
        with pytest.raises(ValueError):
            book.queue_qty_at("bogus", 0.40)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# fetched_at + source provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_fetched_at_uses_now_by_default(self):
        before = time.time()
        book = parse_kalshi_orderbook("T1", {"orderbook": {"yes": [], "no": []}})
        after = time.time()
        assert book is not None
        assert before <= book.fetched_at <= after

    def test_fetched_at_explicit(self):
        book = parse_kalshi_orderbook(
            "T1",
            {"orderbook": {"yes": [], "no": []}},
            fetched_at=1700000000.0,
        )
        assert book.fetched_at == 1700000000.0

    def test_source_default_rest(self):
        book = parse_kalshi_orderbook("T1", {"orderbook": {"yes": [], "no": []}})
        assert book.source == "rest"

    def test_source_override(self):
        book = parse_kalshi_orderbook(
            "T1",
            {"orderbook": {"yes": [], "no": []}},
            source="ws",
        )
        assert book.source == "ws"


# ---------------------------------------------------------------------------
# Direct synthesis helper
# ---------------------------------------------------------------------------

class TestSynthesizeYesAsks:
    def test_basic(self):
        no_bids = (
            BookLevel(price=0.43, quantity=8),
            BookLevel(price=0.41, quantity=10),
        )
        asks = _synthesize_yes_asks(no_bids)
        # 1-0.43=0.57 (qty 8), 1-0.41=0.59 (qty 10), ascending by price
        assert asks == (
            BookLevel(price=0.57, quantity=8),
            BookLevel(price=0.59, quantity=10),
        )

    def test_empty(self):
        assert _synthesize_yes_asks(()) == ()


# ---------------------------------------------------------------------------
# REST decimal-string parsing — the Kalshi `/markets/{ticker}/orderbook`
# endpoint returns levels as decimal-dollar strings, not integer cents.
# Discovered during the controlled paper-maker test pass:
#   "yes": [["0.0500", "300935.00"], ["0.0600", "12.00"], ...]
# Previously these were silently dropped because the parser did int(entry[0]).
# ---------------------------------------------------------------------------

class TestRestDecimalStringFormat:
    def test_observed_yes_sample(self):
        """Exact shape observed against the live Kalshi REST endpoint."""
        payload = {"orderbook": {
            "yes": [
                ["0.0500", "300935.00"],
                ["0.0600", "12.00"],
                ["0.0700", "189083.00"],
            ],
            "no": [],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        # Sorted descending by price (best YES bid first).
        prices = [lv.price for lv in book.yes_bids]
        assert prices == [pytest.approx(0.07), pytest.approx(0.06), pytest.approx(0.05)]
        assert book.best_yes_bid() == pytest.approx(0.07)
        # queue_qty_at preserves quantity from the decimal-string source.
        assert book.queue_qty_at("yes_bid", 0.05) == 300935
        assert book.queue_qty_at("yes_bid", 0.06) == 12
        assert book.queue_qty_at("yes_bid", 0.07) == 189083

    def test_observed_no_sample_synthesizes_yes_ask(self):
        """NO bid 0.43 ⇒ YES ask 0.57; quantities preserved."""
        payload = {"orderbook": {
            "yes": [],
            "no": [["0.4300", "8.00"], ["0.4100", "10.00"]],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.best_yes_ask() == pytest.approx(0.57)
        # Ascending by ask price; quantities flow through.
        ask_prices = [lv.price for lv in book.yes_asks]
        assert ask_prices == [pytest.approx(0.57), pytest.approx(0.59)]
        ask_qtys = [lv.quantity for lv in book.yes_asks]
        assert ask_qtys == [8, 10]

    def test_decimal_qty_must_be_whole_number(self):
        """A fractional contract count is rejected, not silently rounded."""
        payload = {"orderbook": {
            "yes": [["0.05", "10.5"]],
            "no": [],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.yes_bids == ()

    def test_sub_cent_decimal_price_rejected(self):
        """`"0.005"` (half-cent) is off-tick; reject rather than round."""
        payload = {"orderbook": {
            "yes": [["0.005", "10"]],
            "no": [],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        assert book.yes_bids == ()

    def test_decimal_price_at_boundaries(self):
        """`"0.99"` is valid (99¢); `"1.00"` and `"0.00"` are out of range."""
        payload = {"orderbook": {
            "yes": [["0.99", "5"], ["1.00", "5"], ["0.00", "5"]],
            "no": [],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        prices = [lv.price for lv in book.yes_bids]
        assert prices == [pytest.approx(0.99)]

    def test_mixed_int_cents_and_decimal_strings(self):
        """A book mixing both representations is parsed consistently —
        same-cent levels collapse together regardless of source shape."""
        payload = {"orderbook": {
            "yes": [[40, 10], ["0.40", "5"], ["0.4000", "3"]],
            "no": [],
        }}
        book = parse_kalshi_orderbook("T1", payload)
        assert book is not None
        # All three resolve to 40¢; quantities sum (existing dedup behavior).
        assert len(book.yes_bids) == 1
        assert book.yes_bids[0].price == pytest.approx(0.40)
        assert book.yes_bids[0].quantity == 18


# ---------------------------------------------------------------------------
# _parse_price_to_cents — direct unit tests for every accepted form
# ---------------------------------------------------------------------------

class TestPriceParserAccepts:
    @pytest.mark.parametrize("raw,expected", [
        # Integer cents (WS shape)
        (5, 5),
        (40, 40),
        (99, 99),
        # Integer-cent strings
        ("5", 5),
        ("40", 40),
        ("99", 99),
        # Decimal-dollar strings (REST shape)
        ("0.05", 5),
        ("0.0500", 5),
        ("0.40", 40),
        ("0.4000", 40),
        ("0.99", 99),
        # Floats — dollars in (0, 1)
        (0.05, 5),
        (0.40, 40),
        (0.99, 99),
        # Floats — whole-number cents
        (5.0, 5),
        (40.0, 40),
    ])
    def test_accepts(self, raw, expected):
        assert _parse_price_to_cents(raw) == expected


class TestPriceParserRejects:
    @pytest.mark.parametrize("raw", [
        # Out of range as int cents
        0,
        100,
        -5,
        # Out of range as int-cent strings
        "0",
        "100",
        "-5",
        # Out of range as decimal-dollar strings
        "1.00",
        "0.00",
        "-0.05",
        # Off-tick (sub-cent)
        "0.005",
        0.005,
        0.0501,
        # Non-numeric strings
        "abc",
        "",
        "  ",
        # Other types
        None,
        True,        # bool subclass of int
        False,
        [5],
        {"price": 5},
    ])
    def test_rejects(self, raw):
        assert _parse_price_to_cents(raw) is None


# ---------------------------------------------------------------------------
# _parse_quantity — direct unit tests
# ---------------------------------------------------------------------------

class TestQuantityParserAccepts:
    @pytest.mark.parametrize("raw,expected", [
        (10, 10),
        (300935, 300935),
        ("10", 10),
        ("300935", 300935),
        ("300935.00", 300935),     # the production REST shape
        ("12.0", 12),
        (10.0, 10),
        (300935.0, 300935),
    ])
    def test_accepts(self, raw, expected):
        assert _parse_quantity(raw) == expected


class TestQuantityParserRejects:
    @pytest.mark.parametrize("raw", [
        0,
        -1,
        "0",
        "-1",
        "10.5",
        10.5,
        "abc",
        "",
        None,
        True,
        False,
        [10],
    ])
    def test_rejects(self, raw):
        assert _parse_quantity(raw) is None
