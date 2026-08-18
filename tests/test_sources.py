"""Where a source font comes from: the transport, the archives, and each scheme.

Two layers get stubbed. `serving`, `absent` and `unreachable` stand in for the transfer, to
exercise `fetch`. `cache` stands in for `fetch`, to exercise everything above it.
"""

import io
import pathlib
import urllib.error
import urllib.parse
import zipfile

import pytest
from helpers import refuses

from badgeware_fonts import sources
from badgeware_fonts.af import AfError


def zipped(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture
def serving(monkeypatch):
    """A transfer that hands back bytes, as a log of the URLs it received."""
    urls = []

    def serve(url, target):
        urls.append(url)
        pathlib.Path(target).write_bytes(b"font")

    monkeypatch.setattr(sources.urllib.request, "urlretrieve", serve)
    return urls


@pytest.fixture
def absent(monkeypatch):
    """A server with nothing at any URL, as a log of the URLs it received."""
    urls = []

    def missing(url, _target):
        urls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(sources.urllib.request, "urlretrieve", missing)
    return urls


@pytest.fixture
def unreachable(monkeypatch):
    """A network that cannot be reached, leaving it unknown what is on the far end."""

    def refuse(_url, _target):
        raise OSError("connection refused")

    monkeypatch.setattr(sources.urllib.request, "urlretrieve", refuse)


@pytest.mark.usefixtures("serving")
def test_a_download_lands_under_a_readable_cache_path(tmp_path):
    path = sources.fetch("https://example.invalid/ofl/lexend/Lexend%5Bwght%5D.ttf", tmp_path)
    assert path.read_bytes() == b"font"
    assert path == tmp_path / "example.invalid" / "ofl" / "lexend" / "Lexend[wght].ttf"


@pytest.mark.usefixtures("serving")
def test_a_download_leaves_no_part_file_behind(tmp_path):
    """It lands as a .part and is renamed: a failed transfer leaves no truncated font."""
    path = sources.fetch("https://example.invalid/Font.ttf", tmp_path)
    assert not list(tmp_path.rglob("*.part"))
    assert path.exists()


def test_a_second_fetch_of_one_url_is_served_from_the_cache(serving, tmp_path):
    url = "https://example.invalid/Font.ttf"
    first = sources.fetch(url, tmp_path)
    assert sources.fetch(url, tmp_path) == first
    assert serving == [url]


def test_a_refreshed_fetch_downloads_again_with_the_file_already_in_hand(serving, tmp_path):
    url = "https://example.invalid/latest"
    sources.fetch(url, tmp_path)
    sources.fetch(url, tmp_path, refresh=True)
    assert serving == [url, url]


def test_a_probe_that_finds_nothing_records_the_miss(absent, tmp_path):
    """A recorded miss is what lets a warm cache build with no network."""
    url = "https://raw.githubusercontent.com/google/fonts/main/ofl/nosuchfamily/METADATA.pb"
    assert sources.fetch(url, tmp_path, optional=True) is None
    assert [path.name for path in tmp_path.rglob("METADATA.pb*")] == ["METADATA.pb.absent"]
    assert absent == [url]


def test_a_recorded_miss_is_not_fetched_again(absent, tmp_path):
    url = "https://example.invalid/OFL.txt"
    assert sources.fetch(url, tmp_path, optional=True) is None
    assert sources.fetch(url, tmp_path, optional=True) is None
    assert absent == [url]


@pytest.mark.usefixtures("absent")
def test_a_404_on_a_url_the_build_needs_is_a_failure(tmp_path):
    """Only an optional probe may come back empty. A font the manifest names has to arrive."""
    with pytest.raises(sources.FetchError, match="404"):
        sources.fetch("https://example.invalid/Font.ttf", tmp_path)


@pytest.mark.usefixtures("absent")
def test_a_file_that_turns_up_later_clears_the_recorded_miss(tmp_path, monkeypatch):
    """A refreshed fetch that succeeds must not leave the cache holding both.

    A family that adds a licence upstream arrives here as exactly this.
    """
    url = "https://example.invalid/OFL.txt"
    assert sources.fetch(url, tmp_path, optional=True) is None

    def now_there(_url, target):
        pathlib.Path(target).write_bytes(b"the terms")

    monkeypatch.setattr(sources.urllib.request, "urlretrieve", now_there)
    found = sources.fetch(url, tmp_path, optional=True, refresh=True)
    assert found.read_bytes() == b"the terms"
    assert not list(tmp_path.rglob(f"*{sources.ABSENT}"))


@pytest.mark.usefixtures("unreachable")
def test_a_transfer_that_failed_is_not_the_same_as_a_file_that_is_absent(tmp_path):
    """Taken as absent, an unreachable network would ship a font with no licence beside it."""
    with pytest.raises(sources.FetchError, match="could not fetch"):
        sources.fetch("https://example.invalid/OFL.txt", tmp_path, optional=True)
    assert not list(tmp_path.rglob(f"*{sources.ABSENT}"))


@pytest.mark.usefixtures("unreachable")
def test_a_fetch_failure_is_an_af_error_too(tmp_path):
    """The CLI catches AfError and prints one line, whatever went wrong."""
    with pytest.raises(AfError, match="could not fetch"):
        sources.fetch("https://example.invalid/Font.ttf", tmp_path)


def test_an_http_error_that_is_not_a_404_is_a_fetch_failure(tmp_path, monkeypatch):
    """A broken server is not a missing file, so the probe raises rather than returning None."""

    def broken(url, _target):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)

    monkeypatch.setattr(sources.urllib.request, "urlretrieve", broken)
    with pytest.raises(sources.FetchError, match="could not fetch"):
        sources.fetch("https://example.invalid/OFL.txt", tmp_path, optional=True)


