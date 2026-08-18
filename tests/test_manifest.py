"""The manifest: the variants an entry expands into, and the entries turned away."""

import pytest
from helpers import read_manifest, refuses

from badgeware_fonts import charsets, corpus, grid, sources
from badgeware_fonts.af import ManifestError


def load(text, tmp_path, corpora=()):
    """A manifest on disk, with any corpus files it names written beside it."""
    for name, body in corpora:
        (tmp_path / name).write_text(body, encoding="utf-8")
    return read_manifest(text, tmp_path)


TEXT = """
[[font]]
name = "lexend"
type = "text"
source = "google:Lexend"
"""


def test_a_plural_axis_suffixes_each_variant_and_a_singular_one_does_not(tmp_path):
    found = load(
        """
[[font]]
name = "lato"
type = "text"
source = "google:Lato"
weights = [400, 700]

[[font]]
name = "lexend"
type = "text"
source = "google:Lexend"
weight = 400
""",
        tmp_path,
    )
    assert [variant.id for variant in found.variants] == ["lato-400", "lato-700", "lexend"]


def test_the_variants_of_several_plural_axes_are_their_product(tmp_path):
    found = load(
        """
[[font]]
name = "lato"
type = "text"
source = "google:Lato"
weights = [400, 700]
styles = ["normal", "italic"]
""",
        tmp_path,
    )
    # The upright takes no style suffix, so the two sit beside each other.
    assert [variant.id for variant in found.variants] == ["lato-400", "lato-400-italic", "lato-700", "lato-700-italic"]


WIDE = """
[[font]]
name = "roboto"
type = "text"
source = "google:Roboto"
"""


def test_a_width_names_its_variant_after_the_wdth_percentage(tmp_path):
    found = load(WIDE + "widths = [75, 100, 200]\n", tmp_path)
    # 100 is the normal width and adds nothing, so roboto.af sits beside the others.
    assert [variant.id for variant in found.variants] == ["roboto-condensed", "roboto", "roboto-ultra-expanded"]
    assert [variant.axes()["wdth"] for variant in found.variants] == [75.0, 100.0, 200.0]


def test_a_width_with_no_keyword_is_named_by_its_number(tmp_path):
    found = load(WIDE + "widths = [90, 100]\n", tmp_path)
    assert [variant.id for variant in found.variants] == ["roboto-90", "roboto"]


def test_a_width_is_named_or_a_percentage(tmp_path):
    """The names are the readable form; a number between them interpolates on the axis."""
    found = load(WIDE + 'widths = ["condensed", "normal", 73]\n', tmp_path)
    assert [variant.width for variant in found.variants] == [75, 100, 73.0]
    assert [variant.id for variant in found.variants] == ["roboto-condensed", "roboto", "roboto-73"]


def test_a_width_name_and_its_number_mean_the_same_thing(tmp_path):
    named = load(WIDE + 'width = "ultra-expanded"\n', tmp_path).variants[0]
    numbered = load(WIDE + "width = 200\n", tmp_path).variants[0]
    assert named.width == numbered.width == 200
    assert named.axes()["wdth"] == numbered.axes()["wdth"] == 200.0


@pytest.mark.parametrize("given", ["skinny", 0, 400], ids=["not a keyword", "below the axis", "above the axis"])
def test_a_width_that_is_neither_a_name_nor_a_percentage_is_refused(given, tmp_path):
    value = f'"{given}"' if isinstance(given, str) else given
    with pytest.raises(ManifestError):
        load(WIDE + f"width = {value}\n", tmp_path)


def test_an_entry_with_no_width_asks_the_face_for_none(tmp_path):
    """A static face has no wdth axis, and a variable one keeps its default."""
    found = load(TEXT, tmp_path)
    assert found.variants[0].width is None
    assert "wdth" not in found.variants[0].axes()


def test_the_cap_decides_the_grid_a_variant_is_built_to(tmp_path):
    found = load(
        """
[[font]]
name = "digits"
type = "text"
source = "google:Lexend"
caps = [81, 648]
chars = "0123456789"
""",
        tmp_path,
    )
    narrow, wide = found.variants
    assert (narrow.id, narrow.wide, narrow.units_per_em) == ("digits-81", False, None)
    assert (wide.id, wide.wide, wide.units_per_em) == ("digits-648", True, 1024)


