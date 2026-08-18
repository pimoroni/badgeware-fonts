"""The .af container, as alright-fonts writes it and the badgeware firmware reads it.

A four-byte marker, flags, then counts of glyphs, contours and points as big-endian u16.
Then the glyph table, the length of every contour, and finally the points.

Points are y-down from the baseline: a glyph above it has negative y. bbox_y is y-up
and goes negative only for a descender. x starts at the left of the advance, ink offset by
the side bearing.

`pack` and `unpack` are held to each other by a round trip in tests/test_af.py. Reading a
font back needs struct alone, not freetype or shapely. The sizes a glyph is built to are
`grid`.
"""

import struct

AF_MAGIC = b"af!?"
AF_FLAG_16BIT_POINT_COUNT = 0b0000001
# Wide: 16-bit bbox, advance and points, then a u16 units-per-em after the counts. A narrow
# font holds the whole em in a signed byte, and a glyph drawn a hundred pixels tall shows
# stepped outlines.
AF_FLAG_WIDE = 0b0000010
HEADER = ">HHHH"  # flags, glyphs, contours, points, after the marker
GLYPH_STRUCT = ">HbbBBBB"  # codepoint, then bbox x y w h, advance, contour count
GLYPH_STRUCT_WIDE = ">HhhHHHB"
NARROW_UNITS_PER_EM = 128
# The 81:128 cap-to-em ratio `units_per_em_for` holds a wide font to.
REFERENCE_CAP = 81

# Narrow coordinates and advances are signed bytes.
COORD_MIN, COORD_MAX = -128, 127
WIDE_COORD_MIN, WIDE_COORD_MAX = -32768, 32767
MAX_CODEPOINT = 0xFFFF

GLYPH_FIELDS = ("codepoint", "bbox_x", "bbox_y", "bbox_w", "bbox_h", "advance", "contours")


class AfError(Exception):
    """A font that cannot be built, packed or read. The CLI prints it and exits 1."""


class ManifestError(AfError):
    """A manifest that cannot be read: a bad key, a bad value, a merge that cannot line up.

    Raised before anything is fetched: the fix is in fonts.toml, never upstream.
    It lives here rather than in `manifest`, which imports the `charsets` and `corpus` modules
    that also raise it.
    """


class Glyph:
    """What `pack` takes: a codepoint, its contours, and where the ink sits in the advance."""

    def __init__(self, codepoint):
        self.codepoint = codepoint
        self.contours = []
        self.advance = 0
        self.bbox_x = self.bbox_y = self.bbox_w = self.bbox_h = 0

    def points(self):
        return sum(len(contour) for contour in self.contours)


def limits(wide):
    """The low and high a coordinate fits between, then the ceiling on an advance or extent."""
    if wide:
        return WIDE_COORD_MIN, WIDE_COORD_MAX, 0xFFFF
    return COORD_MIN, COORD_MAX, 255


def wide_for(cap):
    """Whether `cap` needs the 16-bit path: an ascender over 127 leaves the signed byte."""
    return cap > COORD_MAX


def units_per_em_for(cap):
    """The em to record for a wide font at `cap`, or None for a narrow one.

    Holds the reference cap-to-em ratio, keeping one font_size at one height either width.
    """
    if not wide_for(cap):
        return None
    return round(cap * NARROW_UNITS_PER_EM / REFERENCE_CAP)


def clamp(value, low, high):
    return max(low, min(high, int(value)))


def out_of_range(glyphs, wide=False):
    """Codepoints of glyphs `pack` would have to clamp to fit.

    Points, the bbox and the advance alike. `pack` clamps rather than raising. A clamped
    advance draws a word in one place, which is why a caller drops what this reports.
    """
    low, high, extent = limits(wide)
    over = []
    for glyph in glyphs:
        if not 0 <= glyph.advance <= extent:
            over.append(glyph.codepoint)
            continue
        if not low <= glyph.bbox_x <= high or not low <= glyph.bbox_y <= high:
            over.append(glyph.codepoint)
            continue
        if not 0 <= glyph.bbox_w <= extent or not 0 <= glyph.bbox_h <= extent:
            over.append(glyph.codepoint)
            continue
        if any(not low <= x <= high or not low <= y <= high for contour in glyph.contours for x, y in contour):
            over.append(glyph.codepoint)
    return over


