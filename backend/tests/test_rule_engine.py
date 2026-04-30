"""
Tests for services.rule_engine — per-rule pass/fail coverage + classification.

Every rule in the policy table has at least one test proving:
  - when it passes
  - when it fails
  - what status it produces
"""
import pytest
from services.engine_config import EngineConfig
from services.rule_engine import (
    MarketFeatures,
    POLICY_TABLE,
    evaluate_rules,
    compute_kelly,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_cfg() -> EngineConfig:
    return EngineConfig()


def _buy_ready(**overrides) -> MarketFeatures:
    """Return a MarketFeatures that passes ALL 23 rules (→ BUY)."""
    defaults = dict(
        platform="polymarket",
        market_id="test",
        sport="tennis_atp",
        event_label="Alcaraz vs Sinner",
        market_type="h2h",
        side="Alcaraz",
        question="Will Alcaraz beat Sinner?",
        pm_price=0.55,
        pm_price_no=0.45,
        pm_price_effective=0.56,
        price_in_range=True,
        is_live=False,
        has_bookmaker_data=True,
        name_match_score=1.0,
        outcome_aligned=True,
        event_match_confidence=0.95,
        match_quality="verified",
        p_true=0.65,
        edge=0.09,
        fanduel_overround=0.02,
        fanduel_line_width=0.20,
        fanduel_line_width_label="Moderate",
        fanduel_confidence_label="High",
        line_match_exact=True,
        unit_match=True,
        side_match=True,
        fd_odds=-180,
        # Ambiguity — clean
        competing_matches=1,
        confidence_gap=1.0,
        has_shared_last_name=False,
        matched_event_id="ev1",
        second_best_event_id="",
        best_match_confidence=0.95,
        second_best_confidence=0.0,
        home_last_name_collision=False,
        away_last_name_collision=False,
        # Metadata — complete
        has_end_date=True,
        has_outcome_prices=True,
        prices_internally_consistent=True,
        # Observability
        home_tokens=("carlos", "alcaraz"),
        away_tokens=("jannik", "sinner"),
        question_tokens=("will", "alcaraz", "beat", "sinner"),
    )
    defaults.update(overrides)
    return MarketFeatures(**defaults)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

class TestBaselineClassification:
    def test_perfect_buy(self):
        f = _buy_ready()
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"
        assert f.reject_reasons == []
        assert f.downgrade_reasons == []

    def test_perfect_buy_kelly(self):
        f = _buy_ready()
        evaluate_rules(f, _default_cfg())
        compute_kelly(f, _default_cfg())
        assert f.kelly_fraction > 0
        assert f.kelly_full > 0
        assert f.kelly_full <= 0.25

    def test_rule_count(self):
        """Ensure we track every rule — update this if rules are added/removed."""
        assert len(POLICY_TABLE) == 23


# ---------------------------------------------------------------------------
# CRITICAL rules (fail → SKIP)
# ---------------------------------------------------------------------------

class TestPriceRange:
    def test_pass(self):
        f = _buy_ready(price_in_range=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail(self):
        f = _buy_ready(price_in_range=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "PRICE_OUT_OF_RANGE" in f.reject_reasons


class TestNotLive:
    def test_pass(self):
        f = _buy_ready(is_live=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail(self):
        f = _buy_ready(is_live=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "EVENT_LIVE" in f.reject_reasons

    def test_live_never_becomes_buy(self):
        """Safety: even with perfect edge, live events cannot be BUY."""
        f = _buy_ready(is_live=True, edge=0.50, p_true=0.99)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


class TestHasBookmaker:
    def test_pass(self):
        f = _buy_ready(has_bookmaker_data=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail(self):
        f = _buy_ready(has_bookmaker_data=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "NO_BOOKMAKER_DATA" in f.reject_reasons


class TestNameMatch:
    def test_pass(self):
        f = _buy_ready(name_match_score=1.0)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail_partial(self):
        f = _buy_ready(name_match_score=0.5)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "NAME_MISMATCH" in f.reject_reasons

    def test_fail_zero(self):
        f = _buy_ready(name_match_score=0.0)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


class TestOutcomeAlignment:
    def test_pass(self):
        f = _buy_ready(outcome_aligned=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail(self):
        f = _buy_ready(outcome_aligned=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "OUTCOME_NOT_ALIGNED" in f.reject_reasons

    def test_ambiguous_mapping_never_buys(self):
        """Safety: unaligned outcome must never BUY."""
        f = _buy_ready(outcome_aligned=False, edge=0.50)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


class TestConfidenceSurvival:
    def test_pass_at_threshold(self):
        f = _buy_ready(event_match_confidence=0.85)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "CONFIDENCE_BELOW_SURVIVAL" not in f.reject_reasons

    def test_fail_below_survival(self):
        f = _buy_ready(event_match_confidence=0.84)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "CONFIDENCE_BELOW_SURVIVAL" in f.reject_reasons

    def test_pass_above_buy(self):
        f = _buy_ready(event_match_confidence=0.95)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_just_below_survival(self):
        f = _buy_ready(event_match_confidence=0.849)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


class TestLineMatch:
    def test_pass_h2h(self):
        f = _buy_ready(market_type="h2h", line_match_exact=False)
        _, results = evaluate_rules(f, _default_cfg())
        line_result = [r for r in results if r.rule_name == "line_match"][0]
        assert line_result.passed is True

    def test_pass_totals(self):
        f = _buy_ready(market_type="totals", line_match_exact=True)
        _, results = evaluate_rules(f, _default_cfg())
        line_result = [r for r in results if r.rule_name == "line_match"][0]
        assert line_result.passed is True

    def test_fail_totals(self):
        f = _buy_ready(market_type="totals", line_match_exact=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "LINE_MISMATCH" in f.reject_reasons

    def test_fail_handicap(self):
        f = _buy_ready(market_type="handicap", line_match_exact=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "LINE_MISMATCH" in f.reject_reasons

    def test_line_mismatch_never_passes(self):
        """Safety: mismatched totals line must always SKIP."""
        f = _buy_ready(market_type="totals", line_match_exact=False, edge=0.50)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


class TestUnitMatch:
    def test_pass_h2h(self):
        f = _buy_ready(market_type="h2h", unit_match=False)
        _, results = evaluate_rules(f, _default_cfg())
        unit_result = [r for r in results if r.rule_name == "unit_match"][0]
        assert unit_result.passed is True

    def test_fail_totals_set_vs_game(self):
        f = _buy_ready(market_type="totals", unit_match=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "UNIT_MISMATCH" in f.reject_reasons

    def test_fail_handicap_unit(self):
        f = _buy_ready(market_type="handicap", unit_match=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "UNIT_MISMATCH" in f.reject_reasons


class TestSideMatch:
    def test_pass_h2h(self):
        f = _buy_ready(market_type="h2h", side_match=False)
        _, results = evaluate_rules(f, _default_cfg())
        side_result = [r for r in results if r.rule_name == "side_match"][0]
        assert side_result.passed is True

    def test_fail_handicap_wrong_favored(self):
        f = _buy_ready(market_type="handicap", side_match=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "SIDE_MISMATCH" in f.reject_reasons

    def test_pass_handicap(self):
        f = _buy_ready(market_type="handicap", side_match=True)
        _, results = evaluate_rules(f, _default_cfg())
        side_result = [r for r in results if r.rule_name == "side_match"][0]
        assert side_result.passed is True

    def test_wrong_side_never_passes(self):
        """Safety: wrong handicap side must always SKIP."""
        f = _buy_ready(market_type="handicap", side_match=False, edge=0.50)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


class TestPositiveEdge:
    def test_pass(self):
        f = _buy_ready(edge=0.01)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "NO_EDGE" not in f.reject_reasons

    def test_fail_zero(self):
        f = _buy_ready(edge=0.0)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "NO_EDGE" in f.reject_reasons

    def test_fail_negative(self):
        f = _buy_ready(edge=-0.05)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "NO_EDGE" in f.reject_reasons

    def test_no_edge_never_passes(self):
        """Safety: negative edge must never pass."""
        f = _buy_ready(edge=-0.01, p_true=0.60)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


class TestMinTrueProb:
    def test_pass_at_boundary(self):
        f = _buy_ready(p_true=0.40)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "TRUE_PROB_TOO_LOW" not in f.reject_reasons

    def test_fail(self):
        f = _buy_ready(p_true=0.39)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "TRUE_PROB_TOO_LOW" in f.reject_reasons

    def test_below_floor_never_passes(self):
        """Safety: sub-floor p_true must never pass."""
        f = _buy_ready(p_true=0.35, edge=0.20)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"


# ---------------------------------------------------------------------------
# DOWNGRADE rules (fail → WATCH)
# ---------------------------------------------------------------------------

class TestConfidenceBuy:
    def test_pass_above_buy(self):
        f = _buy_ready(event_match_confidence=0.90)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail_between_survival_and_buy(self):
        f = _buy_ready(event_match_confidence=0.87)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "CONFIDENCE_BELOW_BUY" in f.downgrade_reasons

    def test_exactly_at_buy_threshold(self):
        f = _buy_ready(event_match_confidence=0.90)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_just_below_buy(self):
        f = _buy_ready(event_match_confidence=0.899)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"


class TestEdgeThreshold:
    def test_pass_normal_market(self):
        f = _buy_ready(edge=0.05, fanduel_line_width=0.20)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail_normal_market(self):
        f = _buy_ready(edge=0.04, fanduel_line_width=0.20)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons

    def test_pass_wide_market(self):
        f = _buy_ready(edge=0.08, fanduel_line_width=0.40)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "EDGE_BELOW_THRESHOLD" not in f.downgrade_reasons

    def test_fail_wide_market(self):
        f = _buy_ready(edge=0.07, fanduel_line_width=0.40)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons

    def test_wide_at_boundary(self):
        """Line width at the boundary (0.35) uses normal threshold."""
        f = _buy_ready(edge=0.05, fanduel_line_width=0.35)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_wide_just_above_boundary(self):
        f = _buy_ready(edge=0.05, fanduel_line_width=0.36)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons


class TestFDConfidence:
    def test_pass_high(self):
        f = _buy_ready(fanduel_confidence_label="High")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_pass_medium(self):
        f = _buy_ready(fanduel_confidence_label="Medium")
        status, _ = evaluate_rules(f, _default_cfg())
        assert "FD_CONFIDENCE_LOW" not in f.downgrade_reasons

    def test_fail_low(self):
        f = _buy_ready(fanduel_confidence_label="Low")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "FD_CONFIDENCE_LOW" in f.downgrade_reasons

    def test_low_is_watch_not_skip(self):
        """FD Low confidence should downgrade, not hard-reject."""
        f = _buy_ready(fanduel_confidence_label="Low")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "FD_CONFIDENCE_LOW" not in f.reject_reasons


# ---------------------------------------------------------------------------
# AMBIGUITY rules (DOWNGRADE)
# ---------------------------------------------------------------------------

class TestConfidenceGap:
    def test_pass_single_match(self):
        f = _buy_ready(competing_matches=1, confidence_gap=1.0)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_pass_sufficient_gap(self):
        f = _buy_ready(competing_matches=2, confidence_gap=0.10)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "AMBIGUOUS_MATCH_GAP" not in f.downgrade_reasons

    def test_fail_narrow_gap(self):
        f = _buy_ready(competing_matches=2, confidence_gap=0.02)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "AMBIGUOUS_MATCH_GAP" in f.downgrade_reasons

    def test_exactly_at_threshold(self):
        f = _buy_ready(competing_matches=2, confidence_gap=0.05)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "AMBIGUOUS_MATCH_GAP" not in f.downgrade_reasons

    def test_just_below_threshold(self):
        f = _buy_ready(competing_matches=2, confidence_gap=0.049)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "AMBIGUOUS_MATCH_GAP" in f.downgrade_reasons


class TestSharedLastName:
    def test_pass_no_shared(self):
        f = _buy_ready(has_shared_last_name=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail_shared(self):
        f = _buy_ready(has_shared_last_name=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "SHARED_LAST_NAME" in f.downgrade_reasons


class TestCompetingMatches:
    def test_pass_single(self):
        f = _buy_ready(competing_matches=1)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail_multiple(self):
        f = _buy_ready(competing_matches=3)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EXCESS_COMPETING_MATCHES" in f.downgrade_reasons

    def test_exactly_at_max(self):
        f = _buy_ready(competing_matches=1)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "EXCESS_COMPETING_MATCHES" not in f.downgrade_reasons

    def test_two_matches(self):
        f = _buy_ready(competing_matches=2)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "EXCESS_COMPETING_MATCHES" in f.downgrade_reasons


class TestLastNameCollision:
    def test_pass_no_collision(self):
        f = _buy_ready(home_last_name_collision=False, away_last_name_collision=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail_home_collision(self):
        f = _buy_ready(home_last_name_collision=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "LAST_NAME_COLLISION" in f.downgrade_reasons

    def test_fail_away_collision(self):
        f = _buy_ready(away_last_name_collision=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "LAST_NAME_COLLISION" in f.downgrade_reasons


# ---------------------------------------------------------------------------
# METADATA rules (DOWNGRADE)
# ---------------------------------------------------------------------------

class TestMetadataComplete:
    def test_pass_all_present(self):
        f = _buy_ready(has_end_date=True, has_outcome_prices=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_pass_missing_end_date_not_required(self):
        """Default config does not require end_date."""
        f = _buy_ready(has_end_date=False, has_outcome_prices=True)
        cfg = _default_cfg()
        status, _ = evaluate_rules(f, cfg)
        assert "INCOMPLETE_METADATA" not in f.downgrade_reasons

    def test_fail_missing_end_date_when_required(self):
        f = _buy_ready(has_end_date=False, has_outcome_prices=True)
        cfg = EngineConfig(require_end_date=True)
        status, _ = evaluate_rules(f, cfg)
        assert status == "WATCH"
        assert "INCOMPLETE_METADATA" in f.downgrade_reasons

    def test_fail_missing_prices(self):
        f = _buy_ready(has_outcome_prices=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "INCOMPLETE_METADATA" in f.downgrade_reasons


class TestPricesConsistent:
    def test_pass_consistent(self):
        f = _buy_ready(prices_internally_consistent=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_fail_inconsistent(self):
        f = _buy_ready(prices_internally_consistent=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "PRICES_INCONSISTENT" in f.downgrade_reasons


# ---------------------------------------------------------------------------
# Compound scenarios
# ---------------------------------------------------------------------------

class TestCompoundScenarios:
    def test_obvious_buy(self):
        f = _buy_ready(
            event_match_confidence=0.95,
            edge=0.10,
            p_true=0.65,
            fanduel_line_width=0.10,
            fanduel_confidence_label="High",
            competing_matches=1,
        )
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"
        assert f.reject_reasons == []
        assert f.downgrade_reasons == []

    def test_obvious_skip_live(self):
        f = _buy_ready(is_live=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"

    def test_obvious_skip_no_edge(self):
        f = _buy_ready(edge=-0.03, p_true=0.50)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"

    def test_borderline_watch_confidence(self):
        f = _buy_ready(event_match_confidence=0.88)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "CONFIDENCE_BELOW_BUY" in f.downgrade_reasons
        assert len(f.reject_reasons) == 0

    def test_borderline_watch_edge(self):
        f = _buy_ready(edge=0.03)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons

    def test_borderline_watch_fd_low(self):
        f = _buy_ready(fanduel_confidence_label="Low")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "FD_CONFIDENCE_LOW" in f.downgrade_reasons

    def test_multiple_downgrades_still_watch(self):
        f = _buy_ready(
            event_match_confidence=0.87,
            fanduel_confidence_label="Low",
            edge=0.03,
            competing_matches=3,
            prices_internally_consistent=False,
        )
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert len(f.downgrade_reasons) >= 4

    def test_critical_overrides_downgrade(self):
        f = _buy_ready(is_live=True, fanduel_confidence_label="Low")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "EVENT_LIVE" in f.reject_reasons

    def test_duplicate_event_candidates(self):
        f = _buy_ready(
            competing_matches=2,
            confidence_gap=0.03,
            has_shared_last_name=True,
        )
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "AMBIGUOUS_MATCH_GAP" in f.downgrade_reasons
        assert "SHARED_LAST_NAME" in f.downgrade_reasons

    def test_wrong_handicap_side_is_skip(self):
        f = _buy_ready(market_type="handicap", side_match=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "SIDE_MISMATCH" in f.reject_reasons

    def test_totals_line_mismatch_is_skip(self):
        f = _buy_ready(market_type="totals", line_match_exact=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "LINE_MISMATCH" in f.reject_reasons

    def test_ambiguous_mapping_with_collision(self):
        """Last name collision + shared name + narrow gap = multi-downgrade WATCH."""
        f = _buy_ready(
            home_last_name_collision=True,
            has_shared_last_name=True,
            competing_matches=2,
            confidence_gap=0.03,
        )
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "LAST_NAME_COLLISION" in f.downgrade_reasons
        assert "SHARED_LAST_NAME" in f.downgrade_reasons
        assert "AMBIGUOUS_MATCH_GAP" in f.downgrade_reasons

    def test_incomplete_metadata_with_edge(self):
        """Good edge but missing metadata → WATCH, not BUY."""
        f = _buy_ready(has_outcome_prices=False, edge=0.15)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"


# ---------------------------------------------------------------------------
# Safety invariants — these must NEVER pass
# ---------------------------------------------------------------------------

class TestSafetyInvariants:
    """Hard safety checks: these scenarios must NEVER become BUY."""

    def test_live_event_never_buys(self):
        f = _buy_ready(is_live=True)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_unresolved_side_never_buys(self):
        f = _buy_ready(market_type="handicap", side_match=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_line_mismatch_never_buys(self):
        f = _buy_ready(market_type="totals", line_match_exact=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_unit_mismatch_never_buys(self):
        f = _buy_ready(market_type="totals", unit_match=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_no_positive_edge_never_buys(self):
        f = _buy_ready(edge=0.0)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_below_prob_floor_never_buys(self):
        f = _buy_ready(p_true=0.30, edge=0.10)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_ambiguous_player_mapping_never_buys(self):
        f = _buy_ready(outcome_aligned=False)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_name_mismatch_never_buys(self):
        f = _buy_ready(name_match_score=0.5)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"

    def test_ambiguous_match_gap_never_buys(self):
        """Close competing matches should prevent BUY."""
        f = _buy_ready(competing_matches=2, confidence_gap=0.02)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status != "BUY"


# ---------------------------------------------------------------------------
# Kelly sizing
# ---------------------------------------------------------------------------

class TestKelly:
    def test_positive_edge(self):
        f = _buy_ready(edge=0.09, p_true=0.65, pm_price_effective=0.56)
        evaluate_rules(f, _default_cfg())
        compute_kelly(f, _default_cfg())
        assert f.kelly_full > 0
        assert f.kelly_fraction > 0
        assert f.kelly_fraction == pytest.approx(f.kelly_full * 0.20, abs=0.0001)

    def test_zero_edge(self):
        f = _buy_ready(edge=0.0)
        evaluate_rules(f, _default_cfg())
        compute_kelly(f, _default_cfg())
        assert f.kelly_full == 0.0
        assert f.kelly_fraction == 0.0

    def test_negative_edge(self):
        f = _buy_ready(edge=-0.05)
        evaluate_rules(f, _default_cfg())
        compute_kelly(f, _default_cfg())
        assert f.kelly_full == 0.0

    def test_kelly_capped(self):
        f = _buy_ready(edge=0.40, p_true=0.95, pm_price_effective=0.55)
        evaluate_rules(f, _default_cfg())
        compute_kelly(f, _default_cfg())
        assert f.kelly_full <= 0.25

    def test_kelly_only_for_buy(self):
        """Kelly should be computed but only BUY should act on it."""
        f = _buy_ready(edge=0.09, p_true=0.65, pm_price_effective=0.56,
                       fanduel_confidence_label="Low")
        evaluate_rules(f, _default_cfg())
        compute_kelly(f, _default_cfg())
        assert f.status == "WATCH"
        assert f.kelly_fraction > 0  # computed even for WATCH


# ---------------------------------------------------------------------------
# Config-driven threshold changes
# ---------------------------------------------------------------------------

class TestConfigOverrides:
    def test_lower_min_edge_promotes_to_buy(self):
        # NBA has per-sport min_edge=0.03, so a 3.5% edge passes
        f = _buy_ready(edge=0.035, sport="basketball_nba")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_higher_survival_threshold(self):
        f = _buy_ready(event_match_confidence=0.87)
        cfg = EngineConfig(survival_threshold=0.90, buy_threshold=0.95)
        status, _ = evaluate_rules(f, cfg)
        assert status == "SKIP"
        assert "CONFIDENCE_BELOW_SURVIVAL" in f.reject_reasons

    def test_narrower_confidence_gap_threshold(self):
        f = _buy_ready(competing_matches=2, confidence_gap=0.07)
        cfg = EngineConfig(min_confidence_gap=0.10)
        status, _ = evaluate_rules(f, cfg)
        assert status == "WATCH"
        assert "AMBIGUOUS_MATCH_GAP" in f.downgrade_reasons

    def test_require_end_date(self):
        f = _buy_ready(has_end_date=False)
        cfg = EngineConfig(require_end_date=True)
        status, _ = evaluate_rules(f, cfg)
        assert status == "WATCH"
        assert "INCOMPLETE_METADATA" in f.downgrade_reasons


# ---------------------------------------------------------------------------
# Per-sport edge thresholds
# ---------------------------------------------------------------------------

class TestPerSportEdgeThreshold:
    """Per-sport min_edge from SportConfig controls the edge threshold rule."""

    def test_nba_passes_at_3_5_percent(self):
        """NBA has min_edge=0.03 — a 3.5% edge passes."""
        f = _buy_ready(edge=0.035, sport="basketball_nba")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_nba_fails_at_2_5_percent(self):
        """NBA has min_edge=0.03 — a 2.5% edge fails."""
        f = _buy_ready(edge=0.025, sport="basketball_nba")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons

    def test_mlb_passes_at_3_5_percent(self):
        """MLB has min_edge=0.03 — a 3.5% edge passes."""
        f = _buy_ready(edge=0.035, sport="baseball_mlb")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_nhl_passes_at_3_5_percent(self):
        """NHL has min_edge=0.03 — a 3.5% edge passes."""
        f = _buy_ready(edge=0.035, sport="icehockey_nhl")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_mma_fails_at_3_5_percent(self):
        """MMA uses default min_edge=0.05 — a 3.5% edge fails."""
        f = _buy_ready(edge=0.035, sport="mma_mixed_martial_arts")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons

    def test_mma_passes_at_5_5_percent(self):
        """MMA uses default min_edge=0.05 — a 5.5% edge passes."""
        f = _buy_ready(edge=0.055, sport="mma_mixed_martial_arts")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "BUY"

    def test_unknown_sport_uses_global_default(self):
        """Unknown sport falls back to EngineConfig.min_edge (5%)."""
        f = _buy_ready(edge=0.035, sport="unknown_sport")
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons

    def test_wide_market_overrides_sport_threshold(self):
        """Wide market threshold (8%) takes precedence over sport threshold (3%)."""
        f = _buy_ready(
            edge=0.05,
            sport="basketball_nba",
            fanduel_line_width=0.40,
            fanduel_line_width_label="Wide",
        )
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "WATCH"
        assert "EDGE_BELOW_THRESHOLD" in f.downgrade_reasons


# ---------------------------------------------------------------------------
# Price-probability coherence (side inversion detection)
# ---------------------------------------------------------------------------

class TestPriceProbCoherence:
    def test_pass_normal_edge(self):
        """Normal: pm_price=0.55, p_true=0.65, divergence=0.10 — passes."""
        f = _buy_ready(pm_price=0.55, p_true=0.65)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "PRICE_PROB_DIVERGENCE" not in f.reject_reasons

    def test_fail_side_inversion(self):
        """Inverted: pm_price=0.20, p_true=0.65, divergence=0.45 — SKIP."""
        f = _buy_ready(pm_price=0.20, pm_price_effective=0.21, p_true=0.65, edge=0.44)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "PRICE_PROB_DIVERGENCE" in f.reject_reasons

    def test_pass_at_threshold(self):
        """At threshold: divergence=0.40 — passes."""
        f = _buy_ready(pm_price=0.25, pm_price_effective=0.26, p_true=0.65, edge=0.39)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "PRICE_PROB_DIVERGENCE" not in f.reject_reasons

    def test_fail_above_threshold(self):
        """Above threshold: divergence=0.41 — SKIP."""
        f = _buy_ready(pm_price=0.24, pm_price_effective=0.25, p_true=0.65, edge=0.40)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "PRICE_PROB_DIVERGENCE" in f.reject_reasons

    def test_catches_mls_inversion_pattern(self):
        """
        The specific MLS bug: Inter Miami at 20.5c with -240 FD (p_true ~61%).
        Divergence = |0.61 - 0.205| = 0.405 > 0.40 → SKIP.
        """
        f = _buy_ready(pm_price=0.205, pm_price_effective=0.215, p_true=0.61, edge=0.395)
        status, _ = evaluate_rules(f, _default_cfg())
        assert status == "SKIP"
        assert "PRICE_PROB_DIVERGENCE" in f.reject_reasons

    def test_pass_legitimate_high_edge(self):
        """Legitimate edge: pm_price=0.40, p_true=0.65, divergence=0.25 — passes."""
        f = _buy_ready(pm_price=0.40, pm_price_effective=0.41, p_true=0.65, edge=0.24)
        status, _ = evaluate_rules(f, _default_cfg())
        assert "PRICE_PROB_DIVERGENCE" not in f.reject_reasons


# ---------------------------------------------------------------------------
# Rule evaluation trace
# ---------------------------------------------------------------------------

class TestRuleTrace:
    def test_all_rules_present_in_trace(self):
        f = _buy_ready()
        _, results = evaluate_rules(f, _default_cfg())
        result_names = {r.rule_name for r in results}
        policy_names = {r.rule_name for r in POLICY_TABLE}
        assert result_names == policy_names

    def test_trace_records_severity(self):
        f = _buy_ready(is_live=True)
        _, results = evaluate_rules(f, _default_cfg())
        live_result = [r for r in results if r.rule_name == "not_live"][0]
        assert live_result.passed is False
        assert live_result.severity == "CRITICAL"
        assert live_result.reason_code == "EVENT_LIVE"

    def test_trace_includes_description(self):
        f = _buy_ready()
        _, results = evaluate_rules(f, _default_cfg())
        for r in results:
            assert len(r.description) > 0
            assert len(r.reason_code) > 0
