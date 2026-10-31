"""The annotation interface, serialisation and forward compatibility."""

from __future__ import annotations

import cairo
import pytest

from ganot8.annotations import (
    Box,
    UnknownAnnotation,
    annotation_from_dict,
    registered_kinds,
)
from ganot8.geometry import Handle, Point, Rect
from ganot8.surfaces import new_surface, surface_to_pil


def test_box_is_registered():
    assert "box" in registered_kinds()


def test_bounds_include_the_stroke():
    box = Box(rect=Rect(10, 10, 20, 20), stroke_width=4)
    bounds = box.bounds()
    assert bounds.left < 10 and bounds.right > 30


def test_move_translates_geometry():
    box = Box(rect=Rect(10, 10, 20, 20))
    box.move(5, -3)
    assert box.rect == Rect(15, 7, 20, 20)


def test_set_handle_resizes():
    box = Box(rect=Rect(0, 0, 100, 100))
    box.set_handle(Handle.SE, Point(50, 40))
    assert box.rect == Rect(0, 0, 50, 40)


def test_handles_are_the_eight_rect_handles():
    assert len(Box(rect=Rect(0, 0, 10, 10)).handles()) == 8


def test_hollow_box_is_only_clickable_on_its_outline():
    box = Box(rect=Rect(0, 0, 100, 100), stroke_width=2, filled=False)
    assert box.hit_test(Point(0, 50), tolerance=2)      # on the left edge
    assert not box.hit_test(Point(50, 50), tolerance=2)  # empty middle
    assert not box.hit_test(Point(200, 200), tolerance=2)


def test_filled_box_is_clickable_anywhere_inside():
    box = Box(rect=Rect(0, 0, 100, 100), filled=True)
    assert box.hit_test(Point(50, 50), tolerance=2)


def test_hit_tolerance_widens_the_target():
    box = Box(rect=Rect(0, 0, 100, 100), stroke_width=1, filled=False)
    assert not box.hit_test(Point(-5, 50), tolerance=1)
    assert box.hit_test(Point(-5, 50), tolerance=6)


def test_to_dict_round_trip_preserves_everything():
    box = Box(
        rect=Rect(1, 2, 3, 4),
        color=(0.1, 0.2, 0.3, 0.4),
        stroke_width=7.5,
        opacity=0.5,
        filled=True,
    )
    clone = annotation_from_dict(box.to_dict())
    assert isinstance(clone, Box)
    assert clone.rect == box.rect
    assert clone.color == box.color
    assert clone.stroke_width == box.stroke_width
    assert clone.opacity == box.opacity
    assert clone.filled is True


def test_clone_is_independent():
    box = Box(rect=Rect(0, 0, 10, 10))
    clone = box.clone()
    clone.move(5, 5)
    assert box.rect == Rect(0, 0, 10, 10)


def test_restore_mutates_in_place_so_references_stay_valid():
    """Undo must not swap the object out: selection holds a reference to it."""
    box = Box(rect=Rect(0, 0, 10, 10))
    reference = box
    snapshot = box.state()
    box.move(100, 100)
    box.restore(snapshot)
    assert reference is box
    assert box.rect == Rect(0, 0, 10, 10)


def test_unknown_kind_is_preserved_verbatim():
    """A project written by a newer build must survive a load/save cycle."""
    payload = {"kind": "hologram", "rect": [1, 2, 3, 4], "shimmer": True, "nested": {"a": 1}}
    annotation = annotation_from_dict(payload)
    assert isinstance(annotation, UnknownAnnotation)
    assert annotation.to_dict() == payload


def test_unknown_annotations_are_not_selectable_or_drawn():
    annotation = annotation_from_dict({"kind": "hologram"})
    assert not annotation.selectable
    assert not annotation.hit_test(Point(0, 0), 100)
    surface = new_surface(4, 4)
    annotation.draw(cairo.Context(surface))
    assert set(surface_to_pil(surface).get_flattened_data()) == {(0, 0, 0, 0)}


def test_missing_kind_is_treated_as_unknown():
    assert isinstance(annotation_from_dict({"rect": [0, 0, 1, 1]}), UnknownAnnotation)


def test_box_is_filled_by_default():
    assert Box().filled is True


def test_hollow_box_draws_pixels():
    surface = new_surface(20, 20)
    cr = cairo.Context(surface)
    Box(rect=Rect(5, 5, 10, 10), color=(1, 0, 0, 1), stroke_width=2, filled=False).draw(cr)
    image = surface_to_pil(surface)
    assert image.getpixel((5, 5))[3] > 0     # on the outline
    assert image.getpixel((10, 10))[3] == 0  # hollow middle


def test_filled_box_fills():
    surface = new_surface(20, 20)
    cr = cairo.Context(surface)
    Box(rect=Rect(5, 5, 10, 10), color=(0, 1, 0, 1), filled=True).draw(cr)
    assert surface_to_pil(surface).getpixel((10, 10)) == (0, 255, 0, 255)


def test_opacity_multiplies_colour_alpha():
    surface = new_surface(20, 20)
    cr = cairo.Context(surface)
    Box(rect=Rect(0, 0, 20, 20), color=(1, 0, 0, 1), opacity=0.5, filled=True).draw(cr)
    assert surface_to_pil(surface).getpixel((10, 10))[3] == pytest.approx(128, abs=2)


def test_empty_rect_draws_nothing():
    surface = new_surface(10, 10)
    Box(rect=Rect(5, 5, 0, 0)).draw(cairo.Context(surface))
    assert set(surface_to_pil(surface).get_flattened_data()) == {(0, 0, 0, 0)}


def test_filled_box_hides_the_line_width_control():
    """draw() fills or strokes, never both, so width is inert while filled."""
    from ganot8.annotations import STYLE_STROKE_WIDTH

    assert STYLE_STROKE_WIDTH not in Box(filled=True).visible_style_properties()
    assert STYLE_STROKE_WIDTH in Box(filled=False).visible_style_properties()


def test_visible_style_properties_defaults_to_the_declared_set():
    from ganot8.annotations import Arrow

    arrow = Arrow()
    assert arrow.visible_style_properties() == arrow.style_properties


def test_default_line_width_is_thick_enough_to_read_on_a_screenshot():
    """A hairline disappears once a screenshot is scaled down for sharing."""
    from ganot8.annotations import Annotation

    assert Annotation().stroke_width == 7.0
    assert Box().stroke_width == 7.0


def test_arrow_head_scales_with_the_default_width():
    """head_scale stays 4x, so the head keeps pace with a thicker line."""
    from ganot8.annotations import Arrow

    assert Arrow().head_length == 28.0
