"""
Tests for ambiguity detection and enrichment in the pipeline.

Covers:
  - _enrich_ambiguity_metrics behavior
  - shared last name detection
  - confidence gap computation
  - competing matches counting
"""
import pytest
from services.rule_engine import MarketFeatures
from services.opportunities import _enrich_ambiguity_metrics


def _make_feature(
    platform: str = "polymarket",
    market_id: str = "m1",
    event_id: str = "ev1",
    confidence: float = 0.95,
    home_norm: str = "carlos alcaraz",
    away_norm: str = "jannik sinner",
) -> MarketFeatures:
    return MarketFeatures(
        platform=platform,
        market_id=market_id,
        matched_event_id=event_id,
        event_match_confidence=confidence,
        best_match_confidence=confidence,
        home_player_norm=home_norm,
        away_player_norm=away_norm,
    )


class TestEnrichAmbiguityMetrics:
    def test_single_event_match(self):
        """One market matched to one event — no ambiguity."""
        f = _make_feature(event_id="ev1", confidence=0.95)
        _enrich_ambiguity_metrics([f])

        assert f.competing_matches == 1
        assert f.confidence_gap == 1.0
        assert f.second_best_event_id == ""
        assert f.has_shared_last_name is False

    def test_two_events_wide_gap(self):
        """One market matched to two events with clear winner."""
        f1 = _make_feature(market_id="m1", event_id="ev1", confidence=0.95)
        f2 = _make_feature(market_id="m1", event_id="ev2", confidence=0.70,
                           home_norm="carlos alcaraz", away_norm="rafael nadal")
        _enrich_ambiguity_metrics([f1, f2])

        assert f1.competing_matches == 2
        assert f1.confidence_gap == 0.25
        assert f1.second_best_event_id == "ev2"
        assert f2.competing_matches == 2

    def test_two_events_narrow_gap(self):
        """Two events with close confidence — ambiguous."""
        f1 = _make_feature(market_id="m1", event_id="ev1", confidence=0.93)
        f2 = _make_feature(market_id="m1", event_id="ev2", confidence=0.91,
                           home_norm="carlos alcaraz", away_norm="rafael nadal")
        _enrich_ambiguity_metrics([f1, f2])

        assert f1.competing_matches == 2
        assert f1.confidence_gap == pytest.approx(0.02, abs=0.001)

    def test_shared_last_name_detection(self):
        """Two events share a player last name → flagged."""
        # Event 1: Alcaraz vs Sinner
        f1 = _make_feature(
            market_id="m1", event_id="ev1", confidence=0.95,
            home_norm="carlos alcaraz", away_norm="jannik sinner",
        )
        # Event 2: Alcaraz vs Nadal (shares "alcaraz")
        f2 = _make_feature(
            market_id="m1", event_id="ev2", confidence=0.90,
            home_norm="carlos alcaraz", away_norm="rafael nadal",
        )
        _enrich_ambiguity_metrics([f1, f2])

        assert f1.has_shared_last_name is True
        assert f2.has_shared_last_name is True

    def test_no_shared_last_name(self):
        """Two events with completely different players."""
        f1 = _make_feature(
            market_id="m1", event_id="ev1", confidence=0.95,
            home_norm="carlos alcaraz", away_norm="jannik sinner",
        )
        f2 = _make_feature(
            market_id="m1", event_id="ev2", confidence=0.88,
            home_norm="rafael nadal", away_norm="novak djokovic",
        )
        _enrich_ambiguity_metrics([f1, f2])

        assert f1.has_shared_last_name is False
        assert f2.has_shared_last_name is False

    def test_different_markets_independent(self):
        """Features from different markets don't affect each other."""
        f1 = _make_feature(market_id="m1", event_id="ev1", confidence=0.95)
        f2 = _make_feature(market_id="m2", event_id="ev2", confidence=0.90,
                           home_norm="rafael nadal", away_norm="novak djokovic")
        _enrich_ambiguity_metrics([f1, f2])

        assert f1.competing_matches == 1
        assert f2.competing_matches == 1
        assert f1.confidence_gap == 1.0
        assert f2.confidence_gap == 1.0

    def test_three_events_same_market(self):
        """Three events matched to one market."""
        f1 = _make_feature(market_id="m1", event_id="ev1", confidence=0.95)
        f2 = _make_feature(market_id="m1", event_id="ev2", confidence=0.92,
                           home_norm="carlos alcaraz", away_norm="rafael nadal")
        f3 = _make_feature(market_id="m1", event_id="ev3", confidence=0.85,
                           home_norm="carlos alcaraz", away_norm="novak djokovic")
        _enrich_ambiguity_metrics([f1, f2, f3])

        assert f1.competing_matches == 3
        assert f1.confidence_gap == pytest.approx(0.03, abs=0.001)
        assert f1.second_best_event_id == "ev2"

    def test_non_top_event_gets_correct_gap(self):
        """Features for non-best event get gap relative to best."""
        f1 = _make_feature(market_id="m1", event_id="ev1", confidence=0.95)
        f2 = _make_feature(market_id="m1", event_id="ev2", confidence=0.88,
                           home_norm="rafael nadal", away_norm="novak djokovic")
        _enrich_ambiguity_metrics([f1, f2])

        # f2 is NOT the top event — its gap should be vs the top
        assert f2.second_best_event_id == "ev1"
        assert f2.confidence_gap == pytest.approx(0.07, abs=0.001)

    def test_h2h_two_sides_same_event(self):
        """H2H produces two features for the same event — they're not rivals."""
        f1 = _make_feature(market_id="m1", event_id="ev1", confidence=0.95)
        f2 = _make_feature(market_id="m1", event_id="ev1", confidence=0.95)
        _enrich_ambiguity_metrics([f1, f2])

        # Same event_id counted once → competing_matches = 1
        assert f1.competing_matches == 1
        assert f1.confidence_gap == 1.0

    def test_different_platforms_separate(self):
        """Same market_id on different platforms → treated independently."""
        f1 = _make_feature(platform="polymarket", market_id="m1",
                           event_id="ev1", confidence=0.95)
        f2 = _make_feature(platform="kalshi", market_id="m1",
                           event_id="ev2", confidence=0.90)
        _enrich_ambiguity_metrics([f1, f2])

        assert f1.competing_matches == 1
        assert f2.competing_matches == 1

    def test_cross_platform_same_ambiguity_when_both_events_match(self):
        """
        When two sportsbook events share both player names (same players in
        different tournaments), BOTH platform markets see competing_matches=2.

        This proves that per-platform enrichment doesn't create a blind spot:
        if both events match on Polymarket, they also match on Kalshi (same
        player names), so ambiguity is detected on both platforms independently.
        """
        # Polymarket market matched to E1 and E2
        pm_e1 = _make_feature(
            platform="polymarket", market_id="pm1",
            event_id="ev1", confidence=0.95,
            home_norm="carlos alcaraz", away_norm="jannik sinner",
        )
        pm_e2 = _make_feature(
            platform="polymarket", market_id="pm1",
            event_id="ev2", confidence=0.92,
            home_norm="carlos alcaraz", away_norm="jannik sinner",
        )

        # Kalshi market also matched to E1 and E2 (same player names)
        k_e1 = _make_feature(
            platform="kalshi", market_id="k1",
            event_id="ev1", confidence=0.95,
            home_norm="carlos alcaraz", away_norm="jannik sinner",
        )
        k_e2 = _make_feature(
            platform="kalshi", market_id="k1",
            event_id="ev2", confidence=0.92,
            home_norm="carlos alcaraz", away_norm="jannik sinner",
        )

        _enrich_ambiguity_metrics([pm_e1, pm_e2, k_e1, k_e2])

        # Both platforms see the same ambiguity
        assert pm_e1.competing_matches == 2
        assert k_e1.competing_matches == 2
        assert pm_e1.confidence_gap == k_e1.confidence_gap
