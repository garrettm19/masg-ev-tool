"""
Tests for services.normalizer — name normalization edge cases.

Covers:
  - diacritics (Polish, French, Czech, Spanish, Norwegian)
  - hyphens (single, double)
  - apostrophes
  - periods/initials
  - short names
  - multi-word names
  - empty/edge inputs
  - whole-word matching collision avoidance
"""
import pytest
from services.normalizer import normalize_name, last_name, tokenize, name_appears_in_text


class TestNormalizeName:
    # --- Basic ---
    def test_basic_lowercase(self):
        assert normalize_name("Carlos Alcaraz") == "carlos alcaraz"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_extra_whitespace(self):
        assert normalize_name("  Carlos   Alcaraz  ") == "carlos alcaraz"

    def test_numbers_preserved(self):
        assert normalize_name("Player 1") == "player 1"

    # --- Accents / diacritics ---
    def test_polish_accents(self):
        assert normalize_name("Iga Świątek") == "iga swiatek"

    def test_french_accents(self):
        assert normalize_name("Gaël Monfils") == "gael monfils"

    def test_czech_accents(self):
        assert normalize_name("Tomáš Macháč") == "tomas machac"

    def test_spanish_tilde(self):
        assert normalize_name("Muñoz") == "munoz"

    def test_norwegian_no_accent(self):
        assert normalize_name("Casper Ruud") == "casper ruud"

    def test_german_umlaut(self):
        assert normalize_name("Müller") == "muller"

    def test_turkish_cedilla(self):
        assert normalize_name("Çağla Büyükakçay") == "cagla buyukakcay"

    def test_romanian_accents(self):
        assert normalize_name("Simona Halep") == "simona halep"

    def test_japanese_romanized(self):
        assert normalize_name("Naomi Ōsaka") == "naomi osaka"

    # --- Hyphens ---
    def test_hyphenated_name(self):
        assert normalize_name("Félix Auger-Aliassime") == "felix auger aliassime"

    def test_double_hyphen(self):
        assert normalize_name("Jean-Luc Picard-Riker") == "jean luc picard riker"

    # --- Punctuation ---
    def test_apostrophe(self):
        assert normalize_name("Jannik O'Sullivan") == "jannik osullivan"

    def test_period_in_name(self):
        assert normalize_name("A.J. Fox") == "aj fox"

    def test_period_initial_jr(self):
        assert normalize_name("R. Federer Jr.") == "r federer jr"

    def test_comma(self):
        assert normalize_name("Last, First") == "last first"

    # --- Short / multi-word ---
    def test_short_name(self):
        assert normalize_name("Li Na") == "li na"

    def test_multi_word_surname(self):
        assert normalize_name("Alex de Minaur") == "alex de minaur"

    def test_van_prefix(self):
        assert normalize_name("Robin van Persie") == "robin van persie"

    def test_multi_word_team(self):
        assert normalize_name("Kolkata Knight Riders") == "kolkata knight riders"

    def test_single_word(self):
        assert normalize_name("Ronaldo") == "ronaldo"


class TestLastName:
    def test_two_words(self):
        assert last_name("carlos alcaraz") == "alcaraz"

    def test_single_word(self):
        assert last_name("alcaraz") == "alcaraz"

    def test_three_words(self):
        assert last_name("felix auger aliassime") == "aliassime"

    def test_empty(self):
        assert last_name("") == ""

    def test_multi_word_surname_gets_last_token(self):
        assert last_name("alex de minaur") == "minaur"


class TestTokenize:
    def test_basic(self):
        assert tokenize("carlos alcaraz") == {"carlos", "alcaraz"}

    def test_single(self):
        assert tokenize("alcaraz") == {"alcaraz"}

    def test_three_tokens(self):
        assert tokenize("felix auger aliassime") == {"felix", "auger", "aliassime"}


class TestNameAppearsInText:
    def test_last_name_match(self):
        text = normalize_name("Will Alcaraz beat Sinner?")
        assert name_appears_in_text("carlos alcaraz", text)

    def test_team_name_match(self):
        text = normalize_name("Will Kolkata Knight Riders beat Chennai Super Kings?")
        assert name_appears_in_text("kolkata knight riders", text)

    def test_short_name_below_threshold(self):
        text = normalize_name("Will Li beat Na?")
        assert not name_appears_in_text("li na", text, min_len=3)

    def test_partial_no_match(self):
        text = normalize_name("Will Alcaraz beat Sinner?")
        assert not name_appears_in_text("carlos nadal", text)

    def test_hyphenated_in_text(self):
        text = normalize_name("Auger-Aliassime vs Sinner")
        assert name_appears_in_text("felix auger aliassime", text)

    def test_accented_in_text(self):
        text = normalize_name("Świątek vs Sabalenka")
        assert name_appears_in_text("iga swiatek", text)

    def test_no_substring_false_positive(self):
        """'lee' should not match 'sleep' — word boundary required."""
        text = "he fell asleep"
        assert not name_appears_in_text("duck hee lee", text)

    def test_word_boundary_match(self):
        text = "lee vs kim"
        assert name_appears_in_text("duck hee lee", text)
