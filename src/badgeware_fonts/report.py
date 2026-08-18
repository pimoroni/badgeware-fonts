"""What is in an .af font, read off the file. Where to start with one that will not draw.

A capital should stand the cap height the font was built to, the unit a badge's font sizes
are given in. An advance should be a little wider than the ink inside it: an advance of one
or two units under real ink means the units were mixed up, which nothing else catches.
"""

from .af import COORD_MAX, WIDE_COORD_MAX, read
from .grid import MIN_ADVANCE_RATIO

DETAIL_CHARS = "HxpO0.,%-/ "


def describe(path, chars=DETAIL_CHARS, show_all=False):
    font = read(path)
    glyphs = font["glyphs"]
    by_codepoint = {glyph["codepoint"]: glyph for glyph in glyphs}
    limit = WIDE_COORD_MAX if font["wide"] else COORD_MAX
    lines = [f"{path}: {font['size']} bytes, {len(glyphs)} glyphs, {font['points']} points, {font['size'] // max(1, len(glyphs))} bytes each"]

    codepoints = sorted(by_codepoint)
    ascii_have = sum(1 for point in range(0x20, 0x7F) if point in by_codepoint)
    lines.append(f"  codepoints {codepoints[0]:#x}..{codepoints[-1]:#x}, " f"printable ASCII {ascii_have}/95, " f"degree sign {'yes' if 0xB0 in by_codepoint else 'NO'}")

    tall = max(glyphs, key=lambda glyph: glyph["bbox_h"])
    reach = max((max((max(abs(x), abs(y)) for x, y in zip(glyph["points"][0::2], glyph["points"][1::2], strict=True)), default=0) for glyph in glyphs), default=0)
    lines.append(f"  {'wide' if font['wide'] else 'narrow'}, " f"{font['units_per_em']} units per em")
    cap = by_codepoint.get(ord("H"))
    if cap:
        lines.append(f"  a capital stands {cap['bbox_h']}")
    lines.append(f"  tallest {chr(tall['codepoint'])!r} at {tall['bbox_h']}, " f"furthest point {reach} of {limit}")

    suspect = [glyph for glyph in glyphs if glyph["contours"] and glyph["advance"] < glyph["bbox_w"] * MIN_ADVANCE_RATIO]
    if suspect:
        lines.append(f"  {len(suspect)} glyphs carry more ink than advance, which is what " "a units mix-up looks like: " + " ".join(repr(chr(glyph["codepoint"])) for glyph in suspect[:12]))

    show = codepoints if show_all else [ord(c) for c in chars]
    lines.append(f"\n  {'char':<6} {'cp':>5} {'bbox x':>7} {'y':>4} {'w':>4} {'h':>4} " f"{'adv':>4} {'contours':>9}")
    for codepoint in show:
        glyph = by_codepoint.get(codepoint)
        if glyph is None:
            lines.append(f"  {chr(codepoint)!r:<6} not in this font")
            continue
        lines.append(f"  {chr(codepoint)!r:<6} {codepoint:5d} {glyph['bbox_x']:7d} " f"{glyph['bbox_y']:4d} {glyph['bbox_w']:4d} {glyph['bbox_h']:4d} " f"{glyph['advance']:4d} {glyph['contours']:9d}")
    return lines
