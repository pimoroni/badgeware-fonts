"""The manifest this repository publishes, without building anything from it."""

from badgeware_fonts import cli, grid, manifest


def test_the_catalogue_parses_and_expands(repo_root):
    found = manifest.read(repo_root / "fonts.toml")
    ids = [variant.id for variant in found.variants]
    assert len(set(ids)) == len(ids)
    assert "lexend" in ids
    assert "lato-400" in ids and "lato-700" in ids


def test_every_entry_is_reachable_by_name(repo_root):
    found = manifest.read(repo_root / "fonts.toml")
    for entry in found.entries:
        assert found.select([entry.name])


def test_the_seven_segment_face_comes_out_of_its_release_zip(repo_root):
    """A pinned release, the font taken out of the archive, the licence out of it too."""
    found = manifest.read(repo_root / "fonts.toml")
    entry = found.by_id["dseg7-classic"].entry
    assert entry.source == "github:keshikan/DSEG"
    assert entry.release == "v0.46", "a pinned tag keeps the build reproducible"
    assert entry.member.endswith(".ttf")
    assert entry.licence == "DSEG-LICENSE.txt"
    # Seven segments and no letters, so the cap is measured from a digit.
    assert entry.cap_from == "0"
    assert found.by_id["dseg7-classic"].wide


def test_the_digits_pack_wide_and_the_body_text_narrow(repo_root):
    found = manifest.read(repo_root / "fonts.toml")
    assert found.by_id["lexend-digits"].wide
    assert found.by_id["lexend-digits"].units_per_em == 1024
    assert not found.by_id["lexend"].wide


def test_the_merged_font_leaves_its_icon_codepoints_alone(repo_root):
    """Remapped icons would collide with the text half of the merge."""
    found = manifest.read(repo_root / "fonts.toml")
    merged = found.by_id["roboto-symbols"]
    assert [part.id for part in merged.parts] == ["roboto-text", "material-symbols"]
    assert found.by_id["material-symbols"].entry.codepoints == "preserve"
    icons = {one.target("preserve") for one in found.by_id["material-symbols"].glyphs}
    text = set(found.by_id["roboto-text"].codepoints)
    assert not icons & text


def test_no_entry_asks_for_a_cap_that_drops_glyphs(repo_root):
    """The caps the build reported for the faces whose widest glyphs overhang the byte."""
    found = manifest.read(repo_root / "fonts.toml")
    assert found.by_id["poppins-400"].cap == 76
    assert found.by_id["permanent-marker"].cap == 77
    assert found.by_id["advent-pro-ultra-expanded-400-italic"].cap == 68
    # The normal width holds its glyphs at the reference cap.
    assert found.by_id["advent-pro-400"].cap == 81


def test_the_icon_sets_draw_from_the_same_letters(repo_root):
    """Material and Phosphor on one set of letters, so either drops into the other."""
    found = manifest.read(repo_root / "fonts.toml")
    letters = {}
    for name in ("badge-symbols", "phosphor-symbols", "phosphor-symbols-fill"):
        variant = found.by_id[name]
        letters[name] = sorted(one.target("remap") for one in variant.glyphs)
    assert letters["badge-symbols"] == letters["phosphor-symbols"]
    assert letters["badge-symbols"] == letters["phosphor-symbols-fill"]
    assert "".join(chr(point) for point in letters["badge-symbols"]) == "abcdefghlmnoprstuy"


def test_a_quality_for_body_text_does_not_reach_the_icons(repo_root):
    """Body text stops at 20px; an icon is drawn larger and keeps the default."""
    found = manifest.read(repo_root / "fonts.toml")
    assert found.by_id["lexend"].quality() == 20
    for name in ("badge-symbols", "phosphor-symbols", "material-symbols"):
        assert found.by_id[name].quality() == grid.DEFAULT_QUALITY, name
    # The fonts drawn the height of a screen declare it, in pixels.
    for name in ("lexend-digits", "dseg7-classic"):
        assert found.by_id[name].quality() == 100, name


def test_the_list_command_runs_over_the_catalogue(capsys, repo_root):
    assert cli.main(["--manifest", str(repo_root / "fonts.toml"), "list"]) == 0
    printed = capsys.readouterr().out
    assert "lexend-digits.af" in printed
    assert "merges roboto-text + material-symbols" in printed


def test_an_unknown_font_is_refused_by_name(capsys, repo_root):
    assert cli.main(["--manifest", str(repo_root / "fonts.toml"), "list", "lexnd"]) == 1
    assert "no font called lexnd" in capsys.readouterr().err
