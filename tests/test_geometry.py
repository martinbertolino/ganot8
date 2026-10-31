"""Geometry primitives and hit-testing maths."""

from __future__ import annotations

import math

import pytest

from ganot8.geometry import (
    Handle,
    Point,
    Rect,
    constrain_to_axis,
    distance_to_segment,
    rect_handle_positions,
    resize_rect,
)


def test_rect_from_points_normalises_any_corner_order():
    a = Rect.from_points(Point(10, 20), Point(30, 50))
    b = Rect.from_points(Point(30, 50), Point(10, 20))
    assert a == b == Rect(10, 20, 20, 30)


def test_rect_edges():
    rect = Rect(10, 20, 30, 40)
    assert (rect.left, rect.top, rect.right, rect.bottom) == (10, 20, 40, 60)
    assert rect.center == Point(25, 40)


def test_normalized_fixes_negative_extent():
    assert Rect(30, 50, -20, -30).normalized() == Rect(10, 20, 20, 30)


def test_contains_includes_the_boundary():
    rect = Rect(0, 0, 10, 10)
    assert rect.contains(Point(0, 0))
    assert rect.contains(Point(10, 10))
    assert not rect.contains(Point(10.1, 5))


def test_contains_rect_and_intersects():
    outer = Rect(0, 0, 100, 100)
    assert outer.contains_rect(Rect(10, 10, 10, 10))
    assert not outer.contains_rect(Rect(90, 90, 20, 20))
    assert outer.intersects(Rect(90, 90, 20, 20))
    assert not outer.intersects(Rect(200, 200, 10, 10))


def test_union_covers_both():
    assert Rect(0, 0, 10, 10).union(Rect(20, 20, 10, 10)) == Rect(0, 0, 30, 30)


def test_inflate_then_deflate_round_trips():
    rect = Rect(10, 10, 20, 20)
    assert rect.inflated(5).inflated(-5) == rect


def test_handle_positions_are_at_corners_and_midpoints():
    positions = rect_handle_positions(Rect(0, 0, 100, 50))
    assert positions[Handle.NW] == Point(0, 0)
    assert positions[Handle.SE] == Point(100, 50)
    assert positions[Handle.N] == Point(50, 0)
    assert positions[Handle.W] == Point(0, 25)
    assert len(positions) == 8


@pytest.mark.parametrize(
    "handle,point,expected",
    [
        (Handle.NW, Point(10, 10), Rect(10, 10, 90, 90)),
        (Handle.SE, Point(50, 50), Rect(0, 0, 50, 50)),
        (Handle.N, Point(999, 25), Rect(0, 25, 100, 75)),
        (Handle.W, Point(40, 999), Rect(40, 0, 60, 100)),
    ],
)
def test_resize_moves_only_the_dragged_edges(handle, point, expected):
    assert resize_rect(Rect(0, 0, 100, 100), handle, point) == expected


def test_resize_past_the_opposite_edge_flips_rather_than_inverting():
    """Dragging the left edge beyond the right must stay a valid rect."""
    result = resize_rect(Rect(0, 0, 100, 100), Handle.NW, Point(150, 150))
    assert result.width > 0 and result.height > 0
    assert result == Rect(100, 100, 50, 50)


def test_resize_with_square_constraint_keeps_corners_square():
    result = resize_rect(Rect(0, 0, 100, 100), Handle.SE, Point(60, 20), square=True)
    assert result.width == result.height == 60


def test_distance_to_segment_perpendicular_and_beyond_ends():
    start, end = Point(0, 0), Point(10, 0)
    assert distance_to_segment(Point(5, 3), start, end) == pytest.approx(3)
    # Past an endpoint it is the distance to that endpoint, not the infinite line.
    assert distance_to_segment(Point(-4, 3), start, end) == pytest.approx(5)


def test_distance_to_degenerate_segment():
    assert distance_to_segment(Point(3, 4), Point(0, 0), Point(0, 0)) == pytest.approx(5)


def test_constrain_to_axis_snaps_to_45_degrees():
    snapped = constrain_to_axis(Point(0, 0), Point(10, 1))
    assert snapped.y == pytest.approx(0, abs=1e-9)
    assert snapped.x == pytest.approx(math.hypot(10, 1))

    diagonal = constrain_to_axis(Point(0, 0), Point(10, 9))
    assert diagonal.x == pytest.approx(diagonal.y)


def test_point_distance():
    assert Point(0, 0).distance_to(Point(3, 4)) == pytest.approx(5)


def test_rect_serialisation_round_trip():
    rect = Rect(1.5, 2.5, 3.5, 4.5)
    assert Rect.from_list(rect.to_list()) == rect