def test_a_per_type_default_reaches_only_that_type(tmp_path):
    found = load(
        """
[defaults]
cap = 81

[defaults.text]
quality = 20

[defaults.icons]
size = 90
"""
        + TEXT
        + """
[[font]]
name = "icons"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a"]
""",
        tmp_path,
    )
    text, icons = found.by_id["lexend"], found.by_id["icons"]
    assert text.quality() == 20
    # The icon entry keeps the default quality, and takes the shared cap.
    assert icons.quality() == grid.DEFAULT_QUALITY
    assert icons.size() == 90
    assert (text.cap, icons.cap) == (81, 81)


def test_defaults_apply_where_an_entry_says_nothing(tmp_path):
    found = load(
        """
[defaults]
cap = 81
quality = 20
""" + TEXT,
        tmp_path,
    )
    variant = found.variants[0]
    assert variant.cap == 81
    assert variant.quality() == 20


def test_an_entry_plural_replaces_a_defaulted_singular(tmp_path):
    """A default cap and an entry's caps must not arrive together as both forms."""
    found = load(
        """
[defaults]
cap = 81

[[font]]
name = "digits"
type = "text"
source = "google:Lexend"
caps = [81, 648]
""",
        tmp_path,
    )
    assert [variant.cap for variant in found.variants] == [81, 648]


def test_a_quality_is_the_pixel_height_the_outlines_stay_crisp_to(tmp_path):
    """Higher is finer, and one quality means the same crispness at any cap.

    The tolerance a point may move scales with the cap, so a font packed to a large grid
    needs no override to look like a small one.
    """
    found = load(TEXT + "caps = [81, 648]\nquality = 100\n", tmp_path)
    small, large = found.variants
    assert grid.tolerance_for(small.quality(), small.extent()) == pytest.approx(0.405)
    assert grid.tolerance_for(large.quality(), large.extent()) == pytest.approx(3.24)
    # Eight times the cap, eight times the tolerance: the same outline either way.
    assert (grid.tolerance_for(large.quality(), large.extent()) / grid.tolerance_for(small.quality(), small.extent())) == pytest.approx(8)


def test_a_higher_quality_is_a_finer_tolerance(tmp_path):
    """The setting reads as a size, so the number goes up as the outlines get finer."""
    coarse = load(TEXT + "quality = 20\n", tmp_path).variants[0]
    fine = load(TEXT + "quality = 200\n", tmp_path).variants[0]
    assert grid.tolerance_for(fine.quality(), fine.extent()) < grid.tolerance_for(coarse.quality(), coarse.extent())


def test_a_named_quality_stands_for_a_pixel_height(tmp_path):
    for name, value in grid.QUALITY_NAMES.items():
        found = load(TEXT + f'quality = "{name}"\n', tmp_path)
        assert found.variants[0].quality() == value, name


def test_an_icon_quality_is_measured_against_its_box(tmp_path):
    found = load(
        """
[[font]]
name = "icons"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a"]
cap = 81
quality = 100
""",
        tmp_path,
    )
    variant = found.variants[0]
    assert variant.extent() == variant.size() == 100
    assert grid.tolerance_for(variant.quality(), variant.extent()) == pytest.approx(0.5)


@pytest.mark.parametrize("given", ["crunchy", 0, 99999], ids=["not a named level", "below the range", "above the range"])
def test_a_quality_that_is_not_a_pixel_height_is_refused(given, tmp_path):
    value = f'"{given}"' if isinstance(given, str) else given
    with pytest.raises(ManifestError):
        load(TEXT + f"quality = {value}\n", tmp_path)


def test_two_variants_writing_to_one_file_are_refused(tmp_path):
    with refuses("lexend", error=ManifestError):
        load(
            """
[[font]]
name = "lexend"
type = "text"
source = "google:Lexend"

[[font]]
name = "other"
type = "text"
source = "google:Lato"
output = "lexend"
""",
            tmp_path,
        )


def test_a_charset_unions_names_literals_and_ranges(tmp_path):
    found = load(TEXT + 'charset = "digits"\nchars = "H:"\nranges = ["U+00B0"]\n', tmp_path)
    assert found.variants[0].codepoints == sorted([*range(0x30, 0x3A), ord(":"), ord("H"), 0xB0])


def test_a_manifest_defines_charsets_beside_the_builtins(tmp_path):
    found = load(
        """
[charsets.clock]
chars = "H 0123456789:"
""" + TEXT + 'charset = "clock"\n',
        tmp_path,
    )
    assert len(found.variants[0].codepoints) == 13


