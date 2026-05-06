"""
Tests for KalshiWsConsumer orderbook synthesis.

Kalshi orderbook channel publishes resting BIDS per side:
  - yes → list of [price_cents, qty] for YES bids
  - no  → list of [price_cents, qty] for NO bids

Best YES bid = max(yes prices)
Best YES ask = 100 - max(no prices)   # NO bid at 43¢ implies YES ask at 57¢

These tests cover snapshot synthesis, delta updates, empty sides,
malformed payloads, and debounce behavior.  The previous handler used
min(yes prices) as "ask" — that's the lowest YES bid, not the YES ask,
and it's wrong by definition.
"""
import asyncio
from unittest.mock import AsyncMock

from services.monitor.ws_kalshi import KalshiWsConsumer


def _snapshot(ticker: str, yes: list, no: list) -> dict:
    return {
        "type": "orderbook_snapshot",
        "msg": {"market_ticker": ticker, "yes": yes, "no": no},
    }


def _delta(ticker: str, side: str, price: int, delta: int) -> dict:
    return {
        "type": "orderbook_delta",
        "msg": {"market_ticker": ticker, "side": side, "price": price, "delta": delta},
    }


def _new_consumer(tickers: set[str]) -> tuple[KalshiWsConsumer, AsyncMock]:
    consumer = KalshiWsConsumer(api_key="test")
    consumer.watch(tickers)
    return consumer, AsyncMock()


# ---------------------------------------------------------------------------
# Best ask synthesis
# ---------------------------------------------------------------------------

