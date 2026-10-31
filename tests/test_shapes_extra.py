"""Ellipse, Freehand and Badge — the phase 5 shape kinds."""

from __future__ import annotations

import cairo
import pytest

from ganot8.annotations import (
    Badge,
    Ellipse,
    Freehand,
    annotation_from_dict,
    next_badge_number,
)
from ganot8.geometry import Handle, Point, Rect
from ganot8.surfaces import new_surface, surface_to_pil


def render(annotation, size=(80, 60)):
    surface = new_surface(*size)
    annotation.draw(cairo.Context(surface))
    return surface_to_pil(surface)


# -- ellipse -------------------------------------------------------------


def test_ellipse_outline_is_drawn_and_the_middle_is_empty():
    ellipse = Ellipse(rect=Rect(10, 10, 60, 40), stroke_width=3, color=(1, 0, 0, 1))
    image = render(ellipse)
    assert image.getpixel((40, 10))[3] > 0    # top of the arc
    assert image.getpixel((40, 30))[3] == 0   # hollow centre


def test_filled_ellipse_fills_its_centre():
    ellipse = Ellipse(rect=Rect(10, 10, 60, 40), filled=True, color=(0, 1, 0, 1))
    assert render(ellipse).getpixel((40, 30)) == (0, 255, 0, 255)


def test_ellipse_does_not_fill_its_corners():
    """An ellipse is not its bounding box - the corners must stay clear."""
    ellipse = Ellipse(rect=Rect(10, 10, 60, 40), filled=True, color=(0, 1, 0, 1))
    assert render(ellipse).getpixel((11, 11))[3] == 0


def test_hollow_ellipse_is_only_clickable_on_its_outline():
    ellipse = Ellipse(rect=Rect(0, 0, 100, 50), stroke_width=2)
    assert ellipse.hit_test(Point(100, 25), 2)     # right edge
    assert not ellipse.hit_test(Point(50, 25), 2)  # centre
    assert not ellipse.hit_test(Point(2, 2), 2)    # corner of the bounding box


def test_filled_ellipse_is_clickable_inside_but_not_at_the_corner():
    ellipse = Ellipse(rect=Rect(0, 0, 100, 50), filled=True)
    assert ellipse.hit_test(Point(50, 25), 2)
    assert not ellipse.hit_test(Point(1, 1), 2)


def test_filled_ellipse_hides_the_line_width_control():
    from ganot8.annotations import STYLE_STROKE_WIDTH

    assert STYLE_STROKE_WIDTH not in Ellipse(filled=True).visible_style_properties()
    assert STYLE_STROKE_WIDTH in Ellipse(filled=False).visible_style_properties()


def test_ellipse_round_trip():
    ellipse = Ellipse(rect=Rect(1, 2, 3, 4), filled=True)
    restored = annotation_from_dict(ellipse.to_dict())
    assert restored.rect == ellipse.rect and restored.filled is True


def test_degenerate_ellipse_draws_nothing():
    assert set(render(Ellipse(rect=Rect(10, 10, 0, 0))).get_flattened_data()) == {(0, 0, 0, 0)}


# -- freehand ------------------------------------------------------------


def test_freehand_draws_along_its_points():
    stroke = Freehand(
        points=[Point(10, 30), Point(40, 30), Point(70, 30)],
        stroke_width=4,
        color=(1, 0, 0, 1),
    )
    image = render(stroke)
    assert image.getpixel((40, 30))[3] > 0
    assert image.getpixel((40, 5))[3] == 0


def test_a_single_point_still_leaves_a_mark():
    """A tap should not silently produce an invisible annotation."""
    stroke = Freehand(points=[Point(40, 30)], stroke_width=8, color=(1, 0, 0, 1))
    assert render(stroke).getpixel((40, 30))[3] > 0


def test_empty_freehand_draws_nothing():
    assert set(render(Freehand()).get_flattened_data()) == {(0, 0, 0, 0)}
    assert Freehand().bounds() == Rect(0, 0, 0, 0)