def test_an_unknown_charset_lists_what_there_is(tmp_path):
    with refuses("lantin", "latin", error=ManifestError):
        load(TEXT + 'charset = "lantin"\n', tmp_path)


def test_a_codepoint_is_read_in_any_of_its_spellings():
    assert charsets.parse_codepoint("U+00B0", "x") == 0xB0
    assert charsets.parse_codepoint("0xb0", "x") == 0xB0
    assert charsets.parse_codepoint("b0", "x") == 0xB0
    assert list(charsets.parse_range("U+0020-U+0022", "x")) == [0x20, 0x21, 0x22]
    with pytest.raises(ManifestError):
        charsets.parse_range("U+0030-U+0020", "x")


def test_the_default_charset_is_latin(tmp_path):
    found = load(TEXT, tmp_path)
    assert set(found.variants[0].codepoints) == charsets.BUILTIN["latin"]


ICONS = """
[[font]]
name = "icons"
type = "icons"
source = "material:outlined"
corpus = "glyphs.txt"
"""


def test_a_corpus_line_takes_a_name_a_codepoint_and_an_optional_remap():
    read = corpus.parse(["# a comment", "", "sunny e81a", "rainy f176 i    # trailing comment"], "x")
    assert [(one.name, one.codepoint, one.printable) for one in read] == [("sunny", 0xE81A, None), ("rainy", 0xF176, ord("i"))]


@pytest.mark.parametrize("line", ["sunny\n", "sunny nothex\n", "sunny e81a ab\n"], ids=["one field", "a codepoint that is not hex", "a two-character remap"])
def test_a_malformed_corpus_line_is_refused(line):
    with pytest.raises(ManifestError):
        corpus.parse(line.splitlines(), "x")


def test_the_codepoints_mode_decides_where_a_glyph_packs(tmp_path):
    body = "sunny e81a s\nrainy f176\n"
    remapped = load(ICONS + 'codepoints = "remap"\n', tmp_path, [("glyphs.txt", body)])
    preserved = load(ICONS + 'codepoints = "preserve"\n', tmp_path, [("glyphs.txt", body)])
    mode = "remap"
    assert [one.target(mode) for one in remapped.variants[0].glyphs] == [ord("s"), 0xF176]
    mode = "preserve"
    assert [one.target(mode) for one in preserved.variants[0].glyphs] == [0xE81A, 0xF176]


def test_printable_mode_needs_a_third_field_on_every_line(tmp_path):
    with refuses("rainy", error=ManifestError):
        load(ICONS + 'codepoints = "printable"\n', tmp_path, [("glyphs.txt", "sunny e81a s\nrainy f176\n")])


def test_a_glyph_over_a_u16_needs_remapping(tmp_path):
    with pytest.raises(ManifestError):
        load(ICONS + 'codepoints = "preserve"\n', tmp_path, [("glyphs.txt", "check f0000\n")])


def test_two_glyphs_packing_at_one_codepoint_are_refused(tmp_path):
    with refuses("sunny", "snowy", error=ManifestError):
        load(ICONS, tmp_path, [("glyphs.txt", "sunny e81a s\nsnowy e2cd s\n")])


def test_an_icon_entry_takes_its_codepoints_from_a_charset(tmp_path):
    """A face of icons goes in whole, where a corpus picks a few out of thousands."""
    found = load(
        """
[[font]]
name = "emoji"
type = "icons"
source = "google:Noto Emoji"
ranges = ["U+2600-U+2604"]
""",
        tmp_path,
    )
    variant = found.variants[0]
    assert [one.codepoint for one in variant.glyphs] == list(range(0x2600, 0x2605))
    # No names and no remaps in a charset, so the glyphs keep their codepoints.
    assert variant.entry.codepoints == "preserve"
    assert [one.name for one in variant.glyphs][0] == "U+2600"


def test_an_icon_entry_giving_both_a_corpus_and_a_charset_is_refused(tmp_path):
    with pytest.raises(ManifestError):
        load(ICONS + 'ranges = ["U+2600"]\n', tmp_path, [("glyphs.txt", "sunny e81a\n")])


def test_remapping_without_a_corpus_to_read_the_remaps_from_is_refused(tmp_path):
    with pytest.raises(ManifestError):
        load(
            """
[[font]]
name = "emoji"
type = "icons"
source = "google:Noto Emoji"
ranges = ["U+2600"]
codepoints = "remap"
""",
            tmp_path,
        )


