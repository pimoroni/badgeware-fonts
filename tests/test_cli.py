"""The command line, over fonts and manifests that need no network."""

import subprocess
import sys

import pytest
from helpers import glyph, read_manifest

from badgeware_fonts import af, cli

SQUARE = [[(0, 0), (60, 0), (60, -60), (0, -60)]]


@pytest.fixture
def font(tmp_path):
    """An .af on disk with a capital to measure and a descender to show below the baseline."""
    path = tmp_path / "lexend.af"
    path.write_bytes(af.pack([glyph(ord("H"), SQUARE, bbox_w=60, bbox_h=81, advance=70), glyph(ord("p"), SQUARE, bbox_y=-18, bbox_w=60, bbox_h=60, advance=65)]))
    return path


def test_no_command_prints_the_help_and_says_so_in_its_exit_code(capsys):
    assert cli.main([]) == 2
    printed = capsys.readouterr().out
    assert "build" in printed and "inspect" in printed and "list" in printed


def test_inspect_reports_a_font_and_succeeds(font, capsys):
    assert cli.main(["inspect", str(font)]) == 0
    printed = capsys.readouterr().out
    assert "2 glyphs" in printed
    assert "a capital stands 81" in printed


def test_inspect_details_the_characters_it_is_given(font, capsys):
    assert cli.main(["inspect", str(font), "--chars", "Hp"]) == 0
    rows = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  '")]
    assert [row.split()[0] for row in rows] == ["'H'", "'p'"]


def test_inspect_shows_every_glyph_when_asked(font, capsys):
    assert cli.main(["inspect", str(font), "--all"]) == 0
    rows = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  '")]
    assert len(rows) == 2


def test_inspect_names_a_character_the_font_has_not_got(font, capsys):
    assert cli.main(["inspect", str(font), "--chars", "Z"]) == 0
    assert "'Z'    not in this font" in capsys.readouterr().out


def test_inspect_reads_every_font_it_is_given(font, tmp_path, capsys):
    second = tmp_path / "other.af"
    second.write_bytes(font.read_bytes())
    assert cli.main(["inspect", str(font), str(second)]) == 0
    printed = capsys.readouterr().out
    assert str(font) in printed and str(second) in printed


def test_a_font_that_cannot_be_read_is_refused_by_name(tmp_path, capsys):
    missing = tmp_path / "gone.af"
    assert cli.main(["inspect", str(missing)]) == 1
    assert f"cannot read {missing}" in capsys.readouterr().err


def test_data_that_is_not_a_font_is_refused_by_name(tmp_path, capsys):
    path = tmp_path / "notafont.af"
    path.write_bytes(b"nowhere near a font")
    assert cli.main(["inspect", str(path)]) == 1
    assert "does not start with" in capsys.readouterr().err


def test_a_manifest_that_is_not_there_is_refused_by_path(tmp_path, capsys):
    assert cli.main(["--manifest", str(tmp_path / "nothing.toml"), "list"]) == 1
    assert "no manifest at" in capsys.readouterr().err


def test_a_manifest_that_is_not_toml_is_refused(tmp_path, capsys):
    path = tmp_path / "fonts.toml"
    path.write_text("[[font]\nname = ", encoding="utf-8")
    assert cli.main(["--manifest", str(path), "list"]) == 1
    assert "is not valid TOML" in capsys.readouterr().err


def test_list_names_each_variant_and_what_it_packs(tmp_path, capsys):
    read_manifest(
        """
[[font]]
name = "lato"
type = "text"
source = "google:Lato"
weights = [400, 700]
chars = "Hx"

[[font]]
name = "roboto"
type = "text"
source = "google:Roboto"
widths = ["condensed", "normal"]
cap = 648
chars = "H"

[[font]]
name = "icons"
type = "icons"
source = "material:sharp"
glyphs = ["sunny e81a s"]

[[font]]
name = "moshed"
type = "merge"
parts = ["lato", "icons"]
weights = [400, 700]
""",
        tmp_path,
    )
    assert cli.main(["--manifest", str(tmp_path / "fonts.toml"), "list"]) == 0
    printed = capsys.readouterr().out
    assert "lato-400.af" in printed
    assert "2 chars" in printed
    assert "1 glyphs in a 100 box, codepoints remap" in printed
    assert "merges lato-400 + icons" in printed
    # The width, and the grid a cap over the byte moves a variant onto.
    assert "roboto-condensed.af" in printed
    assert "wdth 75" in printed
    assert "wide" in printed and "narrow" in printed


def test_list_takes_the_names_it_is_given(tmp_path, capsys):
    read_manifest(
        """
[[font]]
name = "lato"
type = "text"
source = "google:Lato"
chars = "H"

[[font]]
name = "lexend"
type = "text"
source = "google:Lexend"
chars = "H"
""",
        tmp_path,
    )
    assert cli.main(["--manifest", str(tmp_path / "fonts.toml"), "list", "lexend"]) == 0
    printed = capsys.readouterr().out
    assert "lexend.af" in printed
    assert "lato.af" not in printed


def test_the_module_runs_as_a_script_and_carries_the_exit_code(tmp_path):
    """`python -m badgeware_fonts` is the entry point without the installed console script."""
    done = subprocess.run([sys.executable, "-m", "badgeware_fonts"], capture_output=True, text=True, cwd=tmp_path, check=False)
    assert done.returncode == 2
    assert "badgeware-fonts" in done.stdout
