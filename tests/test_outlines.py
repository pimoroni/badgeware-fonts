"""Curves to polylines, and the shapely clean-up that follows."""

import pytest
import shapely
from helpers import cff_font

from badgeware_fonts import glyphs, outlines


def test_a_curve_is_cut_finely_enough_for_the_grid_it_lands_on():
    """One step per output unit of control polygon: finer than a coordinate can express."""
    line = ((0, 0), (100, 0))
    assert outlines.steps_for(line, scale=1) == 100
    assert outlines.steps_for(line, scale=10) == 10
    # A curve shorter than one step still gets one, or the segment goes missing.
    assert outlines.steps_for(line, scale=1000) == 1


def test_flattening_starts_after_the_start_and_ends_on_the_end():
    """The start is already on the contour; the end has to be, or the next segment jumps."""
    made = outlines.flatten_conic((0, 0), (50, 100), (100, 0), steps=4)
    assert len(made) == 4
    assert made[-1] == (100, 0)
    assert (0, 0) not in made


def test_a_quadratic_bows_towards_its_control_point():
    """Halfway along, a quadratic sits half the way to the control point, not on it."""
    made = outlines.flatten_conic((0, 0), (0, 100), (100, 100), steps=2)
    assert made[0] == pytest.approx((25, 75))
    assert made[1] == pytest.approx((100, 100))


def test_a_cubic_bows_towards_both_of_its_control_points():
    """TrueType is quadratic throughout, so this is the path a CFF face in an .otf takes."""
    made = outlines.flatten_cubic((0, 0), (0, 100), (100, 100), (100, 0), steps=2)
    # Symmetric controls put the midpoint above the chord and level with neither end.
    assert made[0] == pytest.approx((50, 75))
    assert made[1] == pytest.approx((100, 0))


def test_a_straight_cubic_stays_straight():
    """Controls evenly spaced along the chord, so every step lands on it."""
    made = outlines.flatten_cubic((0, 0), (30, 0), (60, 0), (90, 0), steps=3)
    assert [x for x, _y in made] == pytest.approx([30, 60, 90])
    assert [y for _x, y in made] == pytest.approx([0, 0, 0])


def test_overlapping_contours_become_one_ring():
    """A renderer that fills what it is given shows the seam, so overlaps are unioned."""
    left = [(0, 0), (60, 0), (60, 60), (0, 60)]
    right = [(40, 0), (100, 0), (100, 60), (40, 60)]
    made = outlines.clean_contours([left, right], tolerance=0)
    assert len(made) == 1
    assert shapely.Polygon(made[0]).area == pytest.approx(100 * 60)


def test_a_counter_stays_a_hole_of_its_own():
    """The inner ring of an O sits inside the outer, untouching, and both are contours."""
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    inner = [(30, 30), (70, 30), (70, 70), (30, 70)]
    made = outlines.clean_contours([outer, inner], tolerance=0)
    assert len(made) == 2
    assert sorted(round(shapely.Polygon(ring).area) for ring in made) == [1600, 10000]


def test_a_triangle_survives_as_the_smallest_ring_there_is():
    made = outlines.clean_contours([[(0, 0), (100, 0), (50, 100)]], tolerance=0)
    assert len(made) == 1
    assert shapely.Polygon(made[0]).area == pytest.approx(5000)


def test_a_contour_of_two_points_encloses_nothing_and_is_dropped():
    assert outlines.clean_contours([[(0, 0), (100, 0)]], tolerance=0) == []


def test_a_tolerance_takes_out_the_points_it_can_spare():
    """Flattening leaves points a straight edge does not need."""
    edge = [(x, 0) for x in range(0, 101, 5)] + [(100, 100), (0, 100)]
    detailed = outlines.clean_contours([edge], tolerance=0)
    simplified = outlines.clean_contours([edge], tolerance=2)
    assert len(simplified[0]) < len(detailed[0])
    assert shapely.Polygon(simplified[0]).area == pytest.approx(10000, rel=0.01)


def test_a_cff_face_decomposes_through_the_cubic_flattener(tmp_path):
    """The only outlines FreeType hands back as cubics, so the only way to reach that half."""
    face = glyphs.open_face(cff_font(tmp_path), 1000)
    face.load_char("H", outlines.LOAD_FLAGS)
    made = outlines.outline_contours(face, scale=10)
    assert len(made) == 1
    # Cut into many points, starting where the pen moved to and closing back on it.
    assert len(made[0]) > 20
    assert made[0][0] == (100, 0)
    assert made[0][-1] == (100, 0)
    # Through the far end of the curve, bowing up towards the control points on the way.
    assert (500, 0) in made[0]
    assert max(y for _x, y in made[0]) > 200