def test_an_icon_box_tracks_the_cap_unless_it_is_given(tmp_path):
    found = load(ICONS, tmp_path, [("glyphs.txt", "sunny e81a\n")])
    assert found.variants[0].size() == 100
    found = load(ICONS + "cap = 648\n", tmp_path, [("glyphs.txt", "sunny e81a\n")])
    assert found.variants[0].size() == 800


PARTS = """
[[font]]
name = "text"
type = "text"
source = "google:Roboto"
weights = [400, 700]
chars = "abc"

[[font]]
name = "icons"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a"]
codepoints = "preserve"
"""


def test_a_merge_at_a_weight_no_part_has_is_refused(tmp_path):
    with refuses("text-400", "text-700", error=ManifestError):
        load(
            PARTS + """
[[font]]
name = "both"
type = "merge"
parts = ["text", "icons"]
weights = [500]
""",
            tmp_path,
        )


def test_a_single_variant_part_goes_into_every_variant_of_the_merge(tmp_path):
    found = load(
        PARTS + """
[[font]]
name = "both"
type = "merge"
parts = ["text", "icons"]
weights = [400, 700]
""",
        tmp_path,
    )
    merged = [variant for variant in found.variants if variant.type == "merge"]
    assert [variant.id for variant in merged] == ["both-400", "both-700"]
    assert [part.id for part in merged[0].parts] == ["text-400", "icons"]
    assert [part.id for part in merged[1].parts] == ["text-700", "icons"]


def test_a_merge_that_pins_no_weight_is_refused(tmp_path):
    """The default 400 must not quietly take one weight of a family built at 400 and 700."""
    with refuses("text-400", "text-700", error=ManifestError):
        load(
            PARTS + """
[[font]]
name = "both"
type = "merge"
parts = ["text", "icons"]
""",
            tmp_path,
        )


def test_parts_built_to_different_grids_are_refused(tmp_path):
    with pytest.raises(ManifestError):
        load(
            """
[[font]]
name = "narrow"
type = "text"
source = "google:Roboto"
cap = 81
chars = "abc"

[[font]]
name = "wide"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a"]
codepoints = "preserve"
cap = 648

[[font]]
name = "both"
type = "merge"
parts = ["narrow", "wide"]
""",
            tmp_path,
        )


def test_a_merge_of_one_part_is_refused(tmp_path):
    with pytest.raises(ManifestError):
        load(
            PARTS + """
[[font]]
name = "both"
type = "merge"
parts = ["text"]
""",
            tmp_path,
        )


def test_a_merge_naming_an_entry_that_is_not_there_is_refused(tmp_path):
    with refuses("nope", error=ManifestError):
        load(
            PARTS + """
[[font]]
name = "both"
type = "merge"
parts = ["text", "nope"]
""",
            tmp_path,
        )


@pytest.mark.parametrize("axis", ["weights", "styles", "widths", "caps"])
@pytest.mark.parametrize("given", ["400", '"condensed"', "[]"])
def test_a_plural_axis_that_is_not_a_list_is_refused_by_name(axis, given, tmp_path):
    """A bare number or a bare string is the singular form under the plural key."""
    with pytest.raises(ManifestError):
        load(TEXT + f"{axis} = {given}\n", tmp_path)


def test_output_renames_the_stem_and_keeps_the_suffix(tmp_path):
    """The axes still name each variant, or a family would collapse onto one file."""
    found = load(TEXT + 'weights = [400, 700]\noutput = "body-text"\n', tmp_path)
    assert [variant.id for variant in found.variants] == ["body-text-400", "body-text-700"]
    # A single variant takes no suffix, so it is the output name exactly.
    found = load(TEXT + 'weight = 400\noutput = "body-text"\n', tmp_path)
    assert [variant.id for variant in found.variants] == ["body-text"]


def test_an_entry_stays_selectable_by_name_after_an_output_rename(tmp_path):
    found = load(TEXT + 'weights = [400, 700]\noutput = "body-text"\n', tmp_path)
    assert [variant.id for variant in found.select(["lexend"])] == ["body-text-400", "body-text-700"]
    assert [variant.id for variant in found.select(["body-text-400"])] == ["body-text-400"]


