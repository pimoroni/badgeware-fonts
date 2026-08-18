"""The zips a build writes: a family together, every family in one bundle, licences intact."""

import json
import zipfile

from helpers import FakeBuilt, licence

from badgeware_fonts import package


def test_a_family_of_several_weights_zips_as_one(tmp_path):
    """What a release page needs: a family once, not once per weight."""
    ofl = licence(tmp_path, "OFL.txt", "the licence")
    family = [FakeBuilt("lato", "lato-400", b"four", [ofl], 400), FakeBuilt("lato", "lato-700", b"seven", [ofl], 700)]
    target = package.family_zip(family, tmp_path / "out")
    assert target.name == "lato.zip"
    with zipfile.ZipFile(target) as bundle:
        assert sorted(bundle.namelist()) == ["lato-400.af", "lato-700.af", "licences/OFL.txt", "meta.json"]
        meta = json.loads(bundle.read("meta.json"))
        assert bundle.read("lato-700.af") == b"seven"
    assert [font["weight"] for font in meta["fonts"]] == [400, 700]
    # One copy of the licence for the family, not one per weight.
    assert meta["fonts"][0]["licences"] == ["OFL.txt"]


def test_one_family_keeps_its_licence_out_of_a_subdirectory(tmp_path):
    one = FakeBuilt("lato", "lato", b"a", [licence(tmp_path, "OFL.txt", "the licence")])
    target = package.family_zip([one], tmp_path / "out")
    with zipfile.ZipFile(target) as bundle:
        assert "licences/OFL.txt" in bundle.namelist()


def test_builds_group_into_the_families_they_came_from():
    lato = [FakeBuilt("lato", "lato-400", b"", []), FakeBuilt("lato", "lato-700", b"", [])]
    lexend = [FakeBuilt("lexend", "lexend", b"", [])]
    grouped = package.families([*lato, *lexend])
    assert sorted(grouped) == ["lato", "lexend"]
    assert [one.variant.id for one in grouped["lato"]] == ["lato-400", "lato-700"]


def test_the_bundle_files_each_licence_under_the_entry_it_covers(tmp_path):
    """Google families ship differing OFL.txt files, and a flat licences/ would keep one."""
    builds = [FakeBuilt("lato", "lato", b"a", [licence(tmp_path, "OFL.txt", "lato terms")]), FakeBuilt("lexend", "lexend", b"b", [licence(tmp_path, "OFL.txt", "lexend terms")])]
    target = package.bundle_zip(builds, tmp_path / "bundle")
    with zipfile.ZipFile(target) as bundle:
        names = sorted(name for name in bundle.namelist() if name.startswith("licences/"))
        assert names == ["licences/lato/OFL.txt", "licences/lexend/OFL.txt"]
        assert bundle.read("licences/lato/OFL.txt") == b"lato terms"
        assert bundle.read("licences/lexend/OFL.txt") == b"lexend terms"


def test_the_bundle_carries_an_index_of_every_font(tmp_path):
    builds = [FakeBuilt("lato", "lato-400", b"a", []), FakeBuilt("lexend", "lexend", b"b", [])]
    target = package.bundle_zip(builds, tmp_path / "bundle")
    with zipfile.ZipFile(target) as bundle:
        assert sorted(bundle.namelist()) == ["index.json", "lato-400.af", "lexend.af"]
        index = json.loads(bundle.read("index.json"))
    assert [font["name"] for font in index["fonts"]] == ["lato-400", "lexend"]


def test_a_merge_numbers_two_licences_of_one_name_rather_than_dropping_one(tmp_path):
    """Nesting cannot separate a merge: both parts sit under the entry the path is named for."""
    merged = FakeBuilt("both", "both", b"a", [licence(tmp_path, "OFL.txt", "one family"), licence(tmp_path, "OFL.txt", "another family")])
    target = package.family_zip([merged], tmp_path / "out")
    with zipfile.ZipFile(target) as bundle:
        names = sorted(name for name in bundle.namelist() if name.startswith("licences/"))
        assert names == ["licences/OFL-2.txt", "licences/OFL.txt"]
        assert {bundle.read(name) for name in names} == {b"one family", b"another family"}


def test_one_licence_named_twice_is_filed_once(tmp_path):
    """The same bytes under the same name are the same licence, however many parts cite it."""
    ofl = licence(tmp_path, "OFL.txt", "the licence")
    merged = FakeBuilt("both", "both", b"a", [ofl, ofl])
    target = package.family_zip([merged], tmp_path / "out")
    with zipfile.ZipFile(target) as bundle:
        assert [name for name in bundle.namelist() if name.startswith("licences/")] == ["licences/OFL.txt"]


def test_a_licence_with_no_suffix_is_still_numbered(tmp_path):
    """Phosphor's licence is a bare LICENSE, so the numbering cannot assume an extension."""
    parts = [licence(tmp_path, "LICENSE", "one project"), licence(tmp_path, "LICENSE", "another project")]
    target = package.family_zip([FakeBuilt("both", "both", b"a", parts)], tmp_path / "out")
    with zipfile.ZipFile(target) as bundle:
        names = sorted(name for name in bundle.namelist() if name.startswith("licences/"))
    assert names == ["licences/LICENSE", "licences/LICENSE-2"]


def test_a_third_licence_of_one_name_takes_the_next_number(tmp_path):
    parts = [licence(tmp_path, "OFL.txt", f"family {index}") for index in range(3)]
    target = package.family_zip([FakeBuilt("all", "all", b"a", parts)], tmp_path / "out")
    with zipfile.ZipFile(target) as bundle:
        names = sorted(name for name in bundle.namelist() if name.startswith("licences/"))
    assert names == ["licences/OFL-2.txt", "licences/OFL-3.txt", "licences/OFL.txt"]


def test_a_loose_font_is_written_under_its_own_name(tmp_path):
    """What `--loose` writes, for a checkout that vendors one font."""
    target = package.write_loose(FakeBuilt("lato", "lato-400", b"the font", []), tmp_path / "out")
    assert target.name == "lato-400.af"
    assert target.read_bytes() == b"the font"


def test_extra_files_join_the_family_zip(tmp_path):
    """Where the woff2 an icon entry declares ends up."""
    woff = tmp_path / "web" / "badge-symbols.woff2"
    woff.parent.mkdir(parents=True)
    woff.write_bytes(b"a woff2")
    target = package.family_zip([FakeBuilt("badge-symbols", "badge-symbols", b"a", [])], tmp_path / "out", [woff])
    with zipfile.ZipFile(target) as bundle:
        assert bundle.read("badge-symbols.woff2") == b"a woff2"


def test_a_rebuild_writes_the_same_zip(tmp_path):
    """Sorted entries under a fixed timestamp, so a release can be checked against a rebuild."""
    one = FakeBuilt("lato", "lato-400", b"the font", [licence(tmp_path, "OFL.txt", "the licence")])
    first = package.family_zip([one], tmp_path / "a").read_bytes()
    second = package.family_zip([one], tmp_path / "b").read_bytes()
    assert first == second
