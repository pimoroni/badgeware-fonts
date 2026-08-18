"""FreeType outlines to the polylines .af stores, and the shapely clean-up between them.

alright-fonts' pipeline, cut to what a badge needs.
"""

import math

import freetype
import shapely

# The glyph renderer fills one contour at a time into a fixed buffer, silently skipping any
# that overflows it. At a buffer of 256, 256 points draws, 257 draws nothing.
MAX_CONTOUR = 512  # picovector from 39a44c3, June 2025
SAFE_CONTOUR = 256  # every build before it

# Hinting changes an outline, and every load here uses one flag set. A scale measured under
# one set and glyphs built under another do not share a cap height.
LOAD_FLAGS = freetype.FT_LOAD_PEDANTIC


class Bounds:
    """A glyph's extent, from a FreeType bbox."""

    def __init__(self, box):
        self.x, self.y, self.x2, self.y2 = box.xMin, box.yMin, box.xMax, box.yMax

    @property
    def width(self):
        return self.x2 - self.x

    @property
    def height(self):
        return self.y2 - self.y


def steps_for(points, scale):
    """How finely to flatten a curve, from the length of its control polygon."""
    length = sum(math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) for a, b in zip(points, points[1:], strict=False))
    return max(1, int(length / scale))


def flatten_conic(start, control, target, steps):
    """A quadratic curve as points, from the step after `start` to `target` inclusive.

    The start is already on the contour and the end has to be, or the contour stops short of
    where the next segment begins.
    """
    made = []
    for i in range(1, steps + 1):
        t = i / steps
        made.append(
            (
                (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t * t * target[0],
                (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t * t * target[1],
            )
        )
    return made


def flatten_cubic(start, control_a, control_b, target, steps):
    """A cubic curve as points, on the same terms as `flatten_conic`.

    TrueType outlines are quadratic throughout; a CFF face in an .otf brings cubics.
    """
    made = []
    for i in range(1, steps + 1):
        t = i / steps
        made.append(
            (
                (1 - t) ** 3 * start[0] + 3 * (1 - t) ** 2 * t * control_a[0] + 3 * (1 - t) * t**2 * control_b[0] + t**3 * target[0],
                (1 - t) ** 3 * start[1] + 3 * (1 - t) ** 2 * t * control_a[1] + 3 * (1 - t) * t**2 * control_b[1] + t**3 * target[1],
            )
        )
    return made


def outline_contours(face, scale):
    """Decompose the loaded glyph into polylines, in font units.

    FreeType hands back lines and curves; .af holds only points, and curves are flattened
    here and `clean_contours` takes the redundant points back out.

    `scale` is font units per output unit, and sets how finely curves are cut. A step per
    output unit is already finer than a signed byte expresses; stepping per *font* unit
    costs hundreds of points a glyph that quantise onto the same few coordinates.
    """
    contours = []

    def move_to(target, _ctx):
        contours.append([(target.x, target.y)])

    def line_to(target, _ctx):
        contours[-1].append((target.x, target.y))

    def conic_to(control, target, _ctx):
        start, control, target = contours[-1][-1], (control.x, control.y), (target.x, target.y)
        contours[-1] += flatten_conic(start, control, target, steps_for((start, control, target), scale))

    def cubic_to(control_a, control_b, target, _ctx):
        start, target = contours[-1][-1], (target.x, target.y)
        a, b = (control_a.x, control_a.y), (control_b.x, control_b.y)
        contours[-1] += flatten_cubic(start, a, b, target, steps_for((start, a, b, target), scale))

    face.glyph.outline.decompose(None, move_to=move_to, line_to=line_to, conic_to=conic_to, cubic_to=cubic_to)
    return contours


def clean_contours(contours, tolerance):
    """Resolve overlapping and self-intersecting outlines into simple rings.

    Contours in a real font overlap, wind either way, cross themselves. A renderer that
    fills what it is given shows the seams. Genuine overlaps are unioned here and the
    rings taken back out.

    Nesting counts as separate. A counter sits inside its outer ring without touching it,
    survives as a contour, and stays a hole.
    """
    # Three points make a triangle, and are the fewest shapely accepts as a ring.
    rings = [shapely.LinearRing(contour) for contour in contours if len(contour) > 2]
    if not rings:
        return []
    # buffer(0) is the usual trick for making a self-intersecting ring valid.
    polygons = []
    for polygon in shapely.polygons(rings):
        polygon = polygon.buffer(0)
        # One self-intersecting ring can come back as several polygons.
        polygons.extend(getattr(polygon, "geoms", None) or [polygon])

    polygons = merge_overlaps(polygons)
    polygons = [p if p.is_valid else p.buffer(0) for p in polygons]
    polygons = shapely.polygons(shapely.get_rings(polygons))
    if tolerance:
        polygons = shapely.coverage_simplify(polygons, tolerance=tolerance)
    return [shapely.get_coordinates(polygon) for polygon in polygons]


def merge_overlaps(polygons):
    """Union any polygons that partly overlap, until none do.

    Pairwise on `overlaps`, which is false for containment. union_all over the lot would
    take a counter into its outer ring and lose the hole.
    """

    def overlapping_pair(items):
        for i, a in enumerate(items):
            for j, b in enumerate(items):
                if i < j and shapely.overlaps(a, b):
                    return i, j
        return None

    polygons = list(polygons)
    while True:
        pair = overlapping_pair(polygons)
        if pair is None:
            return polygons
        i, j = pair
        polygons[i] = shapely.union(polygons[i], polygons[j])
        polygons.pop(j)
