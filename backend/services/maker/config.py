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


# Default singleton for callers that don't construct their own config.
# Disabled by default — production scans pass through this and run no maker
# planning unless a caller explicitly opts in via the runtime config.
DEFAULT_MAKER_CONFIG = MakerConfig()


# Runtime-mutable config replacing the static default for the normal
# refresh path.  When unset, callers see DEFAULT_MAKER_CONFIG (disabled).
# Mutated only via set_maker_config (called by the maker config endpoint).
_runtime_maker_config: MakerConfig | None = None


def get_maker_config() -> MakerConfig:
    """Return the active maker config — runtime override if set, else the
    disabled default.  Resolved at call time so the value reflects the most
    recent ``set_maker_config`` call."""
    return _runtime_maker_config if _runtime_maker_config is not None else DEFAULT_MAKER_CONFIG


def set_maker_config(config: MakerConfig) -> MakerConfig:
    """Replace the runtime maker config.  Returns the new active config.

    Callers (typically the ``POST /api/maker/config`` endpoint) are expected
    to enforce the paper-mode safety invariants — ``paper_only=True``,
    ``platforms=("kalshi",)``, ``market_types=("h2h",)`` — before calling
    this; the function itself does no validation.
    """
    global _runtime_maker_config
    _runtime_maker_config = config
    return _runtime_maker_config


def reset_maker_config() -> None:
    """Reset the runtime override to ``None`` so ``get_maker_config`` falls
    back to ``DEFAULT_MAKER_CONFIG``.  Used by tests and by any future admin
    "stop maker" path."""
    global _runtime_maker_config
    _runtime_maker_config = None
