"""Where a source font comes from, and the licence that travels with it.

Five schemes:

    google:Lato               google/fonts, resolved through the family's METADATA.pb
    material:outlined         Material Symbols, the variable font with FILL and wght axes
    github:keshikan/DSEG      a release asset, or a file in the repository
    url:https://.../X.ttf     any URL
    file:src/Roboto.ttf       a path beside the manifest

A fetch that lands a zip takes `member` to pick the font out of it, and a `licence` naming
a file inside the same archive comes out of it too.

A build fetches into build/sources, ignored by git, and keeps what it fetched for the next
run, a 404 to an optional probe included. A download lands as a .part and is renamed into
place, leaving no truncated font for FreeType to read where a transfer was interrupted. Once the
cache holds a manifest's sources the whole build runs with no network.

Each fetch brings the licence with it. `package` puts those in the zip, where whoever ships
the artefact needs them.
"""

import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .af import AfError

CACHE = pathlib.Path("build/sources")
# Marks a URL the server returned 404 for, recording a miss in the cache as well as a hit.
ABSENT = ".absent"

GOOGLE_RAW = "https://raw.githubusercontent.com/google/fonts/main/"
# Where a family sits, by the licence it is under. Probed in this order.
GOOGLE_DIRS = ("ofl", "apache", "ufl")
GOOGLE_LICENCES = ("OFL.txt", "LICENSE.txt", "UFL.txt")

MATERIAL_RAW = "https://raw.githubusercontent.com/google/material-design-icons/master/"

GITHUB_RELEASE = "https://github.com/{repo}/releases/download/{release}/{asset}"
GITHUB_RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"
MATERIAL_FILES = {
    "outlined": "MaterialSymbolsOutlined[FILL,GRAD,opsz,wght].ttf",
    "rounded": "MaterialSymbolsRounded[FILL,GRAD,opsz,wght].ttf",
    "sharp": "MaterialSymbolsSharp[FILL,GRAD,opsz,wght].ttf",
}


class FetchError(AfError):
    """A URL that could not be read.

    A separate type, for a caller to tell a transport failure from a manifest that named the
    wrong thing. The build tests skip on this and fail on any other AfError, which
    stops an unreachable network passing for the failure under test.
    """


class Resolved:
    """A source font on disk, with what it took to get there.

    `axes` holds the variation coordinates the source itself demands: a variable family
    carries a requested weight here. An entry's axes are merged over these.
    """

    def __init__(self, path, axes=None, licences=(), provenance="", archive=None):
        self.path = pathlib.Path(path)
        self.axes = dict(axes or {})
        self.licences = list(licences)
        self.provenance = provenance
        # The zip the font came out of, which a licence inside it is taken from too.
        self.archive = archive


def cache_path(url, root=None):
    """A readable cache path for a URL, under the cache root."""
    parsed = urllib.parse.urlparse(url)
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    safe = [re.sub(r"[^A-Za-z0-9._\[\]-]", "_", part) for part in parts]
    return (root or CACHE).joinpath(parsed.netloc, *safe)


def fetch(url, root=None, optional=False, refresh=False):
    """A URL as a file on disk, downloaded once. None for an optional URL that is absent.

    Only a 404 makes an optional URL absent, and the miss is recorded beside where the file
    would have gone. Any other failed transfer raises: a probe that never reached the server
    has not established that the file is missing, and taking it as missing would ship a font
    without the licence covering it. Recording the miss lets a warm cache build offline.
    """
    target = cache_path(url, root)
    absent = target.with_name(target.name + ABSENT)
    if not refresh:
        if target.exists():
            return target
        if optional and absent.exists():
            return None
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    if not optional:
        print(f"    fetching {url}")
    try:
        urllib.request.urlretrieve(url, partial)
        partial.replace(target)
        absent.unlink(missing_ok=True)
    except urllib.error.HTTPError as exc:
        if optional and exc.code == 404:
            absent.touch()
            return None
        raise FetchError(f"could not fetch {url}: {exc}") from None
    except OSError as exc:
        # No marker: the file may well be there. The empty directory goes too.
        prune(target.parent, root or CACHE)
        raise FetchError(f"could not fetch {url}: {exc}") from None
    finally:
        partial.unlink(missing_ok=True)
    return target


def prune(directory, root):
    """Remove `directory` and each empty parent, stopping at `root`.

    The root is compared against, not just arrived at. Without it, an empty cache lets this
    walk out and take whatever empty directories the caller had above it.
    """
    root = pathlib.Path(root).resolve()
    directory = pathlib.Path(directory).resolve()
    if root not in directory.parents:
        return
    while directory != root and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent


