"""Building real fonts from real faces.

These fetch from google/fonts and google/material-design-icons into build/sources. Where a
source cannot be reached they skip; any other failure is a real one.
"""

import json
import sys
import zipfile

import pytest
from helpers import (
    build_manifest,
    build_refused,
    cff_font,
    cli_build,
    read_manifest,
)

from badgeware_fonts import af, package
from badgeware_fonts import build as builder
from badgeware_fonts.af import AfError

MANIFEST = """
[[font]]
name = "lexend"
type = "text"
source = "google:Lexend"
weight = 400
chars = "Hpx 0123456789"

[[font]]
name = "digits"
type = "text"
source = "google:Lexend"
weight = 400
cap = 648
chars = "H0123456789:"

[[font]]
name = "icons"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a s", "rainy f176 i"]
axes = { FILL = 1 }

[[font]]
name = "preserved"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a s"]
codepoints = "preserve"

[[font]]
name = "moshed"
type = "merge"
parts = ["lexend", "preserved"]

[[font]]
name = "family"
type = "text"
source = "google:Lexend"
weights = [400, 700]
chars = "Hx"
"""

ONE_FONT = """
[[font]]
name = "tiny"
type = "text"
source = "google:Lexend"
weight = 400
chars = "H"
"""


@pytest.fixture(scope="module")
def built(tmp_path_factory, repo_root):
    return build_manifest(MANIFEST, tmp_path_factory.mktemp("manifest"), repo_root / "build/sources")


def by_codepoint(one):
    return {glyph.codepoint: glyph for glyph in one.glyphs}


def test_a_capital_stands_the_cap_the_entry_asked_for(built):
    """What every font size on a badge is in terms of."""
    assert by_codepoint(built["lexend"])[ord("H")].bbox_h == 81
    assert by_codepoint(built["digits"])[ord("H")].bbox_h == 648


def test_a_cap_over_a_signed_byte_packs_wide(built):
    narrow, wide = built["lexend"], built["digits"]
    assert (narrow.variant.wide, narrow.variant.units_per_em) == (False, None)
    assert (wide.variant.wide, wide.variant.units_per_em) == (True, 1024)
    assert af.unpack(wide.blob)["units_per_em"] == 1024
    assert not af.unpack(narrow.blob)["wide"]


def test_a_text_glyph_keeps_the_metrics_that_space_the_words(built):
    glyphs = by_codepoint(built["lexend"])
    blank, cap, descender = glyphs[ord(" ")], glyphs[ord("H")], glyphs[ord("p")]
    # A blank glyph spaces without drawing.
    assert blank.contours == [] and blank.advance > 0
    # An advance a little wider than the ink it sits in, and ink above the baseline is
    # negative, being y-down from it.
    assert cap.advance > cap.bbox_w
    assert min(y for contour in cap.contours for _x, y in contour) == -81
    # Only a descender takes bbox_y below the baseline.
    assert cap.bbox_y == 0
    assert descender.bbox_y < 0


def test_an_icon_fills_its_box_and_carries_a_made_up_advance(built):
    box = built["icons"].variant.size()
    for glyph in built["icons"].glyphs:
        assert glyph.advance == box
        assert max(glyph.bbox_w, glyph.bbox_h) == box


def test_an_icon_packs_where_the_codepoints_mode_says(built):
    assert sorted(by_codepoint(built["icons"])) == [ord("i"), ord("s")]
    assert sorted(by_codepoint(built["preserved"])) == [0xE81A]


def test_every_font_reads_back_the_way_it_was_written(built):
    for one in built.values():
        font = af.unpack(one.blob, one.variant.filename)
        em = font["units_per_em"] if font["wide"] else None
        assert af.pack(af.to_glyphs(font), units_per_em=em) == one.blob


def test_no_font_here_carries_a_fault(built):
    """A contour over the renderer's buffer, or an advance under the ink beside it."""
    assert {one.variant.id: one.faults for one in built.values() if one.faults} == {}


OVERHANGING = """
[[font]]
name = "wide-italic"
type = "text"
source = "google:Advent Pro"
style = "italic"
width = "ultra-expanded"
cap = 81
charset = "latin"
"""


@pytest.fixture(scope="module")
def overhanging(tmp_path_factory, repo_root):
    """An ultra-expanded italic at the reference cap, whose widest glyphs run past the byte."""
    return build_manifest(OVERHANGING, tmp_path_factory.mktemp("overhang"), repo_root / "build/sources")["wide-italic"]


