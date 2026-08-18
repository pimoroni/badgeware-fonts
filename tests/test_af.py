"""The container: bytes written, bytes read back, and the glyphs turned away."""

import struct

import pytest
from helpers import glyph, refuses

from badgeware_fonts import af


def test_a_packed_font_reads_back_the_way_it_was_written():
    """The encoder and the decoder are held to each other here.

    Two definitions that disagree do not fail: the font packs, loads, and draws wrong.
    """
    square = [[(0, 0), (90, 0), (90, -90), (0, -90)]]
    packed = af.pack([glyph(ord("b"), square, bbox_w=90, bbox_h=90, advance=95), glyph(ord(" "), [], advance=25)])

    font = af.unpack(packed)
    assert not font["wide"]
    assert font["units_per_em"] == af.NARROW_UNITS_PER_EM
    space, letter = font["glyphs"]
    assert (letter["codepoint"], letter["bbox_w"], letter["bbox_h"], letter["advance"], letter["contours"]) == (ord("b"), 90, 90, 95, 1)
    assert letter["points"] == (0, 0, 90, 0, 90, -90, 0, -90)
    # A blank glyph carries an advance and no ink, so the words still separate.
    assert (space["advance"], space["contours"], space["points"]) == (25, 0, ())


def test_a_wide_font_records_the_grid_it_was_built_to():
    font = af.unpack(af.pack([glyph(ord("H"), [[(0, 0), (600, 0), (600, -648)]], bbox_w=600, bbox_h=648, advance=700)], units_per_em=1024))
    assert font["wide"]
    assert font["units_per_em"] == 1024
    cap = font["glyphs"][0]
    assert (cap["bbox_w"], cap["bbox_h"], cap["advance"]) == (600, 648, 700)
    assert cap["points"] == (0, 0, 600, 0, 600, -648)


def test_glyphs_pack_in_codepoint_order():
    """Two builds of one corpus agree whatever order the entries arrived in."""
    ink = [[(0, 0), (10, 0), (10, -10), (0, -10)]]
    forwards = af.pack([glyph(point, ink, advance=20) for point in (0x41, 0x42, 0x43)])
    backwards = af.pack([glyph(point, ink, advance=20) for point in (0x43, 0x41, 0x42)])
    assert forwards == backwards


def test_the_cap_height_decides_the_coordinate_width():
    """A narrow coordinate is a signed byte, so a cap above 127 widens the whole font."""
    assert not af.wide_for(81)
    assert af.units_per_em_for(81) is None
    assert af.wide_for(648)
    # 648/1024 is 81/128, so a given font_size draws the same height at either width.
    assert af.units_per_em_for(648) == 1024
    assert af.units_per_em_for(122) is None


def test_a_glyph_the_format_cannot_hold_is_reported():
    over = glyph(ord("a"), [[(0, 0), (200, -50), (10, -300)]])
    assert af.out_of_range([over]) == [ord("a")]
    assert af.out_of_range([over], wide=True) == []

    fits = glyph(ord("b"), [[(0, 0), (90, 0), (90, -90), (0, -90), (0, 0)]], bbox_w=90, bbox_h=90, advance=90)
    assert af.out_of_range([fits]) == []


def test_the_header_matches_the_layout_it_declares():
    fits = glyph(ord("b"), [[(0, 0), (90, 0), (90, -90), (0, -90), (0, 0)]], bbox_w=90, bbox_h=90, advance=90)
    blob = af.pack([fits])
    assert blob[:4] == b"af!?"
    _flags, glyphs, contours, points = struct.unpack(">HHHH", blob[4:12])
    assert (glyphs, contours, points) == (1, 1, 5)
    codepoint, _bx, _by, _bw, _bh, advance, count = struct.unpack(">HbbBBBB", blob[12:20])
    assert (codepoint, advance, count) == (ord("b"), 90, 1)
    # Header, glyph table, one contour length, then the points.
    assert len(blob) == 12 + 8 + 2 + 5 * 2


