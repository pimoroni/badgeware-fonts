"""One variant of the manifest, built into glyphs and packed.

A glyph too big for the container is dropped, because `pack` clamps rather than raising and
a clamped glyph draws wrong wherever it appears.

A merge packs two entries or more into one file. The manifest has already checked that the
parts share a grid. What is left to check here is codepoints: a text font holding "s"
collides with an icon remapped to "s", and `on_collision` picks the winner.
"""

import copy

from . import glyphs, sources
from .af import AfError, limits, out_of_range, pack
from .grid import tolerance_for
from .outlines import MAX_CONTOUR, SAFE_CONTOUR


class Built:
    """A packed variant, with everything a report or a zip needs."""

    def __init__(self, variant):
        self.variant = variant
        self.glyphs = []
        self.blob = b""
        self.missing = []
        self.faults = []
        self.warnings = []
        self.dropped = []
        self.fits_at = None
        self.requested = 0
        self.licences = []
        self.provenance = []
        self.applied_axes = {}
        self.quality = 0.0
        self.tolerance = None

    @property
    def points(self):
        return sum(glyph.points() for glyph in self.glyphs)

    @property
    def longest_contour(self):
        return max((len(contour) for glyph in self.glyphs for contour in glyph.contours), default=0)

    def metadata(self):
        """meta.json beside the font, holding what the .af does not record.

        `cap` is the one a caller cannot work out from the file: a badge's draw.add_font
        takes a font's cap height, and every placement rule is in terms of it.
        """
        variant = self.variant
        return {
            "name": variant.id,
            "entry": variant.name,
            "type": variant.type,
            "file": variant.filename,
            "cap": variant.cap,
            "wide": variant.wide,
            "units_per_em": variant.units_per_em or 128,
            "weight": variant.weight,
            "style": variant.style,
            "axes": self.applied_axes,
            "quality": self.quality,
            "tolerance": (round(self.tolerance, 4) if self.tolerance is not None else None),
            "glyphs": len(self.glyphs),
            "points": self.points,
            "bytes": len(self.blob),
            "longest_contour": self.longest_contour,
            "dropped": [f"U+{point:04X}" for point in self.dropped],
            "codepoints": [glyph.codepoint for glyph in self.glyphs],
            "sources": self.provenance,
            "licences": sorted({path.name for path in self.licences}),
        }


def build_all(manifest, variants, cache_root=None, after=None):
    """The chosen variants, plus any part a merge among them needs, in build order.

    `after` is called with each font as it is packed, which is where the CLI reports one.
    """
    done = {}
    for variant in order(variants, manifest):
        built = build(variant, done, manifest, cache_root)
        if after:
            after(built)
    return [done[variant.id] for variant in variants]


def order(variants, manifest):
    """Parts before the merges that take them, each variant once."""
    ordered, seen = [], set()

    def visit(variant):
        if variant.id in seen:
            return
        seen.add(variant.id)
        for part in variant.parts:
            visit(part)
        ordered.append(variant)

    for variant in variants:
        visit(manifest.by_id[variant.id])
    return ordered


def build(variant, done, manifest, cache_root=None):
    if variant.id in done:
        return done[variant.id]
    print(f"  {variant.id}")
    if variant.type == "merge":
        built = build_merge(variant, done, manifest, cache_root)
    elif variant.type == "icons":
        built = build_icons(variant, manifest, cache_root)
    else:
        built = build_text(variant, manifest, cache_root)

    over = out_of_range(built.glyphs, wide=variant.wide)
    if over:
        built.dropped = sorted(over)
        built.fits_at = cap_that_fits(built.glyphs, variant)
        built.glyphs = [glyph for glyph in built.glyphs if glyph.codepoint not in over]
    if not built.glyphs:
        raise AfError(f"{variant.id}: no glyphs were built")
    # After the drop, or a fault could name a glyph the font does not hold.
    built.faults += glyphs.faults(built.glyphs, text=variant.type != "icons")
    built.blob = pack(built.glyphs, units_per_em=variant.units_per_em)
    done[variant.id] = built
    return built