def test_a_glyph_the_format_cannot_hold_is_left_out_of_the_font(overhanging):
    """A clamped glyph draws wrong wherever it appears, so it is dropped instead."""
    assert ord("W") in overhanging.dropped
    assert ord("W") not in {glyph.codepoint for glyph in overhanging.glyphs}
    assert af.out_of_range(overhanging.glyphs) == []


def test_the_report_names_what_it_dropped_and_the_cap_that_would_hold_it(overhanging):
    """The cap to put in the manifest, which is where Advent Pro's 68 comes from."""
    assert 1 <= overhanging.fits_at < overhanging.variant.cap
    line = next(line for line in builder.summary(overhanging) if "left out" in line)
    assert "W" in line
    assert f"a cap of {overhanging.fits_at} would hold them" in line


def test_a_dropped_glyph_is_named_in_the_metadata(overhanging):
    assert f"U+{ord('W'):04X}" in overhanging.metadata()["dropped"]


def test_the_cap_that_fits_is_a_straight_ratio_of_the_reach(built):
    """A glyph's reach scales with the cap, so halving the cap halves the overhang."""
    variant = built["lexend"].variant
    stretched = af.Glyph(ord("W"))
    stretched.contours = [[(0, 0), (254, 0), (254, -81)]]
    assert builder.cap_that_fits([stretched], variant) == 40
    # Nothing over the limit, so the cap it fits at is at or above the declared one.
    assert builder.cap_that_fits(built["lexend"].glyphs, variant) >= variant.cap


def test_a_font_of_blank_glyphs_has_no_cap_that_would_hold_it(built):
    assert builder.cap_that_fits([af.Glyph(ord(" "))], built["lexend"].variant) is None


def test_a_merge_holds_both_parts_at_one_grid(built):
    merged, text, icons = built["moshed"], built["lexend"], built["preserved"]
    assert sorted(by_codepoint(merged)) == sorted(set(by_codepoint(text)) | set(by_codepoint(icons)))
    assert af.unpack(merged.blob)["wide"] is False
    # The glyphs come across as they were built, not rebuilt.
    assert by_codepoint(merged)[0xE81A].contours == by_codepoint(icons)[0xE81A].contours
    assert by_codepoint(merged)[ord("H")].contours == by_codepoint(text)[ord("H")].contours


def colliding(mode=None):
    """The merge above, with an icon remapped onto a letter that the text half packs too."""
    text = MANIFEST.replace('parts = ["lexend", "preserved"]', 'parts = ["lexend", "icons"]').replace('chars = "Hpx 0123456789"', 'chars = "Hs"')
    return text if mode is None else text.replace('parts = ["lexend", "icons"]', f'parts = ["lexend", "icons"]\non_collision = "{mode}"')


def test_a_merge_of_parts_wanting_one_codepoint_is_refused(tmp_path, repo_root):
    """A text font holding "s" against an icon remapped to "s"."""
    build_refused(colliding(), tmp_path, repo_root / "build/sources", "both want 0073", names=["moshed"])


@pytest.mark.parametrize("mode, wins", [("first", "lexend"), ("last", "icons")])
def test_on_collision_says_which_part_keeps_the_codepoint(mode, wins, tmp_path, repo_root):
    made = build_manifest(colliding(mode), tmp_path, repo_root / "build/sources")
    merged, kept = made["moshed"], made[wins]
    assert by_codepoint(merged)[ord("s")].contours == by_codepoint(kept)[ord("s")].contours


def test_replacing_a_codepoint_is_worth_a_warning(tmp_path, repo_root):
    """`first` is silent because nothing changed; `last` overwrote what a part had built."""
    made = build_manifest(colliding("last"), tmp_path, repo_root / "build/sources")
    assert made["moshed"].warnings == ["'s' from icons replaces lexend"]
    assert build_manifest(colliding("first"), tmp_path, repo_root / "build/sources")["moshed"].warnings == []


def test_a_merge_counts_the_codepoints_all_its_parts_asked_for(built):
    merged, text, icons = built["moshed"], built["lexend"], built["preserved"]
    assert merged.requested == text.requested + icons.requested