def test_a_corpus_file_that_is_not_there_is_refused_by_path(tmp_path):
    with pytest.raises(ManifestError):
        load(ICONS, tmp_path)


def test_a_corpus_holding_no_glyphs_is_refused(tmp_path):
    with pytest.raises(ManifestError):
        load(ICONS, tmp_path, corpora=[("glyphs.txt", "# nothing but a comment\n")])


def test_a_codepoints_mode_that_is_not_one_of_the_three_is_refused():
    with pytest.raises(ManifestError):
        corpus.check([], "sideways")


REFUSED = {
    "a manifest with no fonts in it": "[defaults]\ncap = 81\n",
    "a font that is not a table": "font = [1]\n",
    "a font with no name": '[[font]]\ntype = "text"\n',
    "a type that is not one of the three": '[[font]]\nname = "x"\nsource = "google:Lexend"\ntype = "squiggle"\n',
    "a font with no source": '[[font]]\nname = "x"\ntype = "text"\n',
    "two fonts of one name": TEXT + TEXT,
    "both forms of one axis": TEXT + "weight = 400\nweights = [700]\n",
    "a misspelled key": TEXT + "wieght = 400\n",
    "a weight over the range": TEXT + "weight = 1200\n",
    "a weight given as a boolean": TEXT + "weight = true\n",
    "a cap over the range": TEXT + "cap = 9000\n",
    "a style that is not one of the two": TEXT + 'styles = ["oblique"]\n',
    "axes that is not a table": TEXT + "axes = 1\n",
    "a size over the range": '[[font]]\nname = "i"\ntype = "icons"\nsource = "material:sharp"\nglyphs = ["sunny e81a"]\nsize = 9000\n',
    "a charset shadowing a built-in": '[charsets.latin]\nchars = "H"\n' + TEXT,
    "a charset that is not a table": "[charsets]\nmine = 1\n" + TEXT,
    "a charset with a misspelled key": '[charsets.mine]\ncharsett = "latin"\n' + TEXT,
    "a per-type default that is not a table": "[defaults]\ntext = 1\n" + TEXT,
    "both forms of one axis in [defaults]": "[defaults]\ncap = 81\ncaps = [81]\n" + TEXT,
    "both forms of one axis in [defaults.text]": "[defaults.text]\ncap = 81\ncaps = [81]\n" + TEXT,
    "a merge of one part": '[[font]]\nname = "m"\ntype = "merge"\nparts = ["a"]\n',
    "a merge with itself": PARTS + '[[font]]\nname = "m"\ntype = "merge"\nparts = ["m", "text"]\n',
    "an on_collision that is not one of the three": PARTS + '[[font]]\nname = "m"\ntype = "merge"\nparts = ["text", "icons"]\non_collision = "sideways"\n',
    "an icon entry with no codepoints to pack": '[[font]]\nname = "i"\ntype = "icons"\nsource = "material:sharp"\n',
    "a codepoints mode that is not one of the three": '[[font]]\nname = "i"\ntype = "icons"\nsource = "material:sharp"\nglyphs = ["sunny e81a"]\ncodepoints = "sideways"\n',
}


@pytest.mark.parametrize("text", REFUSED.values(), ids=REFUSED.keys())
def test_a_manifest_that_cannot_mean_what_it_says_is_refused(text, tmp_path, monkeypatch):
    """Refused while reading, before any source is fetched, so the fix is in fonts.toml.

    What each refusal reads like is prose, and prose changes. The test id names the rule under
    test; the assertions are the type, and that nothing went to the network to reach it.
    """
    monkeypatch.setattr(sources, "fetch", lambda *_args, **_kwargs: pytest.fail("fetched a source"))
    with pytest.raises(ManifestError):
        load(text, tmp_path)


def test_a_part_at_a_cap_the_merge_does_not_share_is_refused(tmp_path):
    """The parts sit on one grid. A merge cannot declare a cap of its own."""
    with pytest.raises(ManifestError):
        load(PARTS + '[[font]]\ntype = "merge"\nname = "m"\nparts = ["text", "icons"]\nweights = [400, 700]\ncap = 648\n', tmp_path)


def test_a_variant_repr_names_the_id_the_type_and_the_cap(tmp_path):
    """What a failing test prints: it has to name the variant."""
    variant = load(TEXT + "weights = [400, 700]\n", tmp_path).variants[0]
    assert repr(variant) == "<Variant lexend-400 text cap 81>"
