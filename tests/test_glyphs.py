"""What a badge cannot draw, and what it draws despite."""

from helpers import glyph, refuses

from badgeware_fonts import glyphs, grid
from badgeware_fonts.outlines import MAX_CONTOUR


def ring(points):
    """A contour of `points` points, wide enough to carry a plausible advance."""
    return [[(index % 60, -(index % 60)) for index in range(points)]]


def test_a_contour_over_the_renderer_buffer_is_a_fault():
    """The renderer fills each contour into a fixed buffer, skipping any that overflows."""
    over = glyph(ord("H"), ring(MAX_CONTOUR + 1), bbox_w=60, advance=70)
    faults = glyphs.faults([over])
    assert len(faults) == 1
    assert f"over {MAX_CONTOUR}" in faults[0]
    assert "raise quality until it is under" in faults[0]


def test_a_contour_at_the_buffer_limit_is_not_a_fault():
    assert glyphs.faults([glyph(ord("H"), ring(MAX_CONTOUR), bbox_w=60, advance=70)]) == []


def test_one_fault_per_glyph_however_many_contours_overflow():
    """A glyph either draws or it does not; a fault per contour repeats one finding."""
    both = glyph(ord("H"), ring(MAX_CONTOUR + 1) + ring(MAX_CONTOUR + 1), bbox_w=60, advance=70)
    assert len(glyphs.faults([both])) == 1


def test_ink_with_almost_no_advance_is_a_fault():
    """A units mix-up packs and loads without complaint, then draws a word in one place."""
    muddled = glyph(ord("j"), ring(4), bbox_w=60, advance=1)
    assert glyphs.faults([muddled]) == ["'j' advance 1 against 60 of ink"]


def test_an_accent_overhanging_its_advance_is_not_a_fault():
    """A dieresis is wider than the i it sits on, legitimately."""
    assert glyphs.faults([glyph(ord("ï"), ring(4), bbox_w=60, advance=30)]) == []


def test_the_advance_a_glyph_must_keep_sits_between_the_two():
    at_threshold = int(60 * grid.MIN_ADVANCE_RATIO)
    assert glyphs.faults([glyph(ord("j"), ring(4), bbox_w=60, advance=at_threshold - 1)])
    assert glyphs.faults([glyph(ord("j"), ring(4), bbox_w=60, advance=at_threshold + 1)]) == []


def test_an_icon_is_not_judged_on_its_advance():
    """An icon's advance is its box: made up rather than measured, so the ratio is moot."""
    icon = glyph(0xE81A, ring(4), bbox_w=100, advance=1)
    assert glyphs.faults([icon], text=False) == []
    assert glyphs.faults([icon], text=True)


def test_a_blank_glyph_is_not_judged_on_its_advance():
    """A space carries an advance and no ink, so there is no ink for the ratio to measure."""
    assert glyphs.faults([glyph(ord(" "), [], bbox_w=0, advance=25)]) == []


def test_the_axis_aliases_reach_the_tag_whatever_the_manifest_calls_it():
    for name in ("weight", "Weight", "WEIGHT"):
        assert glyphs.AXIS_ALIASES[name.lower()] == "wght"
    # A tag given directly needs no alias.
    assert "wght" not in glyphs.AXIS_ALIASES


def test_asking_for_no_axes_applies_none():
    applied, ignored = glyphs.set_axes(face=None, requested={})
    assert (applied, ignored) == ({}, [])
    assert glyphs.set_axes(face=None, requested=None) == ({}, [])


def test_a_face_freetype_cannot_read_is_refused_by_path(tmp_path):
    path = tmp_path / "notafont.ttf"
    path.write_bytes(b"this is not a font")
    with refuses("notafont.ttf"):
        glyphs.open_face(path, ppem=1000)


class Axis:
    def __init__(self, tag, minimum, maximum, default):
        self.tag = tag.encode()
        self.minimum, self.maximum, self.default = minimum, maximum, default


class VariableFace:
    """What `set_axes` reads of a face: its axes, and somewhere to put the coordinates."""

    def __init__(self, *axes):
        self.axes = axes
        self.coords = None

    def get_variation_info(self):
        return self

    def set_var_design_coords(self, coords):
        self.coords = coords


WGHT = ("wght", 100.0, 900.0, 400.0)
FILL = ("FILL", 0.0, 1.0, 0.0)


def test_an_axis_is_matched_on_its_tag_and_not_its_name():
    """`wght` reaches the axis whether the face calls it Weight or Grosor."""
    face = VariableFace(Axis(*WGHT), Axis(*FILL))
    applied, ignored = glyphs.set_axes(face, {"weight": 700, "FILL": 1})
    assert applied == {"wght": 700, "FILL": 1}
    assert ignored == []
    # Design coordinates in the face's axis order, not the order the entry listed them.
    assert face.coords == [700, 1]


def test_an_axis_the_face_leaves_out_keeps_its_default():
    face = VariableFace(Axis(*WGHT), Axis(*FILL))
    applied, _ignored = glyphs.set_axes(face, {"wght": 700})
    assert applied == {"wght": 700}
    assert face.coords == [700, 0.0]


def test_an_axis_the_face_has_not_got_comes_back_spelled_as_it_was_asked_for():
    """So the warning names the key in the manifest and not the tag it was folded to."""
    face = VariableFace(Axis(*WGHT))
    applied, ignored = glyphs.set_axes(face, {"wght": 700, "FIL": 1})
    assert (applied, ignored) == ({"wght": 700}, ["FIL"])


def test_a_face_where_nothing_matched_is_left_alone():
    """set_var_design_coords goes uncalled, rather than being called with every default."""
    face = VariableFace(Axis(*WGHT))
    applied, ignored = glyphs.set_axes(face, {"FIL": 1})
    assert (applied, ignored) == ({}, ["FIL"])
    assert face.coords is None


def test_a_value_outside_the_axis_range_is_refused_by_the_range():
    face = VariableFace(Axis(*WGHT))
    with refuses("wght", 950, 100, 900):
        glyphs.set_axes(face, {"wght": 950})


def test_an_axis_asked_for_with_no_value_is_not_asked_for():
    """A variant leaves width unset rather than guessing, and None must not reach the face."""
    face = VariableFace(Axis(*WGHT))
    applied, ignored = glyphs.set_axes(face, {"wght": 700, "wdth": None})
    assert (applied, ignored) == ({"wght": 700}, [])


def test_a_face_with_no_axes_at_all_reports_everything_asked_for():
    class Static:
        def get_variation_info(self):
            raise RuntimeError("no fvar here")

    applied, ignored = glyphs.set_axes(Static(), {"wght": 700, "FILL": 1})
    assert (applied, ignored) == ({}, ["FILL", "wght"])