def test_a_merge_takes_the_coarsest_quality_and_no_tolerance(built):
    """A tolerance is in units of one extent, and a merge's parts have one each."""
    merged = built["moshed"]
    assert merged.quality == min(built["lexend"].quality, built["preserved"].quality)
    assert merged.tolerance is None
    assert merged.metadata()["tolerance"] is None


def test_a_codepoint_the_face_has_not_got_is_counted_not_packed(built):
    """Lexend has no U+017F, so the count requested and the glyphs built differ by one."""
    one = built["lexend"]
    assert one.requested == len(one.variant.codepoints)
    assert len(one.glyphs) == one.requested - len(one.missing)


def test_a_charset_of_icons_reports_coverage_not_a_line_per_gap(tmp_path, repo_root):
    """A corpus names each glyph, so an absent one gets a line. A charset expects gaps."""
    one = build_manifest(
        """
[[font]]
name = "emoji"
type = "icons"
source = "google:Noto Emoji"
ranges = ["U+2600-U+26FF"]
""",
        tmp_path,
        repo_root / "build/sources",
    )["emoji"]
    assert one.missing and not one.warnings
    assert any("codepoints are not in the face" in line for line in builder.summary(one))


def test_a_named_glyph_the_face_has_not_got_is_worth_a_line(tmp_path, repo_root):
    """A corpus names every glyph, so a name that resolves to nothing is a mistake in it."""
    one = build_manifest(
        """
[[font]]
name = "icons"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a s", "invented ffff x"]
""",
        tmp_path,
        repo_root / "build/sources",
    )["icons"]
    assert one.warnings == ["invented is not in this face, skipped"]


AXES = """
[[font]]
name = "typo"
type = "text"
source = "google:Lexend"
weight = 400
chars = "H"
axes = { FIL = 1 }

[[font]]
name = "narrowed"
type = "text"
source = "google:Lexend"
weight = 400
width = "condensed"
chars = "H"

[[font]]
name = "static"
type = "text"
source = "google:Lato"
weight = 700
style = "italic"
chars = "H"
"""


@pytest.fixture(scope="module")
def axis_builds(tmp_path_factory, repo_root):
    return build_manifest(AXES, tmp_path_factory.mktemp("axes"), repo_root / "build/sources")


def test_an_axis_the_face_has_not_got_is_reported(axis_builds):
    """A misspelled axis otherwise builds the wrong font and reports success."""
    assert axis_builds["typo"].warnings == ["this face has no FIL axis, so it was not set"]


def test_a_width_the_face_cannot_take_is_reported(axis_builds):
    """Nothing selects a face by width, so a missing wdth axis means it was ignored."""
    assert axis_builds["narrowed"].warnings == ["this face has no wdth axis, so it was not set"]


def test_a_face_chosen_by_file_needs_no_axis_warning(axis_builds):
    """Lato has neither a wght nor an ital axis; the weight and style chose the file."""
    assert axis_builds["static"].warnings == []
    assert axis_builds["static"].applied_axes == {}


def test_an_axis_value_the_face_cannot_reach_is_refused(tmp_path, repo_root):
    text = AXES.replace("axes = { FIL = 1 }", "axes = { wght = 40 }")
    build_refused(text, tmp_path, repo_root / "build/sources", "outside this face's", names=["typo"])


def test_a_cap_from_the_face_has_not_got_names_the_setting(tmp_path, repo_root):
    text = ONE_FONT + 'cap_from = "☃"\n'
    build_refused(text, tmp_path, repo_root / "build/sources", "Set cap_from to a character it does have")


def test_a_cap_from_with_no_outline_is_refused(tmp_path, repo_root):
    """A space has a width and no ink, so there is no height to scale against."""
    text = ONE_FONT + 'cap_from = " "\n'
    build_refused(text, tmp_path, repo_root / "build/sources", "no outline to measure a cap height from")


def test_a_font_that_will_not_draw_is_named_and_nothing_is_written(tmp_path, repo_root, monkeypatch, capsys):
    """One faulty font holds back the whole build: a release is all of the fonts or none."""

    def overflowing(_glyphs, text=True):  # noqa: ARG001
        return ["'H' has a contour of 600 points"]

    monkeypatch.setattr(builder.glyphs, "faults", overflowing)
    code, out = cli_build(ONE_FONT, tmp_path, repo_root / "build/sources")
    printed = capsys.readouterr().out
    assert code == 1
    assert "1 of 1 fonts will not draw correctly, so none were written" in printed
    assert "tiny: 1 glyph" in printed
    assert not out.exists()


