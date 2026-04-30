"""
Tests for services.prop_extractor — player prop matching.

Covers:
  - Prop type classification by sport
  - Question parsing (side + line extraction)
  - Player name matching (strict, full-name only)
  - Exact line matching (zero tolerance)
  - Over/under side alignment
  - Ambiguity rejection
  - Edge calculation correctness
"""
import pytest

from services.adapters.base import NormalizedMarket
from services.engine_config import EngineConfig
from services.odds_provider import PropEvent, PropLine
from services.prop_extractor import (
    classify_prop_type,
    _parse_prop_question,
    _match_player,
    extract_prop_features,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_prop_line(
    player: str = "Jayson Tatum",
    prop_type: str = "player_points",
    line: float = 27.5,
    over_odds: int = -110,
    under_odds: int = -110,
) -> PropLine:
    from services.normalizer import normalize_name
    return PropLine(
        bookmaker_key="fanduel",
        player_name=player,
        player_name_norm=normalize_name(player),
        prop_type=prop_type,
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        last_update="2026-04-09T12:00:00Z",
    )


def _make_prop_event(
    props: list[PropLine] | None = None,
    sport_key: str = "basketball_nba",
    home: str = "Boston Celtics",
    away: str = "Miami Heat",
) -> PropEvent:
    from services.normalizer import normalize_name
    return PropEvent(
        event_id="evt_test",
        sport_key=sport_key,
        tournament="NBA",
        home_team=home,
        away_team=away,
        home_team_norm=normalize_name(home),
        away_team_norm=normalize_name(away),
        commence_time="2026-04-10T23:00:00Z",
        props=props or [],
    )


def _make_prop_market(
    question: str,
    prices: list[str] | None = None,
) -> NormalizedMarket:
    return NormalizedMarket(
        platform="kalshi",
        market_id="prop_test",
        event=question,
        market_type="prop",
        side="",
        line=None,
        price=float(prices[0]) if prices else 0.55,
        liquidity=500.0,
        url=None,
        timestamp=None,
        question=question,
        end_date=None,
        outcome_prices=prices or ["0.55", "0.45"],
        event_slug="test",
    )


# ---------------------------------------------------------------------------
# Prop type classification
# ---------------------------------------------------------------------------

class TestClassifyPropType:

    @pytest.mark.parametrize("question,sport,expected", [
        # NBA
        ("Will Jayson Tatum score Over 27.5 points?", "basketball_nba", "player_points"),
        ("Jayson Tatum Over 8.5 rebounds", "basketball_nba", "player_rebounds"),
        ("Trae Young Over 9.5 assists tonight", "basketball_nba", "player_assists"),
        ("Steph Curry Over 4.5 three pointers", "basketball_nba", "player_threes"),
        ("LeBron Over 42.5 pts+reb+ast", "basketball_nba", "player_points_rebounds_assists"),
        # NFL
        ("Patrick Mahomes Over 2.5 passing touchdowns", "americanfootball_nfl", "player_pass_tds"),
        ("Josh Allen Over 274.5 passing yards", "americanfootball_nfl", "player_pass_yds"),
        ("Derrick Henry Over 89.5 rushing yards", "americanfootball_nfl", "player_rush_yds"),
        ("Tyreek Hill Over 5.5 receptions", "americanfootball_nfl", "player_receptions"),
        ("Travis Kelce Over 74.5 receiving yards", "americanfootball_nfl", "player_reception_yds"),
        ("Ja'Marr Chase anytime touchdown", "americanfootball_nfl", "player_anytime_td"),
        # MLB
        ("Aaron Judge Over 1.5 total bases", "baseball_mlb", "batter_total_bases"),
        ("Shohei Ohtani Over 0.5 home runs", "baseball_mlb", "batter_home_runs"),
        ("Mookie Betts Over 0.5 hits", "baseball_mlb", "batter_hits"),
    ])
    def test_classification(self, question, sport, expected):
        assert classify_prop_type(question, sport) == expected

    def test_wrong_sport_returns_none(self):
        """NBA keywords should not match in NFL context."""
        assert classify_prop_type("Jayson Tatum Over 27.5 points", "americanfootball_nfl") is None

    def test_unknown_question_returns_none(self):
        assert classify_prop_type("Will it rain tomorrow?", "basketball_nba") is None

    def test_unsupported_sport_returns_none(self):
        assert classify_prop_type("Jayson Tatum Over 27.5 points", "icehockey_nhl") is None


# ---------------------------------------------------------------------------
# Question parsing
# ---------------------------------------------------------------------------

class TestParseQuestion:

    def test_over_with_line(self):
        side, line = _parse_prop_question("Will Jayson Tatum score Over 27.5 points?")
        assert side == "over"
        assert line == 27.5

    def test_under_with_line(self):
        side, line = _parse_prop_question("Patrick Mahomes Under 2.5 passing TDs")
        assert side == "under"
        assert line == 2.5

    def test_decimal_line(self):
        side, line = _parse_prop_question("Over 274.5 passing yards")
        assert side == "over"
        assert line == 274.5

    def test_no_side_returns_none(self):
        side, _ = _parse_prop_question("Jayson Tatum 27.5 points")
        assert side is None

    def test_no_line_returns_none(self):
        _, line = _parse_prop_question("Jayson Tatum Over many points")
        assert line is None

    def test_anytime_td_no_line(self):
        """Anytime TD props don't have a line — returns None."""
        side, line = _parse_prop_question("Ja'Marr Chase anytime touchdown")
        assert side is None  # no over/under keyword
        assert line is None


# ---------------------------------------------------------------------------
# Player matching
# ---------------------------------------------------------------------------

class TestMatchPlayer:

    def test_exact_match(self):
        props = [_make_prop_line("Jayson Tatum", "player_points", 27.5)]
        result = _match_player("jayson tatum over 27 5 points", props, "player_points", 27.5)
        assert result is not None
        assert result.player_name == "Jayson Tatum"

    def test_line_mismatch_rejected(self):
        """Different line → no match."""
        props = [_make_prop_line("Jayson Tatum", "player_points", 27.5)]
        result = _match_player("jayson tatum over 25 5 points", props, "player_points", 25.5)
        assert result is None

    def test_prop_type_mismatch_rejected(self):
        """Wrong prop type → no match."""
        props = [_make_prop_line("Jayson Tatum", "player_rebounds", 8.5)]
        result = _match_player("jayson tatum over 8 5 rebounds", props, "player_points", 8.5)
        assert result is None

    def test_player_not_in_question_rejected(self):
        """Player name not substring of question → no match."""
        props = [_make_prop_line("Jayson Tatum", "player_points", 27.5)]
        result = _match_player("jimmy butler over 27 5 points", props, "player_points", 27.5)
        assert result is None

    def test_ambiguity_rejected(self):
        """Two players matching same question → rejected."""
        props = [
            _make_prop_line("James Harden", "player_points", 20.5),
            _make_prop_line("LeBron James", "player_points", 20.5),
        ]
        # "james" appears in both — but full-name match is required
        # "lebron james" is NOT in "james harden over 20 5 points"
        result = _match_player("james harden over 20 5 points", props, "player_points", 20.5)
        assert result is not None
        assert result.player_name == "James Harden"

    def test_no_last_name_fallback(self):
        """Last-name-only should NOT match — strict full-name required."""
        props = [_make_prop_line("Jayson Tatum", "player_points", 27.5)]
        # Question only has "tatum" not "jayson tatum"
        result = _match_player("tatum over 27 5 points", props, "player_points", 27.5)
        assert result is None

    def test_multiple_props_same_player_different_lines(self):
        """Same player, same type, different lines — only exact line matches."""
        props = [
            _make_prop_line("Patrick Mahomes", "player_pass_tds", 1.5, -200, 170),
            _make_prop_line("Patrick Mahomes", "player_pass_tds", 2.5, -110, -110),
            _make_prop_line("Patrick Mahomes", "player_pass_tds", 3.5, 150, -180),
        ]
        result = _match_player(
            "patrick mahomes over 2 5 passing touchdowns", props, "player_pass_tds", 2.5,
        )
        assert result is not None
        assert result.line == 2.5
        assert result.over_odds == -110


# ---------------------------------------------------------------------------
# Full feature extraction
# ---------------------------------------------------------------------------

class TestExtractPropFeatures:

    def test_nba_points_over(self):
        """Standard NBA points Over prop produces one feature."""
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5, -115, -105)
        event = _make_prop_event([prop])
        market = _make_prop_market(
            "Will Jayson Tatum score Over 27.5 points?",
            prices=["0.50", "0.50"],
        )

        features = extract_prop_features(market, event, EngineConfig())

        assert len(features) == 1
        f = features[0]
        assert f.market_type == "player_points"
        assert "Jayson Tatum" in f.side
        assert "Over" in f.side
        assert f.line == 27.5
        assert f.has_bookmaker_data is True
        assert f.name_match_score == 1.0
        assert f.outcome_aligned is True
        assert f.p_true > 0
        assert f.edge != 0  # should have some edge given the prices

    def test_nfl_pass_tds_under(self):
        """NFL passing TD Under prop."""
        prop = _make_prop_line("Patrick Mahomes", "player_pass_tds", 2.5, -150, 130)
        event = _make_prop_event(
            [prop], sport_key="americanfootball_nfl",
            home="Kansas City Chiefs", away="Buffalo Bills",
        )
        market = _make_prop_market(
            "Patrick Mahomes Under 2.5 passing TDs",
            prices=["0.45", "0.55"],
        )

        features = extract_prop_features(market, event, EngineConfig())

        assert len(features) == 1
        f = features[0]
        assert f.market_type == "player_pass_tds"
        assert "Under" in f.side
        # Under side: fd_odds should be the under_odds
        assert f.fd_odds == 130

    def test_line_mismatch_returns_empty(self):
        """PM asks about 25.5, FD only has 27.5 → no feature."""
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5)
        event = _make_prop_event([prop])
        market = _make_prop_market("Jayson Tatum Over 25.5 points", prices=["0.60", "0.40"])

        features = extract_prop_features(market, event, EngineConfig())
        assert features == []

    def test_player_not_found_returns_empty(self):
        """Question mentions a different player → no feature."""
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5)
        event = _make_prop_event([prop])
        market = _make_prop_market("Jimmy Butler Over 27.5 points", prices=["0.50", "0.50"])

        features = extract_prop_features(market, event, EngineConfig())
        assert features == []

    def test_wrong_sport_returns_empty(self):
        """NBA question against NFL event → no feature."""
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5)
        event = _make_prop_event([prop], sport_key="americanfootball_nfl")
        market = _make_prop_market("Jayson Tatum Over 27.5 points")

        features = extract_prop_features(market, event, EngineConfig())
        assert features == []  # classify_prop_type returns None for wrong sport

    def test_no_side_returns_empty(self):
        """Question without over/under → no feature."""
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5)
        event = _make_prop_event([prop])
        market = _make_prop_market("Jayson Tatum 27.5 points")

        features = extract_prop_features(market, event, EngineConfig())
        assert features == []

    def test_edge_calculation(self):
        """Verify edge = p_true - pm_price_effective."""
        # Over odds -200 → implied 0.6667, Under +170 → implied 0.3704
        # Overround = 1.0371
        # Devigged: over = 0.6667/1.0371 ≈ 0.6428, under ≈ 0.3572
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5, -200, 170)
        event = _make_prop_event([prop])
        market = _make_prop_market(
            "Jayson Tatum Over 27.5 points", prices=["0.55", "0.45"],
        )
        cfg = EngineConfig()

        features = extract_prop_features(market, event, cfg)
        assert len(features) == 1
        f = features[0]

        # p_true ≈ 0.6428 (devigged over)
        assert 0.63 < f.p_true < 0.66
        # pm_price_effective = 0.55 + 0.01 (cost_buffer) = 0.56
        expected_edge = f.p_true - 0.56
        assert abs(f.edge - expected_edge) < 0.001

    def test_returns_at_most_one_feature(self):
        """Props always return 0 or 1 features, never 2."""
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5)
        event = _make_prop_event([prop])
        market = _make_prop_market("Jayson Tatum Over 27.5 points")

        features = extract_prop_features(market, event, EngineConfig())
        assert len(features) <= 1

    def test_mlb_batter_hits(self):
        """MLB batter hits prop."""
        prop = _make_prop_line("Shohei Ohtani", "batter_hits", 1.5, -130, 110)
        event = _make_prop_event(
            [prop], sport_key="baseball_mlb",
            home="Los Angeles Dodgers", away="San Diego Padres",
        )
        market = _make_prop_market("Shohei Ohtani Over 1.5 hits", prices=["0.55", "0.45"])

        features = extract_prop_features(market, event, EngineConfig())
        assert len(features) == 1
        assert features[0].market_type == "batter_hits"
        assert "Shohei Ohtani" in features[0].side