def ends_with_path(name, member):
    """Whether `name` ends with `member` on whole path components.

    Not PurePosixPath.match, which reads `member` as a glob and so fails to match a Material
    Symbols filename like MaterialSymbolsOutlined[FILL,GRAD,opsz,wght].ttf against itself.
    """
    parts, wanted = pathlib.PurePosixPath(name).parts, pathlib.PurePosixPath(member).parts
    return len(wanted) <= len(parts) and parts[-len(wanted) :] == wanted


def unzip(archive, member, optional=False):
    """One file out of a fetched zip, extracted beside it.

    A member is matched exactly, or on whole path components from the end, and the
    version-stamped directory a release zip unpacks into stays out of the manifest and
    `Bold.ttf` does not match `SemiBold.ttf`. The extracted copy keeps that path: two
    members of one basename would otherwise serve each other's font.
    """
    inside = pathlib.Path(*(part for part in pathlib.Path(member).parts if part not in ("..", "/")))
    target = archive.parent / f"{archive.stem}.d" / inside
    if target.exists():
        return target
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if member not in names:
                matches = [name for name in names if ends_with_path(name, member)]
                if not matches:
                    if optional:
                        return None
                    fonts = [name for name in names if name.endswith((".ttf", ".otf"))] or names
                    raise AfError(f"{archive.name} has no {member}. It holds: " + ", ".join(fonts[:12]) + (" ..." if len(fonts) > 12 else ""))
                if len(matches) > 1:
                    raise AfError(f"{archive.name} has {len(matches)} files ending " f"{member}: " + ", ".join(sorted(matches)) + ". Name one of them in full")
                member = matches[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(member))
    except zipfile.BadZipFile:
        raise AfError(f"{archive} is not a zip") from None
    return target


def parse_metadata(text):
    """The `fonts` and `axes` blocks of a METADATA.pb, without a protobuf dependency."""
    fonts, axes = [], []
    for block, body in re.findall(r"^(fonts|axes) \{\n(.*?)^\}", text, re.MULTILINE | re.DOTALL):
        fields = dict(re.findall(r'^\s*(\w+):\s*"?([^"\n]*)"?\s*$', body, re.MULTILINE))
        (fonts if block == "fonts" else axes).append(fields)
    return fonts, axes


def google(family, weight, style, root=None):
    """A Google Fonts family at a weight and style, static or variable.

    A variable family's METADATA.pb lists a `wght` axis and one file per style. The weight
    goes in as a coordinate. A static family lists a file per weight; an
    unavailable weight is refused by name.
    """
    slug = re.sub(r"[^a-z0-9]", "", family.lower())
    metadata = directory = None
    for candidate in GOOGLE_DIRS:
        metadata = fetch(f"{GOOGLE_RAW}{candidate}/{slug}/METADATA.pb", root, optional=True)
        if metadata:
            directory = candidate
            break
    if not metadata:
        raise AfError(f"no {family!r} in google/fonts. Looked for {slug}/METADATA.pb " f"under {', '.join(GOOGLE_DIRS)}")

    base = f"{GOOGLE_RAW}{directory}/{slug}/"
    fonts, axes = parse_metadata(metadata.read_text(encoding="utf-8", errors="replace"))
    licences = [found for found in (fetch(base + name, root, optional=True) for name in GOOGLE_LICENCES) if found]

    weight_axis = next((axis for axis in axes if axis.get("tag") == "wght"), None)
    styled = [font for font in fonts if font.get("style", "normal") == style]
    if not styled:
        have = sorted({font.get("style", "normal") for font in fonts})
        raise AfError(f"{family} has no {style} style. It has: {', '.join(have)}")

    if weight_axis:
        low, high = float(weight_axis["min_value"]), float(weight_axis["max_value"])
        if not low <= weight <= high:
            raise AfError(f"{family} is variable on the wght axis from {low:g} to {high:g}, " f"so {weight} is out of range")
        filename = styled[0]["filename"]
        axis_setting = {"wght": float(weight)}
    else:
        exact = [font for font in styled if int(font.get("weight", 400)) == weight]
        if not exact:
            have = sorted({int(font.get("weight", 400)) for font in styled})
            raise AfError(f"{family} {style} has no weight {weight}. It has: " + ", ".join(str(value) for value in have))
        filename = exact[0]["filename"]
        axis_setting = {}

    path = fetch(base + urllib.parse.quote(filename), root)
    return Resolved(path, axis_setting, licences, f"google/fonts {directory}/{slug}/{filename}")


