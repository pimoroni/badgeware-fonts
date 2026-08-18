"""Which codepoints a font packs, and how a spec names them."""

import pytest
from helpers import refuses

from badgeware_fonts import charsets
from badgeware_fonts.af import ManifestError


def test_a_range_skips_the_codepoints_unicode_has_not_assigned():
    """A charset naming a whole block would otherwise take in the holes in it."""
    # U+0378 and U+0379 are the unassigned pair before GREEK YPOGEGRAMMENI.
    assert charsets._named(0x0377, 0x037A) == {0x0377, 0x037A}


def test_a_range_can_be_narrowed_to_the_names_it_holds():
    """What `latin` is: the letters out of blocks that hold punctuation and symbols too."""
    letters = charsets._named(0x0370, 0x037A, "LETTER")
    assert 0x0370 in letters
    # A numeral sign is in the range and is not a letter.
    assert 0x0374 not in letters


def test_latin_covers_ascii_the_degree_sign_and_the_accents():
    latin = charsets.BUILTIN["latin"]
    assert {ord(" "), ord("~"), 0xB0, 0xD7, 0xF7} <= latin
    assert {0xC0, 0x17F} <= latin
    # Nothing outside the Latin blocks it names.
    assert max(latin) == 0x17F


@pytest.mark.parametrize("text, expected", [("U+00B0", 0xB0), ("0xb0", 0xB0), ("b0", 0xB0), ("\\u00B0", 0xB0), (" B0 ", 0xB0)])
def test_a_codepoint_is_read_in_any_of_its_spellings(text, expected):
    assert charsets.parse_codepoint(text, "x") == expected


def test_a_codepoint_that_is_not_hex_is_refused_where_it_was_given():
    with refuses("somewhere", "wobble", error=ManifestError):
        charsets.parse_codepoint("wobble", "somewhere")


def test_a_range_that_ends_below_where_it_starts_is_refused():
    with pytest.raises(ManifestError):
        charsets.parse_range("U+0040-U+0020", "x")


def test_a_single_codepoint_is_a_range_of_one():
    assert list(charsets.parse_range("U+00B0", "x")) == [0xB0]


def test_chars_takes_characters_and_not_a_number():
    with refuses("chars", 5, error=ManifestError):
        charsets.resolve(chars=5, where="x")


def test_an_unknown_charset_lists_the_ones_there_are():
    with refuses("lantin", error=ManifestError):
        charsets.resolve(charset="lantin", where="x")


def test_a_spec_with_nothing_in_it_falls_back_to_latin():
    assert charsets.resolve(where="x") == sorted(charsets.BUILTIN["latin"])


def test_codepoints_describe_as_the_runs_they_fall_into():
    assert charsets.describe([0x20, 0x21, 0x22, 0xB0, 0xC0, 0xC1]) == "0020-0022, 00b0, 00c0-00c1"


def test_a_single_codepoint_describes_without_a_range():
    assert charsets.describe([0xB0]) == "00b0"


def test_no_codepoints_describe_as_nothing():
    assert charsets.describe([]) == ""
