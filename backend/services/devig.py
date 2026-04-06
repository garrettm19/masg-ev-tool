"""
Devig (vig removal) for binary markets.
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