def material(style, root=None):
    """Material Symbols, the variable font. FILL, GRAD, opsz and wght are axes."""
    if style not in MATERIAL_FILES:
        raise AfError(f"material:{style} is not one of " + ", ".join(sorted(MATERIAL_FILES)))
    name = MATERIAL_FILES[style]
    path = fetch(MATERIAL_RAW + "variablefont/" + urllib.parse.quote(name), root)
    licence = fetch(MATERIAL_RAW + "LICENSE", root, optional=True)
    return Resolved(path, {}, [licence] if licence else [], f"google/material-design-icons variablefont/{name}")


def latest_release(repo, root=None):
    """The tag of a repository's latest release, over the API.

    The one call here that needs the API, and the one that makes a build depend on what
    upstream has published since. Pin `release` to a tag to keep a build reproducible.

    Fetched past the cache, or the first tag would stand for every later build and `latest`
    would quietly mean "latest as of whenever this cache was filled".
    """
    target = fetch(GITHUB_API.format(repo=repo), root, refresh=True)
    try:
        tag = json.loads(target.read_text(encoding="utf-8"))["tag_name"]
    except (ValueError, KeyError):
        raise AfError(f"could not read the latest release of {repo}") from None
    print(f"    {repo} latest is {tag}")
    return tag


def github(repo, release=None, asset=None, ref=None, path=None, root=None):
    """A release asset, or a file in the repository.

    A pinned `release` and an `asset` name build the download URL directly. Only
    `release = "latest"` costs an API call, of the sixty an hour an unauthenticated
    caller gets.
    """
    if repo.count("/") != 1:
        raise AfError(f"github:{repo} wants owner/repo")
    if (release or asset) and (ref or path):
        raise AfError(f"github:{repo}: give release and asset, or ref and path, " "not both")

    if release or asset:
        if not asset:
            raise AfError(f'github:{repo}: a release needs asset = "...", the ' "filename as the release page lists it")
        if release in (None, "latest"):
            release = latest_release(repo, root)
        url = GITHUB_RELEASE.format(repo=repo, release=release, asset=asset)
        return Resolved(fetch(url, root), {}, [], f"github {repo} {release} {asset}")

    if not path:
        raise AfError(f'github:{repo}: needs asset = "..." for a release, or ' 'path = "..." for a file in the repository')
    ref = ref or "HEAD"
    url = GITHUB_RAW.format(repo=repo, ref=ref, path=urllib.parse.quote(path))
    return Resolved(fetch(url, root), {}, [], f"github {repo} {ref} {path}")


def resolve(spec, weight=400, style="normal", where=".", member=None, licence=None, release=None, asset=None, ref=None, path=None, root=None):
    """A source spec as a font on disk.

    `where` is the manifest's directory, the root for a file: path. `licence` names one
    more licence file for the zip, as a path or a URL, for a source that publishes none
    where the fetcher looks.
    """
    if not isinstance(spec, str) or ":" not in spec:
        raise AfError(f"source {spec!r} needs a scheme: google:, material:, url: or file:")
    scheme, _, rest = spec.partition(":")

    if scheme == "google":
        found = google(rest, weight, style, root)
    elif scheme == "material":
        found = material(rest, root)
    elif scheme == "github":
        found = github(rest, release, asset, ref, path, root)
    elif scheme in ("url", "http", "https"):
        url = rest if scheme == "url" else spec
        found = Resolved(fetch(url, root), {}, [], url)
    elif scheme == "file":
        local = (pathlib.Path(where) / rest).resolve()
        if not local.exists():
            raise AfError(f"no font at {local}")
        found = Resolved(local, {}, [], str(local))
    else:
        raise AfError(f"unknown source scheme {scheme!r} in {spec!r}")

    # A download that turned out to be an archive: the font comes out of it, and so does a
    # licence packed alongside.
    if zipfile.is_zipfile(found.path):
        found.archive = found.path
        if not member:
            raise AfError(f'{found.path.name} is a zip. Add member = "..." naming the ' ".ttf or .otf inside it")
        found.path = unzip(found.archive, member)
    elif member:
        raise AfError(f"{found.path.name} is not a zip, so member = {member!r} has " "nothing to take out of it")

    if licence:
        found.licences.append(find_licence(licence, found, where, root))
    return found


def find_licence(licence, found, where, root):
    """The licence a manifest named: inside the archive, beside the manifest, or a URL."""
    if "://" in licence:
        return fetch(licence, root)
    if found.archive:
        inside = unzip(found.archive, licence, optional=True)
        if inside:
            return inside
    beside = pathlib.Path(where) / licence
    if beside.exists():
        return beside
    if found.archive:
        raise AfError(f"no licence at {licence}, in {found.archive.name} or beside the " "manifest")
    raise AfError(f"no licence file at {beside}")