def cap_that_fits(glyphs, variant):
    """The highest cap at which no glyph overflows the coordinate, or None if none does.

    A glyph's reach scales with the cap, making this a straight ratio.
    """
    _low, high, _extent = limits(variant.wide)
    worst = max((max(abs(x), abs(y)) for glyph in glyphs for contour in glyph.contours for x, y in contour), default=0)
    if not worst:
        return None
    fits = int(variant.cap * high / worst)
    return fits if fits >= 1 else None


SOURCE_ARGS = ("member", "licence", "release", "asset", "ref", "path")

# Axes a source satisfies by choosing a file, which `google` does per weight and per style.
# Nothing picks a file by width, and a face with no `wdth` axis ignored the setting.
FILE_SELECTED_AXES = ("wght", "ital")


def resolve_source(variant, manifest, cache_root):
    entry = variant.entry
    return sources.resolve(entry.source, weight=variant.weight, style=variant.style, where=manifest.root, root=cache_root, **{key: getattr(entry, key) for key in SOURCE_ARGS})


def source_face(variant, manifest, ppem, cache_root):
    found = resolve_source(variant, manifest, cache_root)
    face = glyphs.open_face(found.path, ppem)
    applied, ignored = glyphs.set_axes(face, {**found.axes, **variant.axes()})
    return face, found, applied, [key for key in ignored if key.lower() not in FILE_SELECTED_AXES]


def missing_axes(ignored):
    """Axes the entry named that the face has not got.

    Silence here builds an unfilled font from `axes = { FIL = 1 }` and reports success.
    """
    if not ignored:
        return []
    return [f"this face has no {', '.join(ignored)} axis, so it was not set"]


def build_text(variant, manifest, cache_root=None):
    built = Built(variant)
    face, found, applied, ignored = source_face(variant, manifest, glyphs.TEXT_PPEM, cache_root)
    built.licences += found.licences
    built.provenance.append(found.provenance)
    built.applied_axes = applied
    built.warnings += missing_axes(ignored)
    built.quality = variant.quality()
    built.tolerance = tolerance_for(built.quality, variant.extent())
    scale = glyphs.cap_scale(face, variant.cap, variant.entry.cap_from)

    built.requested = len(variant.codepoints)
    for codepoint in variant.codepoints:
        glyph = glyphs.text_glyph(face, codepoint, scale, built.tolerance)
        if glyph is None:
            built.missing.append(codepoint)
            continue
        built.glyphs.append(glyph)
    return built


def build_icons(variant, manifest, cache_root=None):
    built = Built(variant)
    face, found, applied, ignored = source_face(variant, manifest, glyphs.ICON_PPEM, cache_root)
    built.licences += found.licences
    built.provenance.append(found.provenance)
    built.applied_axes = applied
    built.warnings += missing_axes(ignored)
    size = variant.size()
    built.quality = variant.quality()
    built.tolerance = tolerance_for(built.quality, variant.extent())
    mode = variant.entry.codepoints

    # A corpus names each glyph, and an absent one gets a line. A charset names whole blocks
    # and expects gaps, which the coverage line in `summary` counts instead.
    named = bool(variant.entry.corpus or variant.entry.glyphs)
    built.requested = len(variant.glyphs)

    for wanted in variant.glyphs:
        glyph = glyphs.icon_glyph(face, wanted.codepoint, size, built.tolerance)
        if glyph is None:
            built.missing.append(wanted.codepoint)
            if named:
                built.warnings.append(f"{wanted.name} is not in this face, skipped")
            continue
        glyph.codepoint = wanted.target(mode)
        built.glyphs.append(glyph)
    return built


