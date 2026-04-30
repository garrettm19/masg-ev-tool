"""
Adversarial tests for strict EV validation rules.

Covers:
  1. date_not_stale: future PM game matched to current FD event → SKIP
  2. edge_plausible: implausibly large edge → DOWNGRADE
  3. cross-game matching in MLB series
  4. combined: stale date + high edge (the Ducks scenario)
"""
import pytest
from services.engine_config import EngineConfig
from services.rule_engine import (
    MarketFeatures,
    evaluate_rules,
    POLICY_TABLE,
)


def _cfg(**overrides) -> EngineConfig:
    defaults = dict(
        max_date_delta_hours=72.0,
        max_plausible_edge=0.20,
    )
    defaults.update(overrides)
    return EngineConfig(**defaults)


def _buy_ready(**overrides) -> MarketFeatures:
    """MarketFeatures that passes all rules."""
    defaults = dict(
        platform="polymarket",
        market_id="test",
        sport="baseball_mlb",
        event_label="Team A vs Team B",
        market_type="h2h",
        side="Team A",
        question="Team A vs Team B",
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
        confidence_gap=1.0,
        competing_matches=1,
        has_shared_last_name=False,
        home_last_name_collision=False,
        away_last_name_collision=False,
        has_end_date=True,
        has_outcome_prices=True,
        prices_internally_consistent=True,
        date_delta_hours=3.0,
    )
    defaults.update(overrides)
    return MarketFeatures(**defaults)


# ---------------------------------------------------------------------------
# date_not_stale: CRITICAL rule
# ---------------------------------------------------------------------------

class TestDateNotStale:
    def test_pass_same_day(self):
        """Same-day match (3 hours delta) passes."""
        f = _buy_ready(date_delta_hours=3.0, competing_matches=1)
        status, _ = evaluate_rules(f, _cfg())
        assert "DATE_TOO_FAR" not in f.reject_reasons

    def test_pass_next_day(self):
        """Next-day match (28 hours delta) passes."""
        f = _buy_ready(date_delta_hours=28.0, competing_matches=1)
        status, _ = evaluate_rules(f, _cfg())
        assert "DATE_TOO_FAR" not in f.reject_reasons

    def test_fail_future_game(self):
        """PM game 5 days in the future with no competing match → SKIP."""
        f = _buy_ready(date_delta_hours=120.0, competing_matches=1)
        status, _ = evaluate_rules(f, _cfg())
        assert status == "SKIP"
        assert "DATE_TOO_FAR" in f.reject_reasons

    def test_fail_ducks_scenario(self):
        """The exact Ducks bug: Apr 16 PM game matched to Apr 8 FD event (214h)."""
        f = _buy_ready(date_delta_hours=214.0, competing_matches=1, edge=0.095)
        status, _ = evaluate_rules(f, _cfg())
        assert status == "SKIP"
        assert "DATE_TOO_FAR" in f.reject_reasons

    def test_pass_series_with_competing(self):
        """MLB series: 2 FD events match, delta=28h, but competing_matches=2 → passes."""
        f = _buy_ready(date_delta_hours=28.0, competing_matches=2)
        status, _ = evaluate_rules(f, _cfg())
        assert "DATE_TOO_FAR" not in f.reject_reasons

    def test_pass_missing_date(self):
        """No date info → passes (can't check)."""
        f = _buy_ready(date_delta_hours=None)
        status, _ = evaluate_rules(f, _cfg())
        assert "DATE_TOO_FAR" not in f.reject_reasons

    def test_boundary_at_72h(self):
        """Exactly at 72h limit → passes."""
        f = _buy_ready(date_delta_hours=72.0, competing_matches=1)
        status, _ = evaluate_rules(f, _cfg())
        assert "DATE_TOO_FAR" not in f.reject_reasons

    def test_boundary_above_72h(self):
        """Just above 72h → SKIP."""
        f = _buy_ready(date_delta_hours=72.1, competing_matches=1)
        status, _ = evaluate_rules(f, _cfg())
        assert status == "SKIP"
        assert "DATE_TOO_FAR" in f.reject_reasons


# ---------------------------------------------------------------------------
# edge_plausible: DOWNGRADE rule
# ---------------------------------------------------------------------------

