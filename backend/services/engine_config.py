"""
Centralized configuration for the opportunity engine.

All tuneable thresholds live here — no magic numbers elsewhere.
"""
from dataclasses import dataclass


@dataclass
class EngineConfig:
    """All engine thresholds in one place."""

    # --- Edge thresholds ---
    min_edge: float = 0.05                         # 5% for normal-width markets
    wide_market_min_edge: float = 0.08             # 8% for wide markets

    # --- Probability floor ---
    min_true_probability: float = 0.40             # drop if p_true < 40%

    # --- Event match confidence (dual threshold) ---
    survival_threshold: float = 0.85               # below = SKIP
    buy_threshold: float = 0.90                    # below = WATCH, above = BUY-eligible

    # --- Line width ---
    max_line_width_for_normal_threshold: float = 0.35

    # --- FanDuel overround tiers ---
    overround_high_max: float = 0.03
    overround_medium_max: float = 0.06

    # --- Kelly sizing ---
    kelly_cap: float = 0.25                        # max full-Kelly fraction
    kelly_fraction: float = 0.20                   # fractional multiplier (1/5 Kelly)

    # --- Cost buffer ---
    cost_buffer: float = 0.01                      # 1 cent trading cost

    # --- Platform price range ---
    min_price: float = 0.02
    max_price: float = 0.98

    # --- Name matching ---
    min_name_length: int = 3                       # ignore last names < 3 chars

    # --- Ambiguity protection ---
    min_confidence_gap: float = 0.05               # gap between 1st and 2nd best match
    max_competing_matches: int = 1                 # max events that survive matching

    # --- Price-probability coherence ---
    max_price_prob_divergence: float = 0.40        # |pm_price - p_true| above this → likely side inversion

    # --- Date strictness ---
    max_date_delta_hours: float = 72.0             # beyond 3 days with no competing match → SKIP

    # --- Edge sanity ---
    max_plausible_edge: float = 0.20               # edges above 20% are likely data errors → DOWNGRADE

    # --- Metadata completeness ---
    require_end_date: bool = False                 # if True, missing end_date → downgrade

    # --- Player props ---
    enable_props: bool = False                     # feature flag — OFF by default
    max_props_per_event: int = 20                  # cap prop features per game to prevent explosion