def test_a_font_with_no_faults_is_written_and_the_build_succeeds(tmp_path, repo_root):
    code, out = cli_build(ONE_FONT, tmp_path, repo_root / "build/sources")
    assert code == 0
    assert (out / "tiny.zip").exists()


def test_only_a_font_with_faults_is_held_back():
    class Stub:
        def __init__(self, faults):
            self.faults = faults

    good, bad = Stub([]), Stub(["a contour of 600 points"])
    assert builder.faulty([good, bad]) == [bad]
    assert builder.faulty([good]) == []


def test_faults_print_as_errors_and_the_rest_as_warnings(built):
    one = built["lexend"]
    stand_in = builder.Built(one.variant)
    stand_in.glyphs, stand_in.blob = one.glyphs, one.blob
    stand_in.faults = ["'j' advance 1 against 60 of ink"]
    stand_in.warnings = ["this face has no FIL axis, so it was not set"]
    lines = builder.summary(stand_in)
    assert any(line.strip() == "error: 'j' advance 1 against 60 of ink" for line in lines)
    assert any(line.strip() == "warning: this face has no FIL axis, so it was not set" for line in lines)


WEB = """
[[font]]
name = "webbed"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a s", "rainy f176 i"]
web = true
"""


def test_web_subsets_the_same_corpus_from_the_same_face(tmp_path, repo_root):
    """A config UI draws these symbols from the font, not from a second hand-kept list."""
    fonttools = pytest.importorskip("fontTools.ttLib")
    found = read_manifest(WEB, tmp_path)
    made = build_manifest(WEB, tmp_path, repo_root / "build/sources")["webbed"]
    out = tmp_path / "web" / "webbed.woff2"
    assert builder.write_web(made, out, repo_root / "build/sources", found) == out

    with fonttools.TTFont(out) as font:
        assert font.flavor == "woff2"
        packed = set(font.getBestCmap())
    # The corpus codepoints, not the remaps: a woff2 keeps the face's own cmap.
    assert {one.codepoint for one in made.variant.glyphs} <= packed


def test_web_on_a_text_entry_is_refused(built, tmp_path, repo_root):
    """There is no corpus to subset to, so the setting cannot mean anything."""
    with pytest.raises(AfError):
        builder.write_web(built["lexend"], tmp_path / "x.woff2", repo_root / "build/sources", None)


def test_the_family_zip_carries_the_woff2_beside_the_font(tmp_path, repo_root):
    pytest.importorskip("fontTools.ttLib")
    code, out = cli_build(WEB, tmp_path, repo_root / "build/sources")
    assert code == 0
    with zipfile.ZipFile(out / "webbed.zip") as bundle:
        assert sorted(bundle.namelist()) == ["licences/LICENSE", "meta.json", "webbed.af", "webbed.woff2"]


def test_a_family_zip_carries_the_font_its_metadata_and_its_licences(built, tmp_path):
    one = built["lexend"]
    target = package.family_zip([one], tmp_path)
    assert target.name == "lexend.zip"
    with zipfile.ZipFile(target) as bundle:
        names = bundle.namelist()
        meta = json.loads(bundle.read("meta.json"))
        assert bundle.read("lexend.af") == one.blob
    assert "licences/OFL.txt" in names
    assert meta["name"] == "lexend"
    font = meta["fonts"][0]
    assert (font["cap"], font["wide"], font["weight"]) == (81, False, 400)
    assert font["codepoints"] == [glyph.codepoint for glyph in one.glyphs]
    assert "google/fonts ofl/lexend/Lexend[wght].ttf" in font["sources"]


def test_quality_is_always_a_float_whether_named_or_numbered(built):
    for one in built.values():
        assert isinstance(one.metadata()["quality"], float), one.variant.id


def test_a_loose_build_writes_bare_fonts_and_no_zip(tmp_path, repo_root):
    code, out = cli_build(ONE_FONT, tmp_path, repo_root / "build/sources", "--loose")
    assert code == 0
    assert [path.name for path in out.iterdir()] == ["tiny.af"]