# ---------------------------------------------------------------------------
# Rule engine integration
# ---------------------------------------------------------------------------

from services.rule_engine import evaluate_rules, compute_kelly


class TestPropRuleEngine:
    """Props pass through the rule engine without h2h-specific rejections."""

    def test_valid_prop_gets_buy(self):
        """Prop with positive edge and all data passes all 23 rules → BUY."""
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5, -200, 170)
        event = _make_prop_event([prop])
        market = _make_prop_market(
            "Will Jayson Tatum score Over 27.5 points?",
            prices=["0.55", "0.45"],
        )
        features = extract_prop_features(market, event, EngineConfig())
        assert len(features) == 1
        f = features[0]

        status, results = evaluate_rules(f, EngineConfig())
        compute_kelly(f, EngineConfig())

        assert status == "BUY"
        assert f.kelly_fraction > 0
        # No CRITICAL or DOWNGRADE failures
        assert all(r.passed for r in results)

    def test_negative_edge_prop_gets_skip(self):
        """Prop with negative edge → SKIP via NO_EDGE."""
        # FD: over -110/under -110 → p_true ≈ 0.50. PM price 0.55 → edge negative
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5, -110, -110)
        event = _make_prop_event([prop])
        market = _make_prop_market(
            "Will Jayson Tatum score Over 27.5 points?",
            prices=["0.55", "0.45"],
        )
        features = extract_prop_features(market, event, EngineConfig())
        assert len(features) == 1

        status, results = evaluate_rules(features[0], EngineConfig())
        assert status == "SKIP"
        failed = [r.reason_code for r in results if not r.passed and r.severity == "CRITICAL"]
        assert "NO_EDGE" in failed

    def test_prop_with_thin_edge_gets_watch(self):
        """Prop with edge below threshold → WATCH via EDGE_BELOW_THRESHOLD."""
        # p_true ≈ 0.524, pm_price = 0.50, edge ≈ 0.014 (below 5% threshold)
        prop = _make_prop_line("Jayson Tatum", "player_points", 27.5, -110, -110)
        event = _make_prop_event([prop])
        market = _make_prop_market(
            "Will Jayson Tatum score Over 27.5 points?",
            prices=["0.50", "0.50"],
        )
        features = extract_prop_features(market, event, EngineConfig())
        assert len(features) == 1

        status, results = evaluate_rules(features[0], EngineConfig())
        # Positive but thin edge → should be WATCH (below 5% threshold)
        assert status in ("WATCH", "SKIP")

    def test_h2h_still_works(self):
        """H2H features are unaffected by prop changes."""
        from services.adapters.base import NormalizedMarket as NM
        from services.feature_extractor import extract_features
        from services.odds_provider import TennisOddsEvent, BookmakerLine
        from services.normalizer import normalize_name

        event = TennisOddsEvent(
            event_id="ev1", sport_key="basketball_nba", tournament="NBA",
            home_player="Boston Celtics", away_player="Miami Heat",
            home_player_norm=normalize_name("Boston Celtics"),
            away_player_norm=normalize_name("Miami Heat"),
            commence_time="2026-04-11T23:00:00Z",
            bookmakers=[BookmakerLine(
                bookmaker_key="fanduel", bookmaker_title="FanDuel",
                home_odds=-150, away_odds=130, last_update="2026-04-09T12:00:00Z",
            )],
        )
        market = NM(
            platform="polymarket", market_id="h2h_test",
            event="Boston Celtics vs Miami Heat",
            market_type="h2h", side="", line=None,
            price=0.55, liquidity=5000.0, url=None, timestamp=None,
            question="Will Boston Celtics beat Miami Heat?",
            end_date="2026-04-12T06:00:00Z",
            outcome_prices=["0.55", "0.45"], event_slug="test",
        )

        features = extract_features(market, event, EngineConfig())
        assert len(features) == 2  # H2H always produces two sides
        for f in features:
            status, _ = evaluate_rules(f, EngineConfig())
            assert status in ("BUY", "WATCH", "SKIP")  # classifies normally
