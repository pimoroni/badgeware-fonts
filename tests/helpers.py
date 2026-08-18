"""Shared test fixtures: synthetic glyphs, manifests on disk, and stand-ins for `package`."""

import contextlib

import pytest

from badgeware_fonts import af, cli, manifest, sources
from badgeware_fonts import build as builder


def glyph(codepoint, contours, **fields):
    """A `Glyph` with its contours and whichever metrics the caller names."""
    made = af.Glyph(codepoint)
    made.contours = contours
    for name, value in fields.items():
        setattr(made, name, value)
    return made


@contextlib.contextmanager
def refuses(*facts, error=af.AfError):
    """Assert the block raises `error`, and that the message carries each of `facts`.

    The facts are what a user needs handed back: the name they typed, the value that was
    wrong, the alternatives on offer. The sentence joining them is prose and is not asserted,
    so rewording a message leaves these tests alone.
    """
    with pytest.raises(error) as caught:
        yield
    missing = [fact for fact in facts if str(fact) not in str(caught.value)]
    assert not missing, f"the refusal left out {missing}: {caught.value}"


def read_manifest(text, where):
    """`text` as a manifest beside `where`, parsed but not built."""
    path = where / "fonts.toml"
    path.write_text(text, encoding="utf-8")
    return manifest.read(path)


def build_manifest(text, where, cache_root):
    """Every font in `text`, keyed by variant id.

    Skipped where a source cannot be fetched, and only there. Any other failure is the one
    under test.
    """
    found = read_manifest(text, where)
    try:
        made = builder.build_all(found, found.variants, cache_root=cache_root)
    except sources.FetchError as exc:
        pytest.skip(f"cannot reach the source fonts: {exc}")
    return {one.variant.id: one for one in made}


def build_refused(text, where, cache_root, complaint, names=()):
    """Assert building `text` is refused, naming `complaint` in the refusal.

    A build that cannot be attempted skips, the same way `build_manifest` does, so an
    unreachable source never masquerades as the refusal being tested.
    """
    found = read_manifest(text, where)
    chosen = found.select(names) if names else found.variants
    try:
        builder.build_all(found, chosen, cache_root=cache_root)
    except sources.FetchError as exc:
        pytest.skip(f"cannot reach the source fonts: {exc}")
    except af.AfError as exc:
        assert complaint in str(exc), f"refused, but saying {str(exc)!r}"
        return
    raise AssertionError(f"built without refusing, where {complaint!r} was expected")


def cli_build(text, where, cache_root, *extra):
    """`badgeware-fonts build` over `text`, as its exit code and the directory it wrote to.

    The sources are fetched first, so a fetch failure skips the test rather than arriving as
    the exit code under examination.
    """
    build_manifest(text, where, cache_root)
    out = where / "out"
    return cli.main(["--manifest", str(where / "fonts.toml"), "build", *extra, "--out", str(out), "--cache", str(cache_root)]), out


def cff_font(where, name="cubic.otf"):
    """A small .otf whose H is a cubic, which no TrueType face can be.

    TrueType outlines are quadratic throughout, so this is the only way to reach the cubic
    half of the flattener. It carries a blank space as well, for the paths that turn on a
    glyph having no ink. Needs fontTools, which the `web` extra brings.
    """
    builder = pytest.importorskip("fontTools.fontBuilder")
    pens = pytest.importorskip("fontTools.pens.t2CharStringPen")

    def charstring(draw):
        pen = pens.T2CharStringPen(600, None)
        draw(pen)
        pen.closePath()
        return pen.getCharString()

    def cap(pen):
        # Tall against its width, or scaling it to a cap of 81 runs the outline past the byte.
        pen.moveTo((100, 0))
        pen.curveTo((100, 1000), (500, 1000), (500, 0))

    def blank(pen):
        pen.moveTo((0, 0))

    fb = builder.FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder([".notdef", "H", "space"])
    fb.setupCharacterMap({ord("H"): "H", ord(" "): "space"})
    fb.setupCFF("Cubic", {"FullName": "Cubic"}, {"H": charstring(cap), "space": charstring(blank), ".notdef": charstring(blank)}, {})
    fb.setupHorizontalMetrics({"H": (600, 100), "space": (250, 0), ".notdef": (600, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Cubic", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    path = where / name
    fb.save(path)
    return path


class FakeVariant:
    def __init__(self, name, variant_id, weight=400):
        self.name = name
        self.id = variant_id
        self.weight = weight

    @property
    def filename(self):
        return f"{self.id}.af"


class FakeBuilt:
    """What `package` reads: a name, some bytes, its licences and its metadata."""

    def __init__(self, name, variant_id, blob, licences, weight=400):
        self.variant = FakeVariant(name, variant_id, weight)
        self.blob = blob
        self.licences = list(licences)

    def metadata(self):
        return {"name": self.variant.id, "weight": self.variant.weight, "licences": sorted({path.name for path in self.licences})}


def licence(where, name, text):
    """A licence file whose directory keeps it apart from others of the same name."""
    path = where / text.replace(" ", "-") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
