"""
Tests for maker policy: which taker rule failures block maker eligibility,
and which are intentionally bypassed.

The architectural invariant under test: maker eligibility consumes Pass A
``MarketFeatures`` directly and runs its own policy.  It does NOT depend on
``EvaluatedOpportunity.status == "BUY"``.  A taker SKIP for ``NO_EDGE`` —
the prediction-market ask too expensive for taker — must still be
maker-eligible if the safety rules pass and a maker bid inside the spread
clears the edge bar.

Compatible (do NOT block maker):
    NO_EDGE                    — taker entry price too high (whole point)
    EDGE_BELOW_THRESHOLD       — thin taker edge (maker can clear)

Everything else in POLICY_TABLE blocks maker.
"""
from __future__ import annotations

import time

import pytest

from services.engine_config import EngineConfig
from services.maker.policy import EXCLUDED_TAKER_RULES
from services.maker.planner import plan_maker_proposal
from services.rule_engine import evaluate_rules

# Reuse fixtures from the math test file to avoid duplicating the
# ~30-field MarketFeatures factory.  Both files are collected by pytest;
# importing the helper functions across files is safe.
from tests.test_maker_planner_math import _book, _features, _maker_cfg


# ---------------------------------------------------------------------------
# Excluded taker rules — maker must still run when these (and only these) fail
# ---------------------------------------------------------------------------

class TestExcludedTakerRules:
    def test_excluded_set_is_only_two_rules(self):
        """Regression guard: only the two entry-price rules are bypassed.
        Any addition to this set must be deliberate."""
        assert EXCLUDED_TAKER_RULES == frozenset({"positive_edge", "edge_threshold"})

    def test_no_edge_does_not_block_maker(self):
        """Canonical case: taker SKIP for NO_EDGE → maker still eligible."""
        # ask=0.90, p_true=0.50 → taker edge = 0.50 - 0.91 = -0.41 → SKIP
        f = _features(pm_price=0.90, pm_price_effective=0.91, edge=-0.41)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)

        # Confirm taker classification
        status, _ = evaluate_rules(f, cfg)
        assert status == "SKIP"
        assert "NO_EDGE" in f.reject_reasons

        # Maker rescues
        b = _book(best_bid=0.40, best_ask=0.90)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is True
        assert prop.proposed_price == pytest.approx(0.41)
        assert prop.estimated_maker_edge == pytest.approx(0.08)
        # Audit fields preserve the taker verdict for observability
        assert prop.taker_status_at_planning == "SKIP"
        assert "NO_EDGE" in prop.taker_reject_reasons

    def test_edge_below_threshold_does_not_block_maker(self):
        """Taker WATCH for EDGE_BELOW_THRESHOLD only → maker eligible."""
        # ask=0.47, p_true=0.50 → taker edge = 0.50 - 0.48 = 0.02 < 0.05 min
        f = _features(pm_price=0.47, pm_price_effective=0.48, edge=0.02)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)

        status, _ = evaluate_rules(f, cfg)
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons

        b = _book(best_bid=0.40, best_ask=0.47)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        # max_bid=0.44, candidate=0.41, proposed=0.41, inside (0.40, 0.47)
        assert prop.eligible is True
        assert prop.proposed_price == pytest.approx(0.41)
        assert prop.taker_status_at_planning == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in prop.taker_downgrade_reasons


# ---------------------------------------------------------------------------
# Safety rule failures — every one of these must block maker
# ---------------------------------------------------------------------------

