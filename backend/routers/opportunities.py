"""
GET /api/opportunities

Returns matched + priced prediction market × FanDuel tennis opportunities.
Supports multiple platforms (Polymarket, Kalshi, etc.) via adapters.
Each row is normalised to a single side — no YES/NO ambiguity.
Read-only.  No trade execution.
"""
import dataclasses
import logging
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from services.price_history import fetch_price_history
from services.opportunities import (
    fetch_opportunities,
    diagnose_pipeline,
    EngineConfig,
    DEFAULT_CONFIG,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

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

    # FanDuel metrics (FanDuel only)
    fanduel_overround: float
    fanduel_line_width: float
    fanduel_line_width_label: str
    fanduel_confidence_label: str

    # Event match
    event_match_confidence: float

    # Status
    status: str


class OpportunitiesResponse(BaseModel):
    opportunities: list[OpportunityOut]
    total: int
    quota_remaining: str | None
    sportsbook_markets_fetched: list[str]
    markets_dropped_by_type: dict[str, int]
    platforms_fetched: list[str]


# ---------------------------------------------------------------------------
# Route
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
    min_event_match_confidence: float = Query(
        default=DEFAULT_CONFIG.min_event_match_confidence,
        ge=0.0, le=1.0,
        description="Minimum event match confidence",
    ),
    platform: str | None = Query(
        default=None,
        description="Filter to a single platform (e.g. 'polymarket', 'kalshi')",
    ),
) -> OpportunitiesResponse:
    """
    Matched and priced tennis opportunities from all platforms.

    Edge thresholds are line-width-aware:
    - Normal markets (line_width <= 0.35): require edge >= min_edge
    - Wide markets (line_width > 0.35):   require edge >= wide_market_min_edge
    """
    cfg = EngineConfig(
        min_edge=min_edge,
        wide_market_min_edge=wide_market_min_edge,
        min_event_match_confidence=min_event_match_confidence,
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

    # Optional platform filter (post-pipeline)
    opps = opportunities
    if platform:
        opps = [o for o in opps if o.platform == platform]

    return OpportunitiesResponse(
        opportunities=[OpportunityOut(**dataclasses.asdict(o)) for o in opps],
        total=len(opps),
        quota_remaining=meta.get("quota_remaining"),
        sportsbook_markets_fetched=meta.get("sportsbook_markets_fetched", ["h2h"]),
        markets_dropped_by_type=meta.get("markets_dropped_by_type", {}),
        platforms_fetched=meta.get("platforms_fetched", []),
    )


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
    min_event_match_confidence: float = Query(default=DEFAULT_CONFIG.min_event_match_confidence, ge=0.0, le=1.0),
) -> dict:
    """Diagnostic endpoint — traces each pipeline stage."""
    cfg = EngineConfig(
        min_edge=min_edge,
        wide_market_min_edge=wide_market_min_edge,
        min_event_match_confidence=min_event_match_confidence,
    )
    try:
        return await diagnose_pipeline(cfg=cfg)
    except Exception as exc:
        logger.error("Debug pipeline failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
