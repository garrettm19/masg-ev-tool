"""
GET /api/opportunities

Returns matched + priced prediction market x FanDuel opportunities.
Two-pass rule engine: features first, then classify BUY/WATCH/SKIP.
Each row includes full reasoning trace.
"""
import logging
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from services.engine_config import EngineConfig
from services.opportunities import (
    fetch_opportunities,
    diagnose_pipeline,
    DEFAULT_CONFIG,
)
from services.price_history import fetch_price_history
from services.rule_engine import POLICY_TABLE

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RuleEvaluation(BaseModel):
    rule: str
    passed: bool
    severity: str
    reason: str


class OpportunityOut(BaseModel):
    # Platform & sport
    platform: str
    sport: str

    # Event
    event: str
    event_url: str | None
    tournament: str
    start_time: str

    # Market
    market_id: str
    market_type: str
    side: str
    line: float | None

    # Pricing (single normalised side)
    pm_price: float
    fd_odds: int
    p_true: float
    edge: float
    recommended_kelly: float
    kelly_full: float

    # FanDuel metrics
    fanduel_overround: float
    fanduel_line_width: float
    fanduel_line_width_label: str
    fanduel_confidence_label: str

    # Match quality
    event_match_confidence: float
    match_quality: str

    # Ambiguity
    matched_event_id: str
    second_best_event_id: str
    confidence_gap: float
    competing_matches: int
    has_shared_last_name: bool

    # Classification
    status: str
    reject_reasons: list[str]
    downgrade_reasons: list[str]

    # Observability
    home_tokens: list[str]
    away_tokens: list[str]
    name_match_score: float
    date_score: float
    date_delta_hours: float | None
    rule_evaluations: list[RuleEvaluation]


class PolicyRuleOut(BaseModel):
    rule_name: str
    stage: str
    severity: str
    reason_code: str
    description: str


class OpportunitiesResponse(BaseModel):
    opportunities: list[OpportunityOut]
    total: int
    status_counts: dict[str, int]
    quota_remaining: str | None
    sportsbook_markets_fetched: list[str]
    markets_dropped_by_type: dict[str, int]
    platforms_fetched: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/opportunities", response_model=OpportunitiesResponse)
