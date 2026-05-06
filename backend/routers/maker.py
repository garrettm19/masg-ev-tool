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

import dataclasses
import logging
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from services.maker.config import (
    MakerConfig,
    get_maker_config,
    set_maker_config,
)
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


# ---------------------------------------------------------------------------
# Runtime maker config — GET to inspect, POST to update safe fields only.
# Unsafe fields (paper_only, platforms, market_types) are NOT in the update
# request model and are clamped to their safe values on every write.
# Live trading is impossible: there is no order-placement code anywhere.
# ---------------------------------------------------------------------------

# Allowed mutable fields.  Anything not in this set is filtered out before
# applying.  Keep in sync with MakerConfigUpdateRequest.
_SAFE_UPDATE_FIELDS: frozenset[str] = frozenset({
    "enabled",
    "min_estimated_maker_edge",
    "max_book_age_seconds",
    "max_fd_age_seconds",
    "require_min_spread",
    "max_contracts_per_order",
    "max_notional_per_order_usd",
    "max_notional_per_market_usd",
    "max_open_orders_total",
    "max_open_orders_per_market",
    "max_orders_per_hour",
    "max_daily_notional_usd",
    "default_ttl_seconds",
    "cancel_before_event_offset_s",
})


class MakerConfigResponse(BaseModel):
    """Full runtime config view.  ``paper_only`` / ``platforms`` /
    ``market_types`` are surfaced so the caller can see they are locked,
    but they cannot be changed via POST."""
    enabled: bool
    paper_only: bool
    platforms: list[str]
    market_types: list[str]
    min_estimated_maker_edge: float
    require_min_spread: float
    max_book_age_seconds: float
    max_fd_age_seconds: float
    max_contracts_per_order: int
    max_notional_per_order_usd: float
    max_notional_per_market_usd: float
    max_open_orders_total: int
    max_open_orders_per_market: int
    max_orders_per_hour: int
    max_daily_notional_usd: float
    default_ttl_seconds: int
    cancel_before_event_offset_s: int


class MakerConfigUpdateRequest(BaseModel):
    """Subset of MakerConfig that is safe to mutate at runtime.

    Unsafe fields (``paper_only``, ``platforms``, ``market_types``) are
    intentionally absent.  Pydantic ignores unknown JSON keys by default,
    so a client sending ``paper_only=false`` is silently dropped — and
    the endpoint additionally clamps the resulting config to enforce the
    safety invariants regardless of input.
    """
    enabled: bool | None = None
    min_estimated_maker_edge: float | None = None
    max_book_age_seconds: float | None = None
    max_fd_age_seconds: float | None = None
    require_min_spread: float | None = None
    max_contracts_per_order: int | None = None
    max_notional_per_order_usd: float | None = None
    max_notional_per_market_usd: float | None = None
    max_open_orders_total: int | None = None
    max_open_orders_per_market: int | None = None
    max_orders_per_hour: int | None = None
    max_daily_notional_usd: float | None = None
    default_ttl_seconds: int | None = None
    cancel_before_event_offset_s: int | None = None


def _to_response(cfg: MakerConfig) -> MakerConfigResponse:
    return MakerConfigResponse(
        enabled=cfg.enabled,
        paper_only=cfg.paper_only,
        platforms=list(cfg.platforms),
        market_types=list(cfg.market_types),
        min_estimated_maker_edge=cfg.min_estimated_maker_edge,
        require_min_spread=cfg.require_min_spread,
        max_book_age_seconds=cfg.max_book_age_seconds,
        max_fd_age_seconds=cfg.max_fd_age_seconds,
        max_contracts_per_order=cfg.max_contracts_per_order,
        max_notional_per_order_usd=cfg.max_notional_per_order_usd,
        max_notional_per_market_usd=cfg.max_notional_per_market_usd,
        max_open_orders_total=cfg.max_open_orders_total,
        max_open_orders_per_market=cfg.max_open_orders_per_market,
        max_orders_per_hour=cfg.max_orders_per_hour,
        max_daily_notional_usd=cfg.max_daily_notional_usd,
        default_ttl_seconds=cfg.default_ttl_seconds,
        cancel_before_event_offset_s=cfg.cancel_before_event_offset_s,
    )


def _enforce_safety(cfg: MakerConfig) -> MakerConfig:
    """Force the paper-mode safety invariants regardless of caller input.
    Defense-in-depth: ``MakerConfigUpdateRequest`` already excludes these
    fields, but this clamp guarantees the runtime singleton can never be
    set to an unsafe value via this endpoint."""
    return dataclasses.replace(
        cfg,
        paper_only=True,
        platforms=("kalshi",),
        market_types=("h2h",),
    )


@router.get("/maker/config", response_model=MakerConfigResponse)
def get_maker_config_endpoint() -> MakerConfigResponse:
    """Return the current runtime maker config.  Empty store / no override
    ⇒ disabled paper-only defaults."""
    return _to_response(get_maker_config())


@router.post("/maker/config", response_model=MakerConfigResponse)
def update_maker_config_endpoint(req: MakerConfigUpdateRequest) -> MakerConfigResponse:
    """Update the runtime maker config with safe paper-mode fields only.

    Returns the updated config so the caller can confirm the safety
    invariants (``paper_only=True``, ``platforms=["kalshi"]``,
    ``market_types=["h2h"]``) are still in place.
    """
    current = get_maker_config()
    raw = req.model_dump(exclude_unset=True)
    safe_updates = {
        k: v for k, v in raw.items()
        if k in _SAFE_UPDATE_FIELDS and v is not None
    }
    updated = dataclasses.replace(current, **safe_updates)
    updated = _enforce_safety(updated)
    new = set_maker_config(updated)
    return _to_response(new)


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
