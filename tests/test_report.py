"""What `inspect` says about a font, and the one threshold it shares with the build."""

import pytest
from helpers import glyph

from badgeware_fonts import af, glyphs, report

SQUARE = [[(0, 0), (60, 0), (60, -60), (0, -60)]]


def described(where, made, **kwargs):
    path = where / "font.af"
    path.write_bytes(af.pack(made, **kwargs))
    return report.describe(str(path))


def test_the_headline_counts_the_bytes_the_glyphs_and_the_points(tmp_path):
    lines = described(tmp_path, [glyph(ord("H"), SQUARE, bbox_w=60, bbox_h=81, advance=70)])
    assert "2 glyphs" not in lines[0]
    assert "1 glyphs, 4 points" in lines[0]


def test_a_capital_gives_the_cap_the_font_was_built_to(tmp_path):
    """The number a badge's draw.add_font takes, and the only one the .af does not record."""
    lines = described(tmp_path, [glyph(ord("H"), SQUARE, bbox_w=60, bbox_h=81, advance=70)])
    assert any(line == "  a capital stands 81" for line in lines)


def test_a_font_with_no_capital_says_nothing_about_the_cap(tmp_path):
    """An icon font has no H, so there is no capital to measure and the line is left out."""
    lines = described(tmp_path, [glyph(0xE81A, SQUARE, bbox_w=60, bbox_h=60, advance=100)])
    assert not any("a capital stands" in line for line in lines)


def test_the_grid_and_the_furthest_point_are_measured_against_the_limit(tmp_path):
    narrow = described(tmp_path, [glyph(ord("H"), SQUARE, bbox_w=60, bbox_h=60, advance=70)])
    assert any("narrow, 128 units per em" in line for line in narrow)
    assert any("furthest point 60 of 127" in line for line in narrow)

    wide = described(tmp_path, [glyph(ord("H"), [[(0, 0), (600, -648)]], bbox_w=600, bbox_h=648, advance=700)], units_per_em=1024)
    assert any("wide, 1024 units per em" in line for line in wide)
    assert any("furthest point 648 of 32767" in line for line in wide)


def test_the_range_of_codepoints_and_the_ascii_it_covers(tmp_path):
    lines = described(tmp_path, [glyph(point, SQUARE, bbox_w=60, bbox_h=60, advance=70) for point in (0x20, 0x41, 0xB0)])
    assert "codepoints 0x20..0xb0" in lines[1]
    assert "printable ASCII 2/95" in lines[1]
    assert "degree sign yes" in lines[1]


def test_a_font_without_the_degree_sign_says_so_in_capitals(tmp_path):
    """A temperature needs the degree sign, so its absence is printed in capitals."""
    lines = described(tmp_path, [glyph(ord("H"), SQUARE, bbox_w=60, bbox_h=60, advance=70)])
    assert "degree sign NO" in lines[1]


def test_the_tallest_glyph_is_named(tmp_path):
    made = [glyph(ord("H"), SQUARE, bbox_w=60, bbox_h=81, advance=70), glyph(ord("p"), SQUARE, bbox_w=60, bbox_h=99, advance=70)]
    assert any("tallest 'p' at 99" in line for line in described(tmp_path, made))


def test_inspect_and_the_build_share_one_units_mix_up_threshold(tmp_path):
    """One threshold, or inspect names glyphs the build passed and the two disagree."""
    accent = glyph(ord("i"), SQUARE, bbox_w=60, bbox_h=60, advance=30)
    muddled = glyph(ord("j"), SQUARE, bbox_w=60, bbox_h=60, advance=1)

    assert glyphs.faults([accent]) == []
    assert glyphs.faults([muddled])

    named = [line for line in described(tmp_path, [accent, muddled]) if "more ink than advance" in line]
    assert len(named) == 1
    assert "'j'" in named[0] and "'i'" not in named[0]


def test_a_font_with_no_glyphs_is_refused_rather_than_described(tmp_path):
    """describe() takes a max() over the glyphs, so an empty font has to be caught first."""
    path = tmp_path / "empty.af"
    # A well-formed header claiming no glyphs, contours or points.
    path.write_bytes(b"af!?" + bytes([0, 1, 0, 0, 0, 0, 0, 0]))
    with pytest.raises(af.AfError):
        report.describe(str(path))
