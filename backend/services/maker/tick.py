"""
Tick helpers for Kalshi binary markets.

Kalshi binary markets quote in integer cents (1¢ ticks, 1–99).  All planner
math is in dollars (float) for symmetry with the rest of the codebase, but
every persisted/proposed price routes through these helpers so floating
point error never produces an off-tick value.
"""
from __future__ import annotations

import math

TICK_DOLLARS: float = 0.01

# Epsilon to absorb float jitter when prices like 0.99 expand to 98.999...
# at 100x scaling.  Smaller than half a tick by many orders of magnitude.
_EPSILON: float = 1e-9


def round_down_to_tick(x: float) -> float:
    """Round ``x`` down to the nearest tick.  ``round_down_to_tick(0.444) == 0.44``."""
    return math.floor(x * 100 + _EPSILON) / 100.0


def round_up_to_tick(x: float) -> float:
    """Round ``x`` up to the nearest tick.  ``round_up_to_tick(0.401) == 0.41``."""
    return math.ceil(x * 100 - _EPSILON) / 100.0


def on_tick(x: float) -> bool:
    """True if ``x`` is exactly on a tick boundary (within float tolerance)."""
    return abs(x * 100 - round(x * 100)) < 1e-6