def test_a_codepoint_over_a_u16_is_refused():
    """A Material Symbol above U+FFFF fits only remapped. The error names the remedy."""
    high = glyph(0x1FFF0, [[(0, 0), (10, 0), (10, -10), (0, 0)]])
    with refuses("1fff0"):
        af.pack([high])


def test_an_em_over_a_u16_is_refused():
    with refuses(70000):
        af.pack([glyph(ord("H"), [], advance=10)], units_per_em=70000)


def test_data_that_is_not_a_font_is_refused_by_name():
    with refuses("somefont.af"):
        af.unpack(b"not a font at all", "somefont.af")


def test_a_glyph_that_would_pack_clamped_is_reported():
    """Points, the bbox and the advance alike: `pack` clamps all of them in silence."""
    ink = [[(0, 0), (90, 0), (90, -90)]]
    assert af.out_of_range([glyph(ord("a"), ink, advance=300)]) == [ord("a")]
    assert af.out_of_range([glyph(ord("a"), ink, advance=90, bbox_w=300)]) == [ord("a")]
    assert af.out_of_range([glyph(ord("a"), ink, advance=90, bbox_h=300)]) == [ord("a")]
    assert af.out_of_range([glyph(ord("a"), ink, advance=90, bbox_x=-200)]) == [ord("a")]
    assert af.out_of_range([glyph(ord("a"), ink, advance=90, bbox_y=-200)]) == [ord("a")]
    # All of it fits wide.
    assert af.out_of_range([glyph(ord("a"), ink, advance=300, bbox_w=300)], wide=True) == []
    assert af.out_of_range([glyph(ord("a"), ink, advance=90, bbox_w=90, bbox_h=90)]) == []


def test_an_advance_over_the_byte_would_pack_clamped():
    """Which is why `out_of_range` covers it and the caller drops the glyph."""
    packed = af.pack([glyph(ord("a"), [[(0, 0), (90, 0), (90, -90)]], advance=300)])
    assert af.unpack(packed)["glyphs"][0]["advance"] == 255


def test_a_file_cut_short_is_refused_wherever_the_cut_falls():
    """Every read is bounds checked: a failed transfer is a named error, not a traceback."""
    whole = af.pack([glyph(ord("a"), [[(0, 0), (90, 0), (90, -90)]], advance=90)])
    for length in range(4, len(whole)):
        with pytest.raises(af.AfError):
            af.unpack(whole[:length], "cut.af")


def byte_counted():
    """Contour lengths a byte each, as afinate writes them and this encoder does not."""
    return af.AF_MAGIC + struct.pack(af.HEADER, 0, 1, 1, 3) + struct.pack(af.GLYPH_STRUCT, ord("a"), 0, 0, 90, 90, 90, 1) + bytes([3]) + struct.pack(">6b", 0, 0, 90, 0, 90, -90)


def test_contour_lengths_a_byte_each_read_back_the_same_outline():
    font = af.unpack(byte_counted())
    assert not font["flags"] & af.AF_FLAG_16BIT_POINT_COUNT
    assert font["glyphs"][0]["outlines"] == [[(0, 0), (90, 0), (90, -90)]]


def test_a_byte_counted_font_cut_short_is_refused_too():
    """An IndexError there, not a struct error, and the same named failure either way."""
    whole = byte_counted()
    for length in range(4, len(whole)):
        with pytest.raises(af.AfError):
            af.unpack(whole[:length], "cut.af")


def test_a_font_of_more_points_than_the_header_counts_is_refused():
    """The header counts glyphs, contours and points as u16. Struct puts it as `H` format."""
    huge = glyph(ord("a"), [[(index % 90, 0) for index in range(0x10000)]], advance=90)
    with refuses(65536, "points"):
        af.pack([huge])


def test_a_font_of_more_contours_than_the_header_counts_is_refused():
    many = glyph(ord("a"), [[(0, 0), (10, 0), (10, -10)] for _ in range(0x10000)], advance=90)
    with refuses(65536, "contours"):
        af.pack([many])
