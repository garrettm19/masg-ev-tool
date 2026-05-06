"""
Read-only maker proposal endpoints.

Exposes the paper maker proposal store under ``/api/maker``.  Read-only
by design: no POST/PUT/DELETE, no order placement, no live trading.

Two endpoints:

  GET /api/maker/proposals
      Filterable list of recent paper proposal records.

  GET /api/maker/summary
      Aggregate counts and top rejection reasons.

Both endpoints return empty results gracefully when the store directory
is missing or empty.  Corrupt JSONL lines are skipped at the store
layer with a logged warning.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from services.maker.state import (
    PaperMakerStore,
    STATUS_PAPER_ACTIVE,
    STATUS_PAPER_REJECTED,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Lazy module-level singleton.  Production callers share one store
# instance; tests use FastAPI's ``app.dependency_overrides`` to swap
# in a tmp-path-backed store without touching this module.
_default_store: PaperMakerStore | None = None


def get_paper_store() -> PaperMakerStore:
    global _default_store
    if _default_store is None:
        _default_store = PaperMakerStore()
    return _default_store


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MakerProposalsResponse(BaseModel):
    days: int
    count: int
    proposals: list[dict[str, Any]]


class TopRejectionReason(BaseModel):
    reason: str
    count: int


class MakerSummaryResponse(BaseModel):
    days: int
    total: int
    eligible: int
    rejected: int
    by_status: dict[str, int]
    by_platform: dict[str, int]
    top_rejection_reasons: list[TopRejectionReason]
    average_estimated_maker_edge: float | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/maker/proposals", response_model=MakerProposalsResponse)
def list_maker_proposals(
    days: int = Query(1, ge=1, le=90),
    status: str | None = Query(None),
    eligible: bool | None = Query(None),
    platform: str | None = Query(None),
    market_id: str | None = Query(None),
    store: PaperMakerStore = Depends(get_paper_store),
) -> MakerProposalsResponse:
    """Return recent paper maker proposals.

    Filterable by ``status``, ``eligible``, ``platform``, ``market_id``.
    Empty store ⇒ empty list (200 OK, never 404).
    """
    records = store.read_recent(days=days)

    def _matches(rec: dict) -> bool:
        if status is not None and rec.get("status") != status:
            return False
        if eligible is not None and bool(rec.get("eligible")) != eligible:
            return False
        if platform is not None and rec.get("platform") != platform:
            return False
        if market_id is not None and rec.get("market_id") != market_id:
            return False
        return True

    filtered = [r for r in records if _matches(r)]
    return MakerProposalsResponse(
        days=days,
        count=len(filtered),
        proposals=filtered,
    )


@router.get("/maker/summary", response_model=MakerSummaryResponse)
def maker_summary(
    days: int = Query(1, ge=1, le=90),
    top_n: int = Query(10, ge=1, le=50),
    store: PaperMakerStore = Depends(get_paper_store),
) -> MakerSummaryResponse:
    """Aggregated counts for recent paper proposals."""
    records = store.read_recent(days=days)

    by_status: Counter[str] = Counter()
    by_platform: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    edges: list[float] = []

    for rec in records:
        st = rec.get("status", "")
        if st:
            by_status[st] += 1
        plat = rec.get("platform", "")
        if plat:
            by_platform[plat] += 1
        if rec.get("eligible"):
            edge = rec.get("estimated_maker_edge")
            if isinstance(edge, (int, float)):
                edges.append(float(edge))
        else:
            for code in rec.get("rejection_reasons") or []:
                if isinstance(code, str):
                    rejection_reasons[code] += 1

    top = [
        TopRejectionReason(reason=code, count=cnt)
        for code, cnt in rejection_reasons.most_common(top_n)
    ]

    return MakerSummaryResponse(
        days=days,
        total=len(records),
        eligible=by_status.get(STATUS_PAPER_ACTIVE, 0),
        rejected=by_status.get(STATUS_PAPER_REJECTED, 0),
        by_status=dict(by_status),
        by_platform=dict(by_platform),
        top_rejection_reasons=top,
        average_estimated_maker_edge=(
            round(sum(edges) / len(edges), 6) if edges else None
        ),
    )