class TestBestAskSynthesis:
    """Best YES ask is the complement of the highest NO bid."""

    def test_canonical_synthesis(self):
        consumer, cb = _new_consumer({"T1"})
        # yes bids at 40 (qty 10) and 42 (qty 5)  → best YES bid = 42
        # no bids at 43 (qty 8) and 41 (qty 10)   → best YES ask = 100 - 43 = 57
        msg = _snapshot("T1", yes=[[40, 10], [42, 5]], no=[[43, 8], [41, 10]])
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_bid("T1") == 42
        assert consumer._best_yes_ask("T1") == 57
        cb.assert_awaited_once_with("T1", 0.57)

    def test_does_not_use_min_yes_as_ask(self):
        """Regression: previous handler used min(yes prices) as ask.  That's
        the lowest YES *bid*, not the YES ask, and it's wrong by definition."""
        consumer, cb = _new_consumer({"T1"})
        # yes bids: 35, 40, 42 — old handler would have called this "ask=35"
        # no bids: 50           → correct YES ask = 100 - 50 = 50
        msg = _snapshot("T1", yes=[[35, 1], [40, 5], [42, 8]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_ask("T1") == 50
        # Callback fires with the correct YES ask (0.50), NOT min(yes)/100 (0.35)
        cb.assert_awaited_once_with("T1", 0.50)

    def test_zero_qty_levels_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        # qty=0 levels should be dropped from both sides
        msg = _snapshot("T1", yes=[[40, 10], [42, 0]], no=[[50, 10], [55, 0]])
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_bid("T1") == 40  # not 42
        assert consumer._best_yes_ask("T1") == 50  # 100 - 50, not 100 - 55

    def test_negative_qty_levels_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        msg = _snapshot("T1", yes=[[40, 10], [42, -3]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_bid("T1") == 40
        assert consumer._best_yes_ask("T1") == 50


# ---------------------------------------------------------------------------
# Empty / missing sides
# ---------------------------------------------------------------------------

class TestEmptySides:
    def test_empty_no_side_no_callback(self):
        consumer, cb = _new_consumer({"T1"})
        msg = _snapshot("T1", yes=[[40, 10]], no=[])
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_bid("T1") == 40
        assert consumer._best_yes_ask("T1") is None
        cb.assert_not_awaited()

    def test_empty_yes_side_still_synthesizes_ask(self):
        consumer, cb = _new_consumer({"T1"})
        msg = _snapshot("T1", yes=[], no=[[43, 5]])
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_bid("T1") is None
        assert consumer._best_yes_ask("T1") == 57
        cb.assert_awaited_once_with("T1", 0.57)

    def test_both_sides_empty_no_crash(self):
        consumer, cb = _new_consumer({"T1"})
        msg = _snapshot("T1", yes=[], no=[])
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_bid("T1") is None
        assert consumer._best_yes_ask("T1") is None
        cb.assert_not_awaited()

    def test_missing_arrays_no_crash(self):
        """Snapshot message missing yes/no fields should not crash."""
        consumer, cb = _new_consumer({"T1"})
        msg = {"type": "orderbook_snapshot", "msg": {"market_ticker": "T1"}}
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_ask("T1") is None
        cb.assert_not_awaited()

    def test_malformed_levels_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        # Strings, short tuples, and non-list entries should be skipped.
        msg = _snapshot(
            "T1",
            yes=[[40, 10], ["bad", "data"], [42], [43, 5]],
            no=[[50, 10]],
        )
        asyncio.run(consumer._handle_message(msg, cb))

        assert consumer._best_yes_bid("T1") == 43  # only the two valid YES entries
        assert consumer._best_yes_ask("T1") == 50


# ---------------------------------------------------------------------------
# Delta path
# ---------------------------------------------------------------------------

class TestDeltaPath:
    """Delta messages incrementally update the per-ticker book and re-synthesize."""

    def test_delta_updates_no_side_and_changes_ask(self):
        consumer, cb = _new_consumer({"T1"})
        snap = _snapshot("T1", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(snap, cb))
        assert consumer._best_yes_ask("T1") == 50

        # New NO bid at 53 (more aggressive) → YES ask drops 50 → 47
        d = _delta("T1", side="no", price=53, delta=5)
        asyncio.run(consumer._handle_message(d, cb))
        assert consumer._best_yes_ask("T1") == 47

        # Two callbacks: ask=50 then ask=47
        assert cb.await_count == 2

    def test_delta_removes_level_when_qty_drops_to_zero(self):
        consumer, cb = _new_consumer({"T1"})
        snap = _snapshot("T1", yes=[[40, 10]], no=[[50, 5], [48, 10]])
        asyncio.run(consumer._handle_message(snap, cb))
        assert consumer._best_yes_ask("T1") == 50  # 100 - 50

        # Cancel all 5 contracts at 50 → top NO bid drops to 48 → YES ask = 52
        d = _delta("T1", side="no", price=50, delta=-5)
        asyncio.run(consumer._handle_message(d, cb))
        assert consumer._best_yes_ask("T1") == 52

    def test_delta_for_yes_side_updates_bid(self):
        consumer, cb = _new_consumer({"T1"})
        snap = _snapshot("T1", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(snap, cb))
        assert consumer._best_yes_bid("T1") == 40

        d = _delta("T1", side="yes", price=42, delta=3)
        asyncio.run(consumer._handle_message(d, cb))
        assert consumer._best_yes_bid("T1") == 42

    def test_delta_for_unwatched_ticker_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        d = _delta("T2", side="no", price=50, delta=5)
        asyncio.run(consumer._handle_message(d, cb))

        assert consumer._best_yes_ask("T2") is None
        cb.assert_not_awaited()

    def test_delta_with_invalid_side_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        snap = _snapshot("T1", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(snap, cb))

        d = {
            "type": "orderbook_delta",
            "msg": {"market_ticker": "T1", "side": "bogus", "price": 50, "delta": 5},
        }
        asyncio.run(consumer._handle_message(d, cb))

        # Book unchanged
        assert consumer._best_yes_ask("T1") == 50

    def test_delta_with_invalid_payload_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        snap = _snapshot("T1", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(snap, cb))

        d = {
            "type": "orderbook_delta",
            "msg": {"market_ticker": "T1", "side": "no", "price": "bad", "delta": 5},
        }
        asyncio.run(consumer._handle_message(d, cb))
        assert consumer._best_yes_ask("T1") == 50  # unchanged


# ---------------------------------------------------------------------------
# Debounce
# ---------------------------------------------------------------------------

class TestDebounce:
    def test_repeats_below_threshold_suppressed(self):
        consumer, cb = _new_consumer({"T1"})
        snap1 = _snapshot("T1", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(snap1, cb))

        # Same best ask (50¢) — second snapshot must NOT re-fire callback.
        snap2 = _snapshot("T1", yes=[[40, 12]], no=[[50, 12]])
        asyncio.run(consumer._handle_message(snap2, cb))

        assert cb.await_count == 1

    def test_meaningful_change_triggers_callback(self):
        consumer, cb = _new_consumer({"T1"})

        snap1 = _snapshot("T1", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(snap1, cb))

        # NO bid jumps 50 → 55 (more aggressive) → YES ask drops 50 → 45
        snap2 = _snapshot("T1", yes=[[40, 10]], no=[[55, 10]])
        asyncio.run(consumer._handle_message(snap2, cb))

        assert cb.await_count == 2
        cb.assert_any_await("T1", 0.50)
        cb.assert_any_await("T1", 0.45)


# ---------------------------------------------------------------------------
# Other lifecycle / housekeeping
# ---------------------------------------------------------------------------

class TestUnwatchAll:
    def test_unwatch_all_clears_books_and_prices(self):
        consumer, cb = _new_consumer({"T1"})
        snap = _snapshot("T1", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(snap, cb))
        assert consumer._best_yes_ask("T1") == 50

        consumer.unwatch_all()
        assert consumer._best_yes_ask("T1") is None
        assert consumer._best_yes_bid("T1") is None
        assert consumer._last_prices == {}
        assert consumer._watched_tickers == set()


class TestUnknownMessage:
    def test_other_message_types_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        msg = {"type": "ticker", "msg": {"market_ticker": "T1", "price": 50}}
        asyncio.run(consumer._handle_message(msg, cb))
        cb.assert_not_awaited()

    def test_message_for_unwatched_ticker_ignored(self):
        consumer, cb = _new_consumer({"T1"})
        msg = _snapshot("T2", yes=[[40, 10]], no=[[50, 10]])
        asyncio.run(consumer._handle_message(msg, cb))
        cb.assert_not_awaited()
        assert consumer._best_yes_ask("T2") is None