def test_freehand_hit_test_follows_the_stroke():
    stroke = Freehand(points=[Point(0, 0), Point(50, 0), Point(50, 50)], stroke_width=2)
    assert stroke.hit_test(Point(25, 0), 2)
    assert stroke.hit_test(Point(50, 25), 2)
    assert not stroke.hit_test(Point(25, 25), 2)  # inside the corner, not on it


def test_freehand_bounds_cover_every_point():
    stroke = Freehand(points=[Point(10, 20), Point(60, 5), Point(30, 70)], stroke_width=2)
    bounds = stroke.bounds()
    assert bounds.left <= 10 and bounds.top <= 5
    assert bounds.right >= 60 and bounds.bottom >= 70


def test_moving_a_freehand_moves_every_point():
    stroke = Freehand(points=[Point(0, 0), Point(10, 10)])
    stroke.move(5, -5)
    assert stroke.points == [Point(5, -5), Point(15, 5)]


def test_freehand_exposes_no_handles():
    """There is no meaningful control point on a hand-drawn stroke."""
    assert Freehand(points=[Point(0, 0), Point(10, 10)]).handles() == {}


def test_freehand_round_trip_preserves_the_path():
    stroke = Freehand(points=[Point(1.5, 2.5), Point(3, 4)])
    assert annotation_from_dict(stroke.to_dict()).points == stroke.points


# -- badge ---------------------------------------------------------------


def test_badge_draws_a_disc():
    badge = Badge(centre=Point(40, 30), number=3, radius=20, color=(1, 0, 0, 1))
    image = render(badge)
    assert image.getpixel((40, 12))[3] > 0    # inside the disc
    assert image.getpixel((2, 2))[3] == 0     # well outside


def test_badge_draws_its_number():
    """The numeral is knocked out in the text colour, so the disc is not plain."""
    badge = Badge(
        centre=Point(40, 30),
        number=8,
        radius=22,
        color=(0, 0, 0, 1),
        text_color=(1, 1, 1, 1),
    )
    image = render(badge)
    centre_area = [
        image.getpixel((x, y))
        for x in range(30, 51)
        for y in range(20, 41)
    ]
    assert any(p[:3] == (255, 255, 255) for p in centre_area), "no numeral drawn"


def test_badge_hit_test_is_circular():
    badge = Badge(centre=Point(50, 50), radius=20)
    assert badge.hit_test(Point(50, 50), 0)
    assert badge.hit_test(Point(69, 50), 0)
    assert not badge.hit_test(Point(66, 66), 0)  # corner of the bounding box


def test_badge_handle_resizes_it():
    badge = Badge(centre=Point(50, 50), radius=20)
    badge.set_handle(Handle.E, Point(90, 50))
    assert badge.radius == pytest.approx(40)


def test_badge_radius_has_a_minimum():
    badge = Badge(centre=Point(50, 50), radius=20)
    badge.set_handle(Handle.E, Point(50, 50))
    assert badge.radius >= 6


def test_numbering_continues_past_the_highest_rather_than_counting():
    """Counting would reuse a number as soon as an earlier badge was deleted."""
    badges = [Badge(number=1), Badge(number=2), Badge(number=3)]
    assert next_badge_number(badges) == 4
    del badges[0]
    assert next_badge_number(badges) == 4


def test_numbering_starts_at_one():
    assert next_badge_number([]) == 1
    assert next_badge_number([Ellipse(rect=Rect(0, 0, 1, 1))]) == 1


def test_badge_round_trip():
    badge = Badge(centre=Point(3, 4), number=12, radius=25.0, font="Serif Bold 20")
    restored = annotation_from_dict(badge.to_dict())
    assert restored.number == 12
    assert restored.radius == pytest.approx(25.0)
    assert restored.font == "Serif Bold 20"
    assert restored.centre == Point(3, 4)
