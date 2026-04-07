"""
Robust name normalization for player/team matching.

Handles diacritics, hyphens, punctuation, and common variations.
"""
import re
import unicodedata


def normalize_name(name: str) -> str:
    """
    Full normalization pipeline:
      1. NFKD decompose + strip combining marks (diacritics)
      2. Lowercase
      3. Replace hyphens with spaces (e.g. "Auger-Aliassime" -> "auger aliassime")
      4. Strip all non-alphanumeric / non-space characters
      5. Collapse whitespace
    """
    # Decompose and strip combining characters (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(
        ch for ch in nfkd if unicodedata.category(ch) != "Mn"
    )
    lowered = stripped.lower()
    # Hyphens become spaces
    lowered = lowered.replace("-", " ")
    # Strip punctuation (keep letters, digits, spaces)
    cleaned = re.sub(r"[^a-z0-9\s]", "", lowered)
    # Collapse whitespace
    return " ".join(cleaned.split())


def last_name(name_norm: str) -> str:
    """Extract last token from a normalized name."""
    parts = name_norm.split()
    return parts[-1] if parts else name_norm


def tokenize(name_norm: str) -> set[str]:
    """Return the set of word tokens in a normalized name."""
    return set(name_norm.split())


def name_appears_in_text(name_norm: str, text_norm: str, min_len: int = 3) -> bool:
    """
    Check if a player's last name appears as a whole word in text.

    Falls back to full-name substring match for team sports.
    """
    ln = last_name(name_norm)
    if len(ln) >= min_len:
        if re.search(r"\b" + re.escape(ln) + r"\b", text_norm):
            return True
    # Full-name substring (team sports)
    if len(name_norm) >= min_len and name_norm in text_norm:
        return True
    return False
