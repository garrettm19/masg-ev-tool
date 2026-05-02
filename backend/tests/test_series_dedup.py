"""
Tests for series dedup — keeping only the closest-date match when
multiple sportsbook events match the same prediction market.

Covers:
  - Single event match: no dedup needed
  - Two games in series: only best date match kept
  - Different markets are independent
  - Best date wins over higher edge
  - Features from dropped events are removed
  - Ambiguity enrichment runs AFTER dedup (regression for stale
    competing_matches stuck downgrading resolved series candidates)
"""
import pytest
from services.rule_engine import MarketFeatures
from services.opportunities import _dedup_to_best_date_match, _enrich_ambiguity_metrics


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


# ---------------------------------------------------------------------------
# Ambiguity enrichment runs AFTER dedup (regression: previously the pipeline
# enriched first, so survivors carried stale competing_matches > 1 and were
# permanently downgraded to WATCH via EXCESS_COMPETING_MATCHES even though
# dedup correctly resolved the series to a single event).
# ---------------------------------------------------------------------------

def _enrichable_feat(
    market_id: str,
    event_id: str,
    confidence: float,
    date_score: float,
    side: str = "Team A",
    home: str = "team_a",
    away: str = "team_b",
) -> MarketFeatures:
    return MarketFeatures(
        platform="kalshi",
        market_id=market_id,
        matched_event_id=event_id,
        event_match_confidence=confidence,
        date_score=date_score,
        side=side,
        home_player_norm=home,
        away_player_norm=away,
    )


class TestEnrichmentAfterDedup:
    def test_three_game_series_resolves_to_single_competing_match(self):
        """Pipeline order regression: a 3-game MLB series should leave the
        surviving feature with competing_matches == 1, not the pre-dedup 3."""
        # Same Kalshi market matched to three FD events (3-game series)
        features = [
            _enrichable_feat("KX-MLB-LADSTL", "g1", confidence=0.90, date_score=1.00),
            _enrichable_feat("KX-MLB-LADSTL", "g2", confidence=0.90, date_score=0.95),
            _enrichable_feat("KX-MLB-LADSTL", "g3", confidence=0.90, date_score=0.85),
        ]
        # Pipeline order: dedup THEN enrich (matches services/opportunities.py)
        survivors = _dedup_to_best_date_match(features)
        _enrich_ambiguity_metrics(survivors)

        assert len(survivors) == 1
        assert survivors[0].matched_event_id == "g1"
        # Critical assertion: competing_matches reflects post-dedup state
        assert survivors[0].competing_matches == 1, (
            "competing_matches should reflect surviving candidates only; "
            "stale pre-dedup count would falsely trigger EXCESS_COMPETING_MATCHES"
        )

    def test_genuine_ambiguity_still_detected_after_dedup(self):
        """If two genuinely different events with similar dates survive
        (different market_ids), ambiguity is still detected per market."""
        features = [
            _enrichable_feat("market_x", "ev1", confidence=0.92, date_score=1.0),
            _enrichable_feat("market_x", "ev2", confidence=0.88, date_score=1.0),
            _enrichable_feat("market_y", "ev3", confidence=0.95, date_score=1.0),
        ]
        # market_x has a genuine 2-event ambiguity at the same date_score
        survivors = _dedup_to_best_date_match(features)
        _enrich_ambiguity_metrics(survivors)

        # market_x: tied date_scores → dedup keeps first (deterministic by impl);
        # only one surviving feature for market_x → competing == 1
        m_x = [f for f in survivors if f.market_id == "market_x"]
        m_y = [f for f in survivors if f.market_id == "market_y"]
        assert len(m_x) == 1
        assert m_x[0].competing_matches == 1
        assert len(m_y) == 1
        assert m_y[0].competing_matches == 1

    def test_no_ambiguity_for_single_market_match(self):
        """Single market, single event: enrichment produces clean state."""
        features = [
            _enrichable_feat("market_z", "evz", confidence=0.98, date_score=1.0),
        ]
        survivors = _dedup_to_best_date_match(features)
        _enrich_ambiguity_metrics(survivors)
        assert survivors[0].competing_matches == 1
        assert survivors[0].confidence_gap == 1.0  # default for non-ambiguous
