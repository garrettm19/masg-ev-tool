"""
Devig (vig removal) for binary and 3-way markets.
Multiplicative method: divide each implied prob by the overround.
"""


def devig_multiplicative(p_yes_impl: float, p_no_impl: float) -> tuple[float, float]:
    """
    Remove vig from a binary market using the multiplicative (proportional) method.
    Returns (p_true_yes, p_true_no) that sum to 1.0.
    """
    overround = p_yes_impl + p_no_impl
    if overround <= 0:
        return 0.5, 0.5
    return round(p_yes_impl / overround, 4), round(p_no_impl / overround, 4)


def devig_3way(
    p_home_impl: float,
    p_away_impl: float,
    p_draw_impl: float,
) -> tuple[float, float, float]:
    """
    Remove vig from a 3-way market (home/away/draw) using the multiplicative method.
    Returns (p_true_home, p_true_away, p_true_draw) that sum to 1.0.
    """
    overround = p_home_impl + p_away_impl + p_draw_impl
    if overround <= 0:
        return 0.3333, 0.3333, 0.3334
    return (
        round(p_home_impl / overround, 4),
        round(p_away_impl / overround, 4),
        round(p_draw_impl / overround, 4),
    )