def build_merge(variant, done, manifest, cache_root=None):
    built = Built(variant)
    mode = variant.entry.on_collision
    by_codepoint, source_of = {}, {}

    for part in variant.parts:
        made = build(manifest.by_id[part.id], done, manifest, cache_root)
        built.licences += made.licences
        built.provenance += made.provenance
        built.missing += made.missing
        built.requested += made.requested
        built.faults += made.faults
        for glyph in made.glyphs:
            existing = by_codepoint.get(glyph.codepoint)
            if existing is not None:
                held = source_of[glyph.codepoint]
                if mode == "error":
                    raise AfError(f"{variant.id}: {held} and {part.id} both want " f"{glyph.codepoint:04x} ({chr(glyph.codepoint)!r}). Remap one, or " "set on_collision")
                if mode == "first":
                    continue
                built.warnings.append(f"{chr(glyph.codepoint)!r} from {part.id} replaces " f"{held}")
            # Copied: the parts are written out on their own as well as into the merge.
            by_codepoint[glyph.codepoint] = copy.deepcopy(glyph)
            source_of[glyph.codepoint] = part.id

    built.glyphs = [by_codepoint[key] for key in sorted(by_codepoint)]
    # The coarsest part is what the merged file is crisp to. Its tolerance is not carried
    # across: a tolerance is in units of one extent, and the parts have one each.
    built.quality = min(done[part.id].quality for part in variant.parts)
    built.tolerance = None
    return built


def summary(built):
    """The lines the CLI prints under one built font: its grid, its size, and its faults."""
    variant, lines = built.variant, []
    grid = f"wide, cap {variant.cap} of a {variant.units_per_em} unit em" if variant.wide else f"narrow, cap {variant.cap} of a 128 unit em"
    crisp = f"crisp to {built.quality:g}px"
    if built.tolerance is not None:
        crisp += f" (tolerance {built.tolerance:.2f} units)"
    lines.append(f"    {grid}, {crisp}")
    if built.applied_axes:
        lines.append("    axes: " + ", ".join(f"{tag}={value:g}" for tag, value in built.applied_axes.items()))
    if variant.type == "icons":
        lines.append(f"    {len(variant.glyphs)} glyphs in a {variant.size()} box, " f"codepoints {variant.entry.codepoints}")
    per_glyph = len(built.blob) // max(1, len(built.glyphs))
    lines.append(f"    {len(built.glyphs)} glyphs, {built.points} points, " f"{len(built.blob)} bytes ({per_glyph} each)")
    fits = "fits any firmware" if built.longest_contour <= SAFE_CONTOUR else f"over {SAFE_CONTOUR}, so it needs picovector 39a44c3 or newer"
    lines.append(f"    longest contour {built.longest_contour} of {MAX_CONTOUR}, {fits}")
    if built.missing:
        absent = sorted(set(built.missing))
        shown = " ".join(f"{point:04x}" for point in absent[:16])
        lines.append(f"    {len(absent)} of {built.requested} codepoints are not in the face: " f"{shown}" + (" ..." if len(absent) > 16 else ""))
    if built.dropped:
        remedy = f"a cap of {built.fits_at} would hold them, or pack wide" if built.fits_at else "pack wide to hold them"
        lines.append("    left out, too big for the format: " + " ".join(chr(point) for point in built.dropped) + f". At cap {variant.cap}, {remedy}")
    for fault in built.faults:
        lines.append(f"    error: {fault}")
    for warning in built.warnings:
        lines.append(f"    warning: {warning}")
    return lines


def faulty(builds):
    """The fonts no firmware will draw correctly.

    One of these holds back the whole build. Writing it would ship an artefact whose fault
    only shows up on the badge.
    """
    return [built for built in builds if built.faults]


def write_web(built, out, cache_root=None, manifest=None):
    """The same corpus as a woff2, for a config UI that draws the same glyphs.

    Built from the corpus and source face the .af came from. A second hand-kept list would
    drift. None where fonttools is absent: the woff2 is an extra for a config UI, and the
    fonts a badge draws do not depend on it.
    """
    try:
        from fontTools import subset
    except ImportError:
        return None
    variant = built.variant
    if variant.type != "icons":
        raise AfError(f"{variant.id}: web is for icon entries, which have a corpus")
    found = resolve_source(variant, manifest, cache_root)
    points = ",".join(f"U+{wanted.codepoint:04X}" for wanted in variant.glyphs)
    out.parent.mkdir(parents=True, exist_ok=True)
    subset.main([str(found.path), f"--unicodes={points}", "--flavor=woff2", "--layout-features=", "--no-hinting", "--desubroutinize", f"--output-file={out}"])
    return out
