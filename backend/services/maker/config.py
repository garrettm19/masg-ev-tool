"""
MakerConfig — all maker-planner thresholds in one place.

Defaults are conservative and the layer is disabled (``enabled=False``).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MakerConfig:
    """All maker thresholds in one place."""

    # --- Global gates ---
    enabled: bool = False
    paper_only: bool = True
    platforms: tuple[str, ...] = ("kalshi",)
    market_types: tuple[str, ...] = ("h2h",)

    # --- Eligibility ---
    min_estimated_maker_edge: float = 0.05
    require_min_spread: float = 0.02

    # --- Staleness ---
    max_book_age_seconds: float = 30.0
    max_fd_age_seconds: float = 600.0

    # --- Sizing (config-only in v1; planner math doesn't size positions yet) ---
    max_contracts_per_order: int = 50
    max_notional_per_order_usd: float = 25.0
    max_notional_per_market_usd: float = 50.0
    max_open_orders_total: int = 10
    max_open_orders_per_market: int = 1
    max_orders_per_hour: int = 20
    max_daily_notional_usd: float = 250.0

    # --- Lifecycle (config-only in v1) ---
    default_ttl_seconds: int = 1800
    cancel_before_event_offset_s: int = 600