class TestEdgePlausible:
    def test_pass_normal_edge(self):
        """Normal edge (9%) passes for any sport."""
        f = _buy_ready(edge=0.09, sport="baseball_mlb")
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" not in f.downgrade_reasons

    def test_mlb_pass_at_limit(self):
        """MLB at 15% (sport limit) passes."""
        f = _buy_ready(edge=0.15, sport="baseball_mlb")
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" not in f.downgrade_reasons

    def test_mlb_fail_above_limit(self):
        """MLB at 16% → WATCH (above 15% sport limit)."""
        f = _buy_ready(edge=0.16, sport="baseball_mlb")
        status, _ = evaluate_rules(f, _cfg())
        assert status == "WATCH"
        assert "EDGE_IMPLAUSIBLE" in f.downgrade_reasons

    def test_nba_fail_above_limit(self):
        """NBA at 13% → WATCH (above 12% sport limit)."""
        f = _buy_ready(edge=0.13, sport="basketball_nba")
        status, _ = evaluate_rules(f, _cfg())
        assert status == "WATCH"
        assert "EDGE_IMPLAUSIBLE" in f.downgrade_reasons

    def test_nba_pass_at_limit(self):
        """NBA at 12% passes."""
        f = _buy_ready(edge=0.12, sport="basketball_nba")
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" not in f.downgrade_reasons

    def test_tennis_pass_higher(self):
        """Tennis at 24% passes (25% sport limit — wider lines)."""
        f = _buy_ready(edge=0.24, sport="tennis_atp_french_open")
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" not in f.downgrade_reasons

    def test_tennis_fail_above_limit(self):
        """Tennis at 26% → WATCH."""
        f = _buy_ready(edge=0.26, sport="tennis_atp_french_open")
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" in f.downgrade_reasons

    def test_nhl_fail_above_limit(self):
        """NHL at 13% → WATCH (12% limit)."""
        f = _buy_ready(edge=0.13, sport="icehockey_nhl")
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" in f.downgrade_reasons

    def test_unknown_sport_uses_global_fallback(self):
        """Unknown sport key uses global 20% default."""
        f = _buy_ready(edge=0.19, sport="unknown_sport")
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" not in f.downgrade_reasons

    def test_fail_extreme_edge(self):
        """Edge 40% (like the old MLS/soccer phantom edges) → SKIP."""
        f = _buy_ready(edge=0.40, pm_price=0.22, pm_price_effective=0.23, p_true=0.63)
        status, _ = evaluate_rules(f, _cfg())
        assert status == "SKIP"

    def test_pass_negative_edge(self):
        """Negative edge → passes (not applicable)."""
        f = _buy_ready(edge=-0.05)
        status, _ = evaluate_rules(f, _cfg())
        assert "EDGE_IMPLAUSIBLE" not in f.downgrade_reasons


# ---------------------------------------------------------------------------
# Combined scenarios
# ---------------------------------------------------------------------------

class TestCombinedValidation:
    def test_cross_game_plus_high_edge(self):
        """Future game (120h) + high edge (15%) → SKIP on date."""
        f = _buy_ready(date_delta_hours=120.0, competing_matches=1, edge=0.15)
        status, _ = evaluate_rules(f, _cfg())
        assert status == "SKIP"
        assert "DATE_TOO_FAR" in f.reject_reasons

    def test_series_with_plausible_edge(self):
        """Series game (competing=2, delta=5h) + small edge → BUY."""
        f = _buy_ready(date_delta_hours=5.0, competing_matches=2, edge=0.08)
        status, _ = evaluate_rules(f, _cfg())
        # competing_matches=2 triggers EXCESS_COMPETING_MATCHES → WATCH
        assert "DATE_TOO_FAR" not in f.reject_reasons

    def test_correct_match_high_edge_still_watchable(self):
        """Close date (3h) + 22% edge → WATCH (edge implausible but date is fine)."""
        f = _buy_ready(date_delta_hours=3.0, competing_matches=1, edge=0.22)
        status, _ = evaluate_rules(f, _cfg())
        assert "DATE_TOO_FAR" not in f.reject_reasons
        assert "EDGE_IMPLAUSIBLE" in f.downgrade_reasons
        assert status == "WATCH"

    def test_all_rules_pass_count(self):
        """Verify total rule count is 23."""
        assert len(POLICY_TABLE) == 23
