"""
Tests for series dedup — keeping only the closest-date match when
multiple sportsbook events match the same prediction market.

Covers:
  - Single event match: no dedup needed
  - Two games in series: only best date match kept
  - Different markets are independent
  - Best date wins over higher edge
  - Features from dropped events are removed
"""
import pytest
from services.rule_engine import MarketFeatures
from services.opportunities import _dedup_to_best_date_match


def _feat(
    platform: str = "polymarket",
    market_id: str = "m1",
    event_id: str = "ev1",
    date_score: float = 1.0,
    edge: float = 0.05,
    side: str = "Team A",
) -> MarketFeatures:
    return MarketFeatures(
        platform=platform,
        market_id=market_id,
        matched_event_id=event_id,
        date_score=date_score,
        edge=edge,
        side=side,
    )


class TestSeriesDedup:
    def test_single_event_unchanged(self):
        features = [_feat(event_id="ev1"), _feat(event_id="ev1", side="Team B")]
        result = _dedup_to_best_date_match(features)
        assert len(result) == 2

    def test_two_games_keeps_best_date(self):
        """Game 1 (date_score=1.0) kept, Game 2 (date_score=0.85) dropped."""
        features = [
            _feat(event_id="game1", date_score=1.0, edge=0.05, side="A"),
            _feat(event_id="game1", date_score=1.0, edge=0.03, side="B"),
            _feat(event_id="game2", date_score=0.85, edge=0.15, side="A"),  # higher edge but worse date
            _feat(event_id="game2", date_score=0.85, edge=0.10, side="B"),
        ]
        result = _dedup_to_best_date_match(features)
        assert len(result) == 2
        assert all(f.matched_event_id == "game1" for f in result)

    def test_higher_edge_dropped_if_worse_date(self):
        """Edge doesn't matter — best date wins."""
        features = [
            _feat(event_id="correct", date_score=0.95, edge=0.02),
            _feat(event_id="wrong", date_score=0.85, edge=0.30),
        ]
        result = _dedup_to_best_date_match(features)
        assert len(result) == 1
        assert result[0].matched_event_id == "correct"

    def test_different_markets_independent(self):
        """Two different PM markets are deduped independently."""
        features = [
            _feat(market_id="m1", event_id="ev1", date_score=1.0),
            _feat(market_id="m1", event_id="ev2", date_score=0.85),
            _feat(market_id="m2", event_id="ev3", date_score=0.85),
            _feat(market_id="m2", event_id="ev4", date_score=1.0),
        ]
        result = _dedup_to_best_date_match(features)
        assert len(result) == 2
        ids = {f.matched_event_id for f in result}
        assert "ev1" in ids  # best for m1
        assert "ev4" in ids  # best for m2

    def test_same_date_score_keeps_first(self):
        """When date scores are tied, keep the first event."""
        features = [
            _feat(event_id="ev_a", date_score=0.95),
            _feat(event_id="ev_b", date_score=0.95),
        ]
        result = _dedup_to_best_date_match(features)
        assert len(result) == 1

    def test_three_game_series(self):
        """Three games: only the best-date match survives."""
        features = [
            _feat(event_id="g1", date_score=1.0, side="A"),
            _feat(event_id="g1", date_score=1.0, side="B"),
            _feat(event_id="g2", date_score=0.95, side="A"),
            _feat(event_id="g2", date_score=0.95, side="B"),
            _feat(event_id="g3", date_score=0.85, side="A"),
            _feat(event_id="g3", date_score=0.85, side="B"),
        ]
        result = _dedup_to_best_date_match(features)
        assert len(result) == 2
        assert all(f.matched_event_id == "g1" for f in result)