async def get_opportunities(
    response: Response,
    min_edge: float = Query(
        default=DEFAULT_CONFIG.min_edge,
        ge=0.0, le=1.0,
        description="Minimum edge for normal-width markets (e.g. 0.05 = 5%)",
    ),
    wide_market_min_edge: float = Query(
        default=DEFAULT_CONFIG.wide_market_min_edge,
        ge=0.0, le=1.0,
        description="Minimum edge for wide-line markets (line_width > 0.35)",
    ),
    survival_threshold: float = Query(
        default=DEFAULT_CONFIG.survival_threshold,
        ge=0.0, le=1.0,
        description="Below this confidence = SKIP",
    ),
    buy_threshold: float = Query(
        default=DEFAULT_CONFIG.buy_threshold,
        ge=0.0, le=1.0,
        description="Required confidence for BUY (below = WATCH)",
    ),
    min_true_probability: float = Query(
        default=DEFAULT_CONFIG.min_true_probability,
        ge=0.0, le=1.0,
        description="Minimum devigged true probability",
    ),
    platform: str | None = Query(
        default=None,
        description="Filter to a single platform (e.g. 'polymarket', 'kalshi')",
    ),
    include_watch: bool = Query(
        default=True,
        description="Include WATCH opportunities in response",
    ),
) -> OpportunitiesResponse:
    """
    Two-pass rule engine opportunities.

    Pass A: extract features for every (market, event) pair.
    Pass B: evaluate policy table → BUY / WATCH / SKIP.
    """
    cfg = EngineConfig(
        min_edge=min_edge,
        wide_market_min_edge=wide_market_min_edge,
        survival_threshold=survival_threshold,
        buy_threshold=buy_threshold,
        min_true_probability=min_true_probability,
    )

    try:
        opportunities, meta = await fetch_opportunities(cfg=cfg)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Opportunities pipeline failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to build opportunities")

    if meta.get("quota_remaining"):
        response.headers["X-Odds-Quota-Remaining"] = str(meta["quota_remaining"])

    opps = opportunities
    if platform:
        opps = [o for o in opps if o.platform == platform]
    if not include_watch:
        opps = [o for o in opps if o.status == "BUY"]

    return OpportunitiesResponse(
        opportunities=[
            OpportunityOut(
                platform=o.platform,
                sport=o.sport,
                event=o.event,
                event_url=o.event_url,
                tournament=o.tournament,
                start_time=o.start_time,
                market_id=o.market_id,
                market_type=o.market_type,
                side=o.side,
                line=o.line,
                pm_price=o.pm_price,
                fd_odds=o.fd_odds,
                p_true=o.p_true,
                edge=o.edge,
                recommended_kelly=o.recommended_kelly,
                kelly_full=o.kelly_full,
                fanduel_overround=o.fanduel_overround,
                fanduel_line_width=o.fanduel_line_width,
                fanduel_line_width_label=o.fanduel_line_width_label,
                fanduel_confidence_label=o.fanduel_confidence_label,
                event_match_confidence=o.event_match_confidence,
                match_quality=o.match_quality,
                matched_event_id=o.matched_event_id,
                second_best_event_id=o.second_best_event_id,
                confidence_gap=o.confidence_gap,
                competing_matches=o.competing_matches,
                has_shared_last_name=o.has_shared_last_name,
                status=o.status,
                reject_reasons=o.reject_reasons,
                downgrade_reasons=o.downgrade_reasons,
                home_tokens=list(o.home_tokens),
                away_tokens=list(o.away_tokens),
                name_match_score=o.name_match_score,
                date_score=o.date_score,
                date_delta_hours=o.date_delta_hours,
                rule_evaluations=[
                    RuleEvaluation(**r) for r in o.rule_evaluations
                ],
            )
            for o in opps
        ],
        total=len(opps),
        status_counts=meta.get("status_counts", {}),
        quota_remaining=meta.get("quota_remaining"),
        sportsbook_markets_fetched=meta.get("sportsbook_markets_fetched", ["h2h"]),
        markets_dropped_by_type=meta.get("markets_dropped_by_type", {}),
        platforms_fetched=meta.get("platforms_fetched", []),
    )


@router.get("/opportunities/policy", response_model=list[PolicyRuleOut])
async def get_policy_table() -> list[PolicyRuleOut]:
    """Return the current rule policy table."""
    return [
        PolicyRuleOut(
            rule_name=r.rule_name,
            stage=r.stage,
            severity=r.severity,
            reason_code=r.reason_code,
            description=r.description,
        )
        for r in POLICY_TABLE
    ]


@router.get("/opportunities/history")
async def get_price_history(
    platform: str = Query(..., description="Platform name (polymarket, kalshi)"),
    market_id: str = Query(..., description="Platform-specific market ID or ticker"),
) -> dict:
    """Fetch price history for a specific market."""
    points = await fetch_price_history(platform, market_id)
    return {
        "platform": platform,
        "market_id": market_id,
        "points": [{"t": p.timestamp, "p": round(p.price, 4)} for p in points],
        "count": len(points),
    }


@router.get("/opportunities/debug")
async def debug_opportunities(
    min_edge: float = Query(default=DEFAULT_CONFIG.min_edge, ge=0.0, le=1.0),
    wide_market_min_edge: float = Query(default=DEFAULT_CONFIG.wide_market_min_edge, ge=0.0, le=1.0),
    survival_threshold: float = Query(default=DEFAULT_CONFIG.survival_threshold, ge=0.0, le=1.0),
    buy_threshold: float = Query(default=DEFAULT_CONFIG.buy_threshold, ge=0.0, le=1.0),
) -> dict:
    """Diagnostic endpoint — traces each pipeline stage with full rule evaluations."""
    cfg = EngineConfig(
        min_edge=min_edge,
        wide_market_min_edge=wide_market_min_edge,
        survival_threshold=survival_threshold,
        buy_threshold=buy_threshold,
    )
    try:
        return await diagnose_pipeline(cfg=cfg)
    except Exception as exc:
        logger.error("Debug pipeline failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