def pack(glyphs, units_per_em=None):
    """The .af file: header, glyph table, contour lengths, then points.

    Pass units_per_em to write a wide font, whose bbox, advance and points are 16-bit and
    whose em is whatever the caller built the glyphs to. Without it the font is narrow,
    every coordinate is a signed byte and the em is 128 by convention.

    Glyphs are written in codepoint order: two builds of one corpus agree whatever
    order the entries were listed in.
    """
    glyphs = sorted(glyphs, key=lambda glyph: glyph.codepoint)
    for glyph in glyphs:
        if glyph.codepoint > MAX_CODEPOINT:
            raise AfError(
                f"codepoint {glyph.codepoint:x} does not fit the format, which stores "
                "them as u16. Remap it to a printable character with a third field in "
                'the corpus, or set codepoints = "printable".'
            )

    wide = units_per_em is not None
    if wide and not 1 <= units_per_em <= 0xFFFF:
        raise AfError(f"units per em {units_per_em} does not fit the format's u16")
    low, high, extent_high = limits(wide)

    contours = sum(len(glyph.contours) for glyph in glyphs)
    points = sum(len(contour) for glyph in glyphs for contour in glyph.contours)
    for what, count in (("glyphs", len(glyphs)), ("contours", contours), ("points", points)):
        if count > 0xFFFF:
            raise AfError(f"{count} {what} does not fit the format's u16. Lower the quality, or pack fewer codepoints")

    flags = AF_FLAG_16BIT_POINT_COUNT | (AF_FLAG_WIDE if wide else 0)
    out = bytearray(AF_MAGIC)
    out += struct.pack(HEADER, flags, len(glyphs), contours, points)
    if wide:
        out += struct.pack(">H", units_per_em)

    glyph_struct = GLYPH_STRUCT_WIDE if wide else GLYPH_STRUCT
    for glyph in glyphs:
        out += struct.pack(
            glyph_struct,
            glyph.codepoint,
            clamp(glyph.bbox_x, low, high),
            clamp(glyph.bbox_y, low, high),
            clamp(glyph.bbox_w, 0, extent_high),
            clamp(glyph.bbox_h, 0, extent_high),
            clamp(glyph.advance, 0, extent_high),
            len(glyph.contours),
        )
    for glyph in glyphs:
        for contour in glyph.contours:
            out += struct.pack(">H", len(contour))
    point_struct = ">hh" if wide else ">bb"
    for glyph in glyphs:
        for contour in glyph.contours:
            for x, y in contour:
                out += struct.pack(point_struct, clamp(x, low, high), clamp(y, low, high))
    return bytes(out)


def unpack(data, name="<bytes>"):
    """A packed font as data: its glyphs, their points, and the grid they sit on.

    Every read is bounds checked, and a file cut short by a failed transfer is named as such.
    Left to struct it would surface as an unpacking error at some byte offset.
    """
    if data[:4] != AF_MAGIC:
        raise AfError(f"{name} does not start with {AF_MAGIC!r}")
    try:
        return _unpack(data, name)
    except (struct.error, IndexError):
        raise AfError(f"{name} stops partway through: {len(data)} bytes is short of what " "its header claims") from None


def _unpack(data, name):
    flags, glyph_count, contour_count, point_count = struct.unpack_from(HEADER, data, 4)
    at = 4 + struct.calcsize(HEADER)
    if not glyph_count:
        raise AfError(f"{name} holds no glyphs")

    wide = bool(flags & AF_FLAG_WIDE)
    units_per_em = NARROW_UNITS_PER_EM
    if wide:
        units_per_em = struct.unpack_from(">H", data, at)[0]
        at += 2

    glyph_struct = GLYPH_STRUCT_WIDE if wide else GLYPH_STRUCT
    glyphs = []
    for _ in range(glyph_count):
        fields = struct.unpack_from(glyph_struct, data, at)
        at += struct.calcsize(glyph_struct)
        glyphs.append(dict(zip(GLYPH_FIELDS, fields, strict=True)))

    lengths = []
    for _ in range(contour_count):
        if flags & AF_FLAG_16BIT_POINT_COUNT:
            lengths.append(struct.unpack_from(">H", data, at)[0])
            at += 2
        else:
            lengths.append(data[at])
            at += 1

    # Points flat, to check a glyph's extent against its bbox, and split into the
    # contours `pack` takes, to compare a rebuild against the font that shipped.
    point_code, point_size = ("h", 4) if wide else ("b", 2)
    index = 0
    for glyph in glyphs:
        spans = lengths[index : index + glyph["contours"]]
        span = sum(spans)
        glyph["points"] = struct.unpack_from(f">{span * 2}{point_code}", data, at) if span else ()
        outlines, taken = [], 0
        for length in spans:
            flat = glyph["points"][taken * 2 : (taken + length) * 2]
            outlines.append(list(zip(flat[0::2], flat[1::2], strict=True)))
            taken += length
        glyph["outlines"] = outlines
        index += glyph["contours"]
        at += span * point_size
    return {"size": len(data), "flags": flags, "glyphs": glyphs, "points": point_count, "wide": wide, "units_per_em": units_per_em}


def to_glyphs(font):
    """A font `unpack` returned, back as the `Glyph` objects `pack` takes."""
    made = []
    for found in font["glyphs"]:
        glyph = Glyph(found["codepoint"])
        glyph.contours = [list(contour) for contour in found["outlines"]]
        glyph.advance = found["advance"]
        glyph.bbox_x, glyph.bbox_y = found["bbox_x"], found["bbox_y"]
        glyph.bbox_w, glyph.bbox_h = found["bbox_w"], found["bbox_h"]
        made.append(glyph)
    return made


def read(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise AfError(f"cannot read {path}: {exc.strerror}") from None
    return unpack(data, str(path))