class TestSafetyFailuresBlockMaker:
    """Each safety-related taker rule failure must block maker eligibility.

    These rules are inherited from POLICY_TABLE via inherited_taker_rules;
    failure = ineligible, regardless of the math.
    """

    def _plan(self, features_overrides: dict, cfg_overrides: dict | None = None):
        f = _features(**features_overrides)
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(**(cfg_overrides or {}))
        return plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

    def test_no_bookmaker_data_blocks(self):
        prop = self._plan({"has_bookmaker_data": False})
        assert prop.eligible is False
        assert "NO_BOOKMAKER_DATA" in prop.rejection_reasons

    def test_name_mismatch_blocks(self):
        prop = self._plan({"name_match_score": 0.0})
        assert prop.eligible is False
        assert "NAME_MISMATCH" in prop.rejection_reasons

    def test_outcome_not_aligned_blocks(self):
        prop = self._plan({"outcome_aligned": False})
        assert prop.eligible is False
        assert "OUTCOME_NOT_ALIGNED" in prop.rejection_reasons

    def test_confidence_below_survival_blocks(self):
        prop = self._plan(
            {"event_match_confidence": 0.50},
            {"survival_threshold": 0.85},
        )
        assert prop.eligible is False
        assert "CONFIDENCE_BELOW_SURVIVAL" in prop.rejection_reasons

    def test_date_too_far_blocks(self):
        # NBA per-sport limit is 12h; 200h is far past
        prop = self._plan(
            {"sport": "basketball_nba", "date_delta_hours": 200.0,
             "fanduel_line_width": 0.20},
        )
        assert prop.eligible is False
        assert "DATE_TOO_FAR" in prop.rejection_reasons

    def test_ambiguity_gap_blocks(self):
        prop = self._plan(
            {
                "competing_matches": 2,
                "confidence_gap": 0.01,
                "second_best_confidence": 0.94,
                "second_best_event_id": "E2",
            },
            {"min_confidence_gap": 0.05, "max_competing_matches": 5},
        )
        assert prop.eligible is False
        assert "AMBIGUOUS_MATCH_GAP" in prop.rejection_reasons

    def test_excess_competing_matches_blocks(self):
        prop = self._plan(
            {
                "competing_matches": 3,
                "confidence_gap": 0.50,
                "second_best_confidence": 0.45,
                "second_best_event_id": "E2",
            },
            {"min_confidence_gap": 0.05, "max_competing_matches": 1},
        )
        assert prop.eligible is False
        assert "EXCESS_COMPETING_MATCHES" in prop.rejection_reasons

    def test_prices_inconsistent_blocks(self):
        prop = self._plan({"prices_internally_consistent": False})
        assert prop.eligible is False
        assert "PRICES_INCONSISTENT" in prop.rejection_reasons

    def test_low_true_prob_blocks(self):
        # Long-tail dog policy is preserved for maker too
        prop = self._plan(
            {"p_true": 0.25, "p_true_other": 0.75},
            {"min_true_probability": 0.40},
        )
        assert prop.eligible is False
        assert "TRUE_PROB_TOO_LOW" in prop.rejection_reasons

    def test_event_live_blocks(self):
        prop = self._plan({"is_live": True})
        assert prop.eligible is False
        assert "EVENT_LIVE" in prop.rejection_reasons

    def test_metadata_incomplete_blocks(self):
        prop = self._plan(
            {"has_outcome_prices": False},
        )
        assert prop.eligible is False
        assert "INCOMPLETE_METADATA" in prop.rejection_reasons


# ---------------------------------------------------------------------------
# Rule trace shape
# ---------------------------------------------------------------------------

class TestMakerPolicyTraceShape:
    def test_excluded_taker_rules_not_in_trace(self):
        """The two excluded rules must NOT appear in the maker rule trace —
        they're explicitly bypassed."""
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        rule_names = {r.rule_name for r in prop.rule_evaluations}
        assert "positive_edge" not in rule_names
        assert "edge_threshold" not in rule_names

    def test_inherited_safety_rules_in_trace(self):
        """Inherited taker safety rules must appear in the maker trace
        so the audit shows they were checked."""
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        rule_names = {r.rule_name for r in prop.rule_evaluations}
        for inherited in (
            "name_match",
            "outcome_alignment",
            "has_bookmaker",
            "confidence_survival",
            "min_true_prob",
            "date_not_stale",
            "price_prob_coherence",
            "metadata_complete",
            "prices_consistent",
        ):
            assert inherited in rule_names, f"missing inherited rule: {inherited}"

    def test_maker_only_rules_in_trace(self):
        """Maker-specific rules must appear in the trace too."""
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        rule_names = {r.rule_name for r in prop.rule_evaluations}
        for maker_rule in (
            "maker_enabled",
            "platform_in_scope",
            "market_type_in_scope",
            "book_fresh",
            "fd_fresh",
            "book_not_crossed",
            "spread_wide_enough",
            "suggested_bid_inside_spread",
            "proposed_below_max_bid",
            "maker_edge_meets_min",
            "maker_edge_plausible",
        ):
            assert maker_rule in rule_names, f"missing maker rule: {maker_rule}"

    def test_full_trace_when_eligible(self):
        """Eligible proposal: every rule in the trace passed."""
        f = _features()
        b = _book(best_bid=0.40, best_ask=0.90)
        cfg = EngineConfig(min_edge=0.05, cost_buffer=0.01)
        prop = plan_maker_proposal(f, b, cfg, _maker_cfg(), now=time.time())

        assert prop.eligible is True
        for r in prop.rule_evaluations:
            assert r.passed is True, f"rule {r.rule_name} failed unexpectedly"


# ---------------------------------------------------------------------------
# Future-proofing: adding a new taker rule should be inherited automatically
# ---------------------------------------------------------------------------

class TestInheritsFutureTakerRules:
    def test_inherited_rules_match_policy_table_minus_excluded(self):
        """inherited_taker_rules() must equal POLICY_TABLE minus the
        excluded set — proving new taker rules flow into maker eligibility
        unless they're explicitly added to EXCLUDED_TAKER_RULES."""
        from services.maker.policy import inherited_taker_rules
        from services.rule_engine import POLICY_TABLE

        inherited_names = {r.rule_name for r in inherited_taker_rules()}
        all_taker_names = {r.rule_name for r in POLICY_TABLE}

        assert inherited_names == all_taker_names - EXCLUDED_TAKER_RULES
