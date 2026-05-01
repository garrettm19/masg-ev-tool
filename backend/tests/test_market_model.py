"""
Tests for the Market Pydantic model.

Covers JSON-string parsing of array fields (outcomes, outcomePrices,
clobTokenIds) and boolean preservation for status flags.
"""
import json

from models.market import Market


class TestArrayJsonStringParsing:
    def test_outcomes_from_json_string(self):
        m = Market(id="m1", question="q", outcomes=json.dumps(["Yes", "No"]))
        assert m.outcomes == ["Yes", "No"]

    def test_outcomes_from_native_list(self):
        m = Market(id="m1", question="q", outcomes=["Yes", "No"])
        assert m.outcomes == ["Yes", "No"]

    def test_outcome_prices_from_json_string(self):
        m = Market(id="m1", question="q", outcomePrices=json.dumps(["0.42", "0.58"]))
        assert m.outcomePrices == ["0.42", "0.58"]

    def test_outcome_prices_invalid_json_returns_none(self):
        m = Market(id="m1", question="q", outcomePrices="not-json")
        assert m.outcomePrices is None


class TestClobTokenIdsParsing:
    def test_from_json_string(self):
        token_a = "12345678901234567890"
        token_b = "98765432109876543210"
        m = Market(
            id="m1",
            question="q",
            clobTokenIds=json.dumps([token_a, token_b]),
        )
        assert m.clobTokenIds == [token_a, token_b]

    def test_from_native_list(self):
        m = Market(id="m1", question="q", clobTokenIds=["a", "b"])
        assert m.clobTokenIds == ["a", "b"]

    def test_missing_defaults_to_none(self):
        m = Market(id="m1", question="q")
        assert m.clobTokenIds is None

    def test_invalid_json_returns_none(self):
        m = Market(id="m1", question="q", clobTokenIds="bogus")
        assert m.clobTokenIds is None

    def test_index_alignment_preserved(self):
        # clobTokenIds must stay parallel to outcomes/outcomePrices for
        # CLOB lookups to map the right side.
        m = Market(
            id="m1",
            question="Athletics vs. New York Yankees",
            outcomes=json.dumps(["Athletics", "New York Yankees"]),
            outcomePrices=json.dumps(["0.365", "0.635"]),
            clobTokenIds=json.dumps(["tok_athletics", "tok_yankees"]),
        )
        assert m.outcomes[0] == "Athletics"
        assert m.outcomePrices[0] == "0.365"
        assert m.clobTokenIds[0] == "tok_athletics"


class TestAcceptingOrders:
    def test_true_preserved(self):
        m = Market(id="m1", question="q", acceptingOrders=True)
        assert m.acceptingOrders is True

    def test_false_preserved(self):
        m = Market(id="m1", question="q", acceptingOrders=False)
        assert m.acceptingOrders is False

    def test_missing_defaults_to_none(self):
        m = Market(id="m1", question="q")
        assert m.acceptingOrders is None


class TestExistingFieldsUnchanged:
    def test_full_market_round_trip(self):
        m = Market(
            id="m1",
            question="Will Alcaraz beat Sinner?",
            outcomes=json.dumps(["Yes", "No"]),
            outcomePrices=json.dumps(["0.65", "0.35"]),
            category="tennis",
            liquidity=5000.0,
            volume24hr=1234.5,
            endDate="2026-06-01T18:00:00Z",
            active=True,
            closed=False,
            featured=True,
            slug="alcaraz-vs-sinner",
            event_slug="atp-french-open-2026",
            event_name="Alcaraz vs Sinner",
        )
        assert m.outcomes == ["Yes", "No"]
        assert m.outcomePrices == ["0.65", "0.35"]
        assert m.liquidity == 5000.0
        assert m.volume24hr == 1234.5
        assert m.active is True
        assert m.closed is False
        assert m.featured is True
        assert m.slug == "alcaraz-vs-sinner"
        assert m.event_slug == "atp-french-open-2026"
        assert m.event_name == "Alcaraz vs Sinner"
        # New fields default to None when absent from input
        assert m.clobTokenIds is None
        assert m.acceptingOrders is None
