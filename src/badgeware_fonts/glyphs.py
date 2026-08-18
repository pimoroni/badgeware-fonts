"""Two geometries: a text glyph on the face's own metrics, an icon fitted to a box.

What differs between them is all of the geometry:

  - an icon is fitted to a box and given a made-up advance, because it stands alone. A
    text glyph keeps the face's advance and side bearing, or the words do not space.
  - an icon scales on whichever axis is tighter. A text font takes one scale for every
    glyph, from the cap height, or the letters do not share a baseline.

Where the numbers sit, whatever the face. A capital stands `cap` units, the unit a badge's
font sizes are given in. Points are y-down from the baseline, which puts ink above it at a
negative y, a cap of 81 reaching y -81. bbox_y is y-up and goes negative only for a
descender. bbox_x
is the left side bearing, and x is measured from the pen. A blank glyph carries an advance
and no contours.

`badgeware-fonts inspect` prints all of it for a font that was built and does not draw.
"""

import freetype

from .af import AfError, Glyph
from .grid import MIN_ADVANCE_RATIO
from .outlines import LOAD_FLAGS, MAX_CONTOUR, Bounds, clean_contours, outline_contours

# The ppem each path sets on the face before loading a glyph. Arbitrary, since every
# measurement here is a ratio taken at the same ppem, but FreeType hints at this size, so
# changing one changes the outlines that build.
TEXT_PPEM = 1000
ICON_PPEM = 64 * 64

# Tags for the axes a badge font uses.
AXIS_ALIASES = {
    "weight": "wght",
    "width": "wdth",
    "slant": "slnt",
    "italic": "ital",
    "grade": "grad",
    "optical_size": "opsz",
    "optical-size": "opsz",
}


def open_face(path, ppem):
    try:
        face = freetype.Face(str(path))
        face.set_char_size(ppem)
    except Exception as exc:
        raise AfError(f"{path} is not a font FreeType can read: {exc}") from None
    return face


def set_axes(face, requested):
    """Set variation axes by tag, reporting any this face has not got.

    Matched on the tag rather than the name, and `wght` reaches the axis whether the face
    calls it Weight or Grosor. Design coordinates, not 16.16: passing fixed point clamps
    every axis to its maximum.

    Returns what was applied and what the face has no axis for.
    """
    # Keyed by the tag to match on, valued by the spelling to report back.
    wanted = {AXIS_ALIASES.get(key.lower(), key).lower(): (key, value) for key, value in (requested or {}).items() if value is not None}
    if not wanted:
        return {}, []
    try:
        axes = face.get_variation_info().axes
    except Exception:
        return {}, sorted(key for key, _value in wanted.values())

    coords, applied = [], {}
    for axis in axes:
        tag = axis.tag.decode() if isinstance(axis.tag, bytes) else str(axis.tag)
        given = wanted.pop(tag.lower(), None)
        if given is None:
            coords.append(axis.default)
            continue
        _key, value = given
        if not axis.minimum <= value <= axis.maximum:
            raise AfError(f"{tag} {value} is outside this face's " f"{axis.minimum:g} to {axis.maximum:g}")
        coords.append(value)
        applied[tag] = value
    if applied:
        face.set_var_design_coords(coords)
    return applied, sorted(key for key, _value in wanted.values())


def cap_scale(face, cap, sample="H"):
    """Font units per output unit, at which a capital stands `cap`."""
    if face.get_char_index(ord(sample)) == 0:
        raise AfError(f"this face has no {sample!r} to measure a cap height from. " "Set cap_from to a character it does have")
    face.load_char(sample, LOAD_FLAGS)
    height = Bounds(face.glyph.outline.get_bbox()).height
    if not height:
        raise AfError(f"{sample!r} has no outline to measure a cap height from")
    return height / cap


def text_glyph(face, codepoint, scale, tolerance):
    """One glyph on the face's own advance and side bearing. None if the face has not got it."""
    if face.get_char_index(codepoint) == 0:
        return None
    face.load_char(codepoint, LOAD_FLAGS)

    glyph = Glyph(codepoint)
    # The advance and the outline bbox both come back in FreeType's 26.6 fixed point, and one
    # scale converts both. Dividing by 64 as well leaves every glyph an advance of about one.
    glyph.advance = round(face.glyph.advance.x / scale)

    source = Bounds(face.glyph.outline.get_bbox())
    if not source.width or not source.height:
        return glyph

    contours = [[(x / scale, -y / scale) for x, y in contour] for contour in outline_contours(face, scale)]
    contours = clean_contours(contours, tolerance)
    contours = [contour for contour in contours if len(contour) > 2]
    if not contours:
        return glyph

    glyph.contours = [[(round(x), round(y)) for x, y in contour] for contour in contours]
    glyph.bbox_x = round(source.x / scale)
    glyph.bbox_y = round(source.y / scale)
    glyph.bbox_w = round(source.width / scale)
    glyph.bbox_h = round(source.height / scale)
    return glyph


def icon_glyph(face, codepoint, size, tolerance):
    """One icon, fitted to a `size` box and placed like a text glyph.

    None if the face has no such glyph, or it has no outline.
    """
    if face.get_char_index(codepoint) == 0:
        return None
    face.load_char(codepoint, LOAD_FLAGS)

    source = Bounds(face.glyph.outline.get_bbox())
    if not source.width or not source.height:
        return None

    # An icon fills its box instead of following the face's metrics. It scales on
    # whichever axis is tighter, keeping its aspect ratio.
    scale = max(source.width / size, source.height / size)
    ink_w, ink_h = source.width / scale, source.height / scale
    pad_x, pad_y = (size - ink_w) / 2, (size - ink_h) / 2

    # Scaled to output units before cleaning: `tolerance` is in output units.
    contours = [[((x - source.x) / scale + pad_x, -((y - source.y) / scale + pad_y)) for x, y in contour] for contour in outline_contours(face, scale)]
    contours = clean_contours(contours, tolerance)
    contours = [contour for contour in contours if len(contour) > 2]
    if not contours:
        return None

    glyph = Glyph(codepoint)
    glyph.contours = [[(round(x), round(y)) for x, y in contour] for contour in contours]
    glyph.bbox_x, glyph.bbox_y = round(pad_x), round(pad_y)
    glyph.bbox_w, glyph.bbox_h = round(ink_w), round(ink_h)
    glyph.advance = size
    return glyph


def faults(glyphs, text=True):
    """Glyphs no firmware will draw correctly, though the container holds them.

    A contour the renderer's buffer skips loses part of its glyph, and an advance far under
    its ink stacks a word on one spot. The caller refuses the build rather than writing either.

    What will not fit the container at all is `af.out_of_range`, and those glyphs are
    dropped.
    """
    problems = []
    for glyph in glyphs:
        char = chr(glyph.codepoint)
        if text and glyph.contours and glyph.advance < glyph.bbox_w * MIN_ADVANCE_RATIO:
            problems.append(f"{char!r} advance {glyph.advance} against " f"{glyph.bbox_w} of ink")
        for contour in glyph.contours:
            if len(contour) > MAX_CONTOUR:
                problems.append(f"{char!r} has a contour of {len(contour)} points, over " f"{MAX_CONTOUR}: raise quality until it is under")
                break
    return problems