def test_a_listed_build_reports_every_font_and_writes_none(tmp_path, repo_root, capsys):
    code, out = cli_build(ONE_FONT, tmp_path, repo_root / "build/sources", "--list")
    assert code == 0
    assert "crisp to" in capsys.readouterr().out
    assert not out.exists()


def test_building_one_entry_by_name_leaves_the_bundle_alone(tmp_path, repo_root):
    """A partial build must not write a badgeware-fonts.zip missing most of the fonts."""
    code, out = cli_build(MANIFEST, tmp_path, repo_root / "build/sources", "family")
    assert code == 0
    assert [path.name for path in out.iterdir()] == ["family.zip"]


def test_a_manifest_that_builds_nothing_is_refused(tmp_path, repo_root):
    """An entry whose charset the face has nothing of leaves no font to write."""
    text = ONE_FONT.replace('chars = "H"', 'ranges = ["U+E000-U+E002"]')
    build_refused(text, tmp_path, repo_root / "build/sources", "no glyphs were built")


def test_a_merge_is_built_after_the_parts_it_takes(tmp_path):
    """Each variant once, so an icon set shared by several merges is built once."""
    found = read_manifest(MANIFEST, tmp_path)
    chosen = found.select(["moshed", "preserved", "lexend"])
    assert [variant.id for variant in builder.order(chosen, found)] == ["lexend", "preserved", "moshed"]


def test_a_font_builds_from_a_face_beside_the_manifest(tmp_path):
    """A `file:` source and a CFF face, so the whole pipeline runs with no network at all."""
    cff_font(tmp_path, "Cubic.otf")
    made = build_manifest('[[font]]\nname = "cubic"\ntype = "text"\nsource = "file:Cubic.otf"\nchars = "H"\n', tmp_path, None)["cubic"]
    assert made.provenance == [str(tmp_path / "Cubic.otf")]
    cap = made.glyphs[0]
    assert cap.codepoint == ord("H")
    assert cap.bbox_h == 81
    assert made.faults == [] and made.warnings == []


def test_a_glyph_simplification_erases_still_spaces_the_words(tmp_path, monkeypatch):
    """A text glyph keeps its advance with no ink, the way a space does."""
    cff_font(tmp_path, "Cubic.otf")
    monkeypatch.setattr(builder.glyphs, "clean_contours", lambda *_args: [])
    made = build_manifest('[[font]]\nname = "cubic"\ntype = "text"\nsource = "file:Cubic.otf"\nchars = "H"\ncap_from = "H"\n', tmp_path, None)["cubic"]
    cap = made.glyphs[0]
    assert cap.contours == []
    assert cap.advance > 0


def test_an_icon_simplification_erases_is_left_out(tmp_path, monkeypatch):
    """Nothing to draw and no words to space, so no codepoint is packed for it."""
    cff_font(tmp_path, "Cubic.otf")
    monkeypatch.setattr(builder.glyphs, "clean_contours", lambda *_args: [])
    found = read_manifest('[[font]]\nname = "cubic"\ntype = "icons"\nsource = "file:Cubic.otf"\nglyphs = ["cap 48 H"]\n', tmp_path)
    with pytest.raises(AfError):
        builder.build_all(found, found.variants)


def test_web_without_fonttools_is_skipped_and_not_fatal(tmp_path, repo_root, capsys, monkeypatch):
    """The woff2 is an extra for a config UI, and the .af does not depend on it."""
    monkeypatch.setitem(sys.modules, "fontTools", None)
    code, out = cli_build(WEB, tmp_path, repo_root / "build/sources")
    assert code == 0
    assert "uv sync --extra web" in capsys.readouterr().out
    with zipfile.ZipFile(out / "webbed.zip") as bundle:
        assert "webbed.af" in bundle.namelist()
        assert "webbed.woff2" not in bundle.namelist()


def test_an_icon_with_no_ink_is_left_out(tmp_path):
    """A blank has nothing to fit to the box, and an icon carries no words to space."""
    cff_font(tmp_path, "Cubic.otf")
    found = read_manifest('[[font]]\nname = "cubic"\ntype = "icons"\nsource = "file:Cubic.otf"\nglyphs = ["cap 48 H", "blank 20 s"]\n', tmp_path)
    made = builder.build_all(found, found.variants)[0]
    assert [glyph.codepoint for glyph in made.glyphs] == [ord("H")]
    assert made.warnings == ["blank is not in this face, skipped"]