@pytest.mark.usefixtures("unreachable")
def test_a_failed_transfer_never_prunes_past_the_cache_root(tmp_path):
    """The root is a boundary: without one this walks out and takes the caller's directories."""
    outer = tmp_path / "my-project"
    cache = outer / "fontcache"
    cache.mkdir(parents=True)
    url = "https://raw.githubusercontent.com/google/fonts/main/ofl/nosuch/METADATA.pb"
    with pytest.raises(sources.FetchError, match="connection refused"):
        sources.fetch(url, cache, optional=True)
    assert cache.is_dir(), "the cache root was handed to us, not made by us"
    assert outer.is_dir()
    assert not any(cache.iterdir())


def test_pruning_stops_at_the_first_directory_holding_anything(tmp_path):
    kept = tmp_path / "a"
    (kept / "b" / "c").mkdir(parents=True)
    (kept / "keep.txt").write_text("x", encoding="utf-8")
    sources.prune(kept / "b" / "c", tmp_path)
    assert kept.is_dir() and (kept / "keep.txt").exists()
    assert not (kept / "b").exists()


def test_pruning_a_directory_outside_the_root_does_nothing(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    sources.prune(elsewhere, root)
    assert elsewhere.is_dir()


class Served(dict):
    """What the stubbed fetcher will serve, and a log of the URLs it received."""

    fetched = ()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A cache root, with every fetch served from `served` instead of the network."""
    served, fetched = Served(), []

    def fake_fetch(url, root=None, optional=False, refresh=False):
        fetched.append((url, refresh))
        if url not in served:
            if optional:
                return None
            raise sources.FetchError(f"could not fetch {url}: not served")
        target = sources.cache_path(url, root or tmp_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(served[url])
        return target

    monkeypatch.setattr(sources, "fetch", fake_fetch)
    served.fetched = fetched
    return served


def test_a_source_with_no_scheme_is_refused():
    with refuses("Lato"):
        sources.resolve("Lato")


def test_an_unknown_scheme_is_refused():
    with refuses("fontsquirrel"):
        sources.resolve("fontsquirrel:Lato")


def test_a_zip_with_no_member_named_is_refused(cache, tmp_path):
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"a/Font.ttf": b"font"})
    with pytest.raises(AfError):
        sources.resolve(f"url:{url}", root=tmp_path)


def test_a_member_matching_nothing_lists_the_fonts_in_the_zip(cache, tmp_path):
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"a/Bold.ttf": b"font", "a/readme.md": b"x"})
    with refuses("Bold.ttf"):
        sources.resolve(f"url:{url}", member="Missing.ttf", root=tmp_path)


def test_a_member_on_a_plain_font_is_refused(cache, tmp_path):
    url = "https://example.invalid/Font.ttf"
    cache[url] = b"not a zip"
    with pytest.raises(AfError):
        sources.resolve(f"url:{url}", member="a/b.ttf", root=tmp_path)


def test_a_member_matches_on_whole_path_components(cache, tmp_path):
    """`Bold.ttf` must not match `SemiBold.ttf`."""
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"f/DSEG7-Classic/DSEG7Classic-SemiBold.ttf": b"semi", "f/DSEG7-Classic/DSEG7Classic-Bold.ttf": b"bold"})
    found = sources.resolve(f"url:{url}", member="DSEG7Classic-Bold.ttf", root=tmp_path)
    assert found.path.read_bytes() == b"bold"


def test_a_member_matching_several_files_is_refused_rather_than_guessed(cache, tmp_path):
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"regular/Font.ttf": b"one", "bold/Font.ttf": b"two"})
    with refuses("regular/Font.ttf", "bold/Font.ttf"):
        sources.resolve(f"url:{url}", member="Font.ttf", root=tmp_path)


def test_two_members_of_one_name_extract_to_separate_copies(cache, tmp_path):
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"regular/Font.ttf": b"one", "bold/Font.ttf": b"two"})
    first = sources.resolve(f"url:{url}", member="regular/Font.ttf", root=tmp_path)
    second = sources.resolve(f"url:{url}", member="bold/Font.ttf", root=tmp_path)
    assert first.path.read_bytes() == b"one"
    assert second.path.read_bytes() == b"two"


def test_a_member_extracted_once_is_not_extracted_again(cache, tmp_path):
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"a/Font.ttf": b"font"})
    first = sources.resolve(f"url:{url}", member="a/Font.ttf", root=tmp_path)
    first.path.write_bytes(b"edited in place")
    second = sources.resolve(f"url:{url}", member="a/Font.ttf", root=tmp_path)
    assert second.path == first.path
    assert second.path.read_bytes() == b"edited in place"


def test_an_archive_that_is_not_a_zip_is_refused_when_it_is_opened(tmp_path):
    """`is_zipfile` reads the signature; this is what happens when the rest disagrees."""
    archive = tmp_path / "fonts.zip"
    archive.write_bytes(b"PK\x03\x04 and then nothing that parses")
    with pytest.raises(AfError):
        sources.unzip(archive, "a/Font.ttf")


def test_a_release_asset_builds_its_url_without_the_api(cache, tmp_path):
    """A pinned tag needs no API call, so a build spends none of the hourly sixty."""
    url = "https://github.com/keshikan/DSEG/releases/download/v0.46/fonts.zip"
    cache[url] = zipped({"fonts-DSEG_v046/DSEG7-Classic/DSEG7Classic-Bold.ttf": b"font", "fonts-DSEG_v046/DSEG-LICENSE.txt": b"the licence"})
    found = sources.resolve("github:keshikan/DSEG", release="v0.46", asset="fonts.zip", member="DSEG7-Classic/DSEG7Classic-Bold.ttf", licence="DSEG-LICENSE.txt", root=tmp_path)
    assert found.path.read_bytes() == b"font"
    assert found.provenance == "github keshikan/DSEG v0.46 fonts.zip"
    # The member matched on the end of its path, so the version-stamped directory the zip
    # unpacks into stays out of the manifest.
    assert found.path.name == "DSEG7Classic-Bold.ttf"
    assert [path.read_bytes() for path in found.licences] == [b"the licence"]


def test_a_repository_file_resolves_through_raw(cache, tmp_path):
    url = "https://raw.githubusercontent.com/googlefonts/lexend/main/Lexend%5Bwght%5D.ttf"
    cache[url] = b"font"
    found = sources.resolve("github:googlefonts/lexend", ref="main", path="Lexend[wght].ttf", root=tmp_path)
    assert found.path.read_bytes() == b"font"
    assert found.provenance == "github googlefonts/lexend main Lexend[wght].ttf"


def test_latest_resolves_the_tag_over_the_api(cache, tmp_path):
    api = "https://api.github.com/repos/keshikan/DSEG/releases/latest"
    cache[api] = b'{"tag_name": "v0.46"}'
    cache["https://github.com/keshikan/DSEG/releases/download/v0.46/f.ttf"] = b"font"
    found = sources.resolve("github:keshikan/DSEG", release="latest", asset="f.ttf", root=tmp_path)
    assert found.provenance == "github keshikan/DSEG v0.46 f.ttf"
    # Past the cache, or the first tag stands for every later build and "latest" means
    # latest as of whenever the cache was filled.
    assert (api, True) in cache.fetched
    assert (api, False) not in cache.fetched


def test_a_latest_release_the_api_does_not_describe_is_refused(cache, tmp_path):
    """Anything but a tag_name leaves the release unresolved, so there is no URL to build."""
    cache["https://api.github.com/repos/keshikan/DSEG/releases/latest"] = b'{"message": "Not Found"}'
    with refuses("keshikan/DSEG"):
        sources.resolve("github:keshikan/DSEG", release="latest", asset="f.ttf", root=tmp_path)


@pytest.mark.usefixtures("cache")
def test_a_release_without_an_asset_is_refused(tmp_path):
    with pytest.raises(AfError):
        sources.resolve("github:keshikan/DSEG", release="v0.46", root=tmp_path)


@pytest.mark.usefixtures("cache")
def test_a_repo_with_neither_asset_nor_path_is_refused(tmp_path):
    with pytest.raises(AfError):
        sources.resolve("github:keshikan/DSEG", root=tmp_path)


@pytest.mark.usefixtures("cache")
def test_mixing_a_release_and_a_repository_path_is_refused(tmp_path):
    with pytest.raises(AfError):
        sources.resolve("github:a/b", release="v1", asset="x.zip", path="y.ttf", root=tmp_path)


@pytest.mark.usefixtures("cache")
def test_a_repo_that_is_not_owner_slash_name_is_refused(tmp_path):
    with refuses("justaname"):
        sources.resolve("github:justaname", asset="x.zip", release="v1", root=tmp_path)


VARIABLE = """name: "Lexend"
fonts {
  style: "normal"
  weight: 400
  filename: "Lexend[wght].ttf"
}
axes {
  tag: "wght"
  min_value: 100.0
  max_value: 900.0
}
"""

STATIC = """name: "Lato"
fonts {
  style: "normal"
  weight: 400
  filename: "Lato-Regular.ttf"
}
fonts {
  style: "italic"
  weight: 700
  filename: "Lato-BoldItalic.ttf"
}
"""


def family(cache, slug, metadata, directory="ofl", files=(), licences=("OFL.txt",)):
    """A google/fonts family the stub will serve, under the directory its licence puts it in."""
    base = f"{sources.GOOGLE_RAW}{directory}/{slug}/"
    cache[base + "METADATA.pb"] = metadata.encode()
    for name in licences:
        cache[base + name] = f"the {name}".encode()
    for name in files:
        cache[base + urllib.parse.quote(name)] = b"font"
    return base


def test_a_metadata_file_parses_into_its_fonts_and_axes():
    fonts, axes = sources.parse_metadata(VARIABLE)
    assert fonts == [{"style": "normal", "weight": "400", "filename": "Lexend[wght].ttf"}]
    assert axes == [{"tag": "wght", "min_value": "100.0", "max_value": "900.0"}]


def test_a_variable_family_takes_the_weight_as_a_coordinate(cache, tmp_path):
    family(cache, "lexend", VARIABLE, files=["Lexend[wght].ttf"])
    found = sources.resolve("google:Lexend", weight=350, root=tmp_path)
    assert found.axes == {"wght": 350.0}
    assert found.provenance == "google/fonts ofl/lexend/Lexend[wght].ttf"
    assert [path.name for path in found.licences] == ["OFL.txt"]


def test_a_static_family_picks_the_file_for_the_weight_and_takes_no_coordinate(cache, tmp_path):
    """The weight chose the face, so there is no axis left to set."""
    family(cache, "lato", STATIC, files=["Lato-BoldItalic.ttf"])
    found = sources.resolve("google:Lato", weight=700, style="italic", root=tmp_path)
    assert found.axes == {}
    assert found.provenance == "google/fonts ofl/lato/Lato-BoldItalic.ttf"


def test_a_family_is_looked_for_under_each_licence_directory(cache, tmp_path):
    """Permanent Marker sits under apache and ships a LICENSE.txt, not an OFL.txt."""
    family(cache, "permanentmarker", STATIC, directory="apache", files=["Lato-Regular.ttf"], licences=["LICENSE.txt"])
    found = sources.resolve("google:Permanent Marker", root=tmp_path)
    assert found.provenance.startswith("google/fonts apache/permanentmarker/")
    assert [path.name for path in found.licences] == ["LICENSE.txt"]


def test_a_family_that_is_in_none_of_them_names_where_it_looked(cache, tmp_path):
    assert not cache
    with refuses("Invented Sans"):
        sources.resolve("google:Invented Sans", root=tmp_path)


def test_a_weight_outside_a_variable_range_is_refused_by_the_range(cache, tmp_path):
    family(cache, "lexend", VARIABLE)
    with refuses(950, 100, 900):
        sources.resolve("google:Lexend", weight=950, root=tmp_path)


def test_a_weight_a_static_family_has_no_file_for_lists_the_weights_it_has(cache, tmp_path):
    family(cache, "lato", STATIC)
    with refuses(900, 400):
        sources.resolve("google:Lato", weight=900, root=tmp_path)


def test_a_style_the_family_has_not_got_lists_the_styles_it_has(cache, tmp_path):
    family(cache, "lexend", VARIABLE)
    with refuses("italic", "normal"):
        sources.resolve("google:Lexend", style="italic", root=tmp_path)


def test_a_family_shipping_no_licence_still_resolves(cache, tmp_path):
    """The probe for one is optional, so a family that publishes none is not a build failure."""
    family(cache, "lexend", VARIABLE, files=["Lexend[wght].ttf"], licences=[])
    assert sources.resolve("google:Lexend", root=tmp_path).licences == []


def test_material_resolves_the_variable_font_for_a_style(cache, tmp_path):
    name = urllib.parse.quote(sources.MATERIAL_FILES["sharp"])
    cache[sources.MATERIAL_RAW + "variablefont/" + name] = b"font"
    cache[sources.MATERIAL_RAW + "LICENSE"] = b"apache"
    found = sources.resolve("material:sharp", root=tmp_path)
    assert found.provenance.startswith("google/material-design-icons variablefont/MaterialSymbolsSharp")
    assert [path.name for path in found.licences] == ["LICENSE"]


@pytest.mark.usefixtures("cache")
def test_a_material_style_that_is_not_one_of_the_three_is_refused(tmp_path):
    with refuses("squiggly", "outlined", "rounded", "sharp"):
        sources.resolve("material:squiggly", root=tmp_path)


def test_a_file_source_resolves_against_the_manifest_directory(tmp_path):
    beside = tmp_path / "src"
    beside.mkdir()
    (beside / "Roboto.ttf").write_bytes(b"font")
    found = sources.resolve("file:src/Roboto.ttf", where=tmp_path)
    assert found.path.read_bytes() == b"font"
    assert found.provenance == str(beside / "Roboto.ttf")


def test_a_file_source_that_is_not_there_is_refused_by_path(tmp_path):
    with refuses("Missing.ttf"):
        sources.resolve("file:src/Missing.ttf", where=tmp_path)


def test_a_licence_given_as_a_url_is_fetched(cache, tmp_path):
    """Phosphor keeps its licence in another repository, so the manifest gives the URL."""
    cache["https://example.invalid/Font.ttf"] = b"font"
    cache["https://example.invalid/LICENSE"] = b"the terms"
    found = sources.resolve("url:https://example.invalid/Font.ttf", licence="https://example.invalid/LICENSE", root=tmp_path)
    assert [path.read_bytes() for path in found.licences] == [b"the terms"]


def test_a_licence_beside_the_manifest_is_taken_from_there(tmp_path):
    (tmp_path / "Roboto.ttf").write_bytes(b"font")
    (tmp_path / "LICENCE.txt").write_text("the terms", encoding="utf-8")
    found = sources.resolve("file:Roboto.ttf", where=tmp_path, licence="LICENCE.txt")
    assert [path.read_text(encoding="utf-8") for path in found.licences] == ["the terms"]


def test_a_licence_absent_from_an_archive_falls_back_to_the_manifest_directory(cache, tmp_path):
    """The archive first, then the manifest directory. Absence in one is not a failure."""
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"a/Font.ttf": b"font"})
    (tmp_path / "LICENCE.txt").write_text("the terms", encoding="utf-8")
    found = sources.resolve(f"url:{url}", member="a/Font.ttf", licence="LICENCE.txt", where=tmp_path, root=tmp_path)
    assert [path.read_text(encoding="utf-8") for path in found.licences] == ["the terms"]


def test_a_licence_that_is_nowhere_beside_the_manifest_is_refused_by_path(tmp_path):
    (tmp_path / "Roboto.ttf").write_bytes(b"font")
    with refuses("LICENCE.txt"):
        sources.resolve("file:Roboto.ttf", where=tmp_path, licence="LICENCE.txt")


def test_a_licence_missing_from_an_archive_says_it_looked_in_both_places(cache, tmp_path):
    url = "https://example.invalid/fonts.zip"
    cache[url] = zipped({"a/Font.ttf": b"font"})
    with refuses("LICENCE.txt", "fonts.zip"):
        sources.resolve(f"url:{url}", member="a/Font.ttf", licence="LICENCE.txt", root=tmp_path)
