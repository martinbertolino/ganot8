"""The five core annotation kinds from docs/SPEC.md section 4."""

from __future__ import annotations

import cairo
import pytest

from ganot8.annotations import (
    Arrow,
    Highlight,
    Redact,
    TextLabel,
    Underline,
    annotation_from_dict,
)
from ganot8.geometry import Handle, Point, Rect
from ganot8.surfaces import new_surface, surface_to_pil


def render(annotation, size=(60, 40), background=None):
    surface = new_surface(*size)
    cr = cairo.Context(surface)
    if background is not None:
        cr.set_source_rgb(*background)
        cr.paint()
    annotation.draw(cr)
    return surface_to_pil(surface)


# -- highlight -----------------------------------------------------------


def test_highlight_defaults_to_translucent_yellow():
    highlight = Highlight()
    assert highlight.opacity < 1.0
    red, green, blue, _ = highlight.color
    assert red > 0.9 and green > 0.8 and blue < 0.4


def test_highlight_leaves_dark_content_readable():
    """MULTIPLY means dark text stays dark instead of being washed out."""
    highlight = Highlight(rect=Rect(0, 0, 60, 40))
    over_white = render(highlight, background=(1, 1, 1))
    over_black = render(highlight, background=(0, 0, 0))
    assert over_white.getpixel((30, 20))[:3] != (255, 255, 255)
    # Black text under a highlight must remain black.
    assert over_black.getpixel((30, 20))[:3] == (0, 0, 0)


def test_highlight_is_clickable_anywhere_inside():
    highlight = Highlight(rect=Rect(0, 0, 50, 50))
    assert highlight.hit_test(Point(25, 25), 1)


# -- redact --------------------------------------------------------------


def test_redact_is_fully_opaque_over_any_content():
    redact = Redact(rect=Rect(0, 0, 60, 40))
    for background in ((1, 1, 1), (0, 0, 0), (0.2, 0.7, 0.3)):
        image = render(redact, background=background)
        assert image.getpixel((30, 20)) == (0, 0, 0, 255)


def test_redact_ignores_opacity_entirely():
    """A see-through redaction leaks; opacity must not weaken it."""
    redact = Redact(rect=Rect(0, 0, 60, 40), opacity=0.1)
    image = render(redact, background=(1, 1, 1))
    assert image.getpixel((30, 20)) == (0, 0, 0, 255)


def test_redact_colour_alpha_is_also_ignored():
    redact = Redact(rect=Rect(0, 0, 60, 40), color=(0.0, 0.0, 0.0, 0.05))
    image = render(redact, background=(1, 1, 1))
    assert image.getpixel((30, 20)) == (0, 0, 0, 255)


def test_redact_does_not_expose_an_opacity_control():
    from ganot8.annotations import STYLE_OPACITY

    assert STYLE_OPACITY not in Redact.style_properties


def test_redact_keeps_its_style_field_across_a_round_trip():
    redact = Redact(rect=Rect(1, 2, 3, 4), style="solid")
    assert annotation_from_dict(redact.to_dict()).style == "solid"


# -- underline -----------------------------------------------------------


def test_underline_draws_along_the_segment():
    underline = Underline(start=Point(5, 20), end=Point(55, 20), stroke_width=3)
    image = render(underline)
    assert image.getpixel((30, 20))[3] > 0
    assert image.getpixel((30, 5))[3] == 0


def test_wavy_underline_covers_more_vertical_space():
    straight = Underline(start=Point(5, 20), end=Point(55, 20), stroke_width=3)
    wavy = Underline(start=Point(5, 20), end=Point(55, 20), stroke_width=3, wavy=True)
    assert wavy.bounds().height > straight.bounds().height


def test_underline_hit_test_follows_the_line():
    underline = Underline(start=Point(0, 10), end=Point(100, 10), stroke_width=2)
    assert underline.hit_test(Point(50, 10), 2)
    assert not underline.hit_test(Point(50, 40), 2)


def test_underline_handles_are_its_endpoints():
    underline = Underline(start=Point(1, 2), end=Point(9, 2))
    handles = underline.handles()
    assert handles[Handle.START] == Point(1, 2)
    assert handles[Handle.END] == Point(9, 2)


def test_moving_a_line_moves_both_ends():
    underline = Underline(start=Point(0, 0), end=Point(10, 0))
    underline.move(5, 5)
    assert underline.start == Point(5, 5)
    assert underline.end == Point(15, 5)


def test_dragging_an_endpoint_moves_only_that_end():
    underline = Underline(start=Point(0, 0), end=Point(10, 0))
    underline.set_handle(Handle.END, Point(30, 4))
    assert underline.start == Point(0, 0)
    assert underline.end == Point(30, 4)


def test_underline_round_trip_keeps_wavy():
    underline = Underline(start=Point(0, 1), end=Point(2, 3), wavy=True)
    restored = annotation_from_dict(underline.to_dict())
    assert restored.wavy is True
    assert restored.start == Point(0, 1)


# -- arrow ---------------------------------------------------------------


def test_arrow_draws_a_head_at_the_end():
    arrow = Arrow(start=Point(5, 20), end=Point(55, 20), stroke_width=3)
    image = render(arrow)
    # The head is wider than the shaft, so it covers more rows near the tip.
    head_column = sum(1 for y in range(40) if image.getpixel((50, y))[3] > 0)
    shaft_column = sum(1 for y in range(40) if image.getpixel((15, y))[3] > 0)
    assert head_column > shaft_column


def test_arrow_head_scales_with_stroke_width():
    thin = Arrow(start=Point(0, 0), end=Point(50, 0), stroke_width=2)
    thick = Arrow(start=Point(0, 0), end=Point(50, 0), stroke_width=10)
    assert thick.head_length > thin.head_length


def test_arrow_bounds_accommodate_the_head():
    arrow = Arrow(start=Point(0, 50), end=Point(100, 50), stroke_width=8)
    assert arrow.bounds().height > 8


def test_very_short_arrow_still_draws_a_head():
    arrow = Arrow(start=Point(30, 20), end=Point(34, 20), stroke_width=3)
    assert render(arrow).getpixel((32, 20))[3] > 0


def test_zero_length_line_draws_nothing():
    arrow = Arrow(start=Point(20, 20), end=Point(20, 20), stroke_width=3)
    assert set(render(arrow).get_flattened_data()) == {(0, 0, 0, 0)}


# -- text ----------------------------------------------------------------


def test_text_measures_its_rendered_size():
    label = TextLabel(text="Hello", font="Sans 18")
    width, height = label.text_size()
    assert width > 0 and height > 0


def test_longer_text_is_wider():
    short = TextLabel(text="Hi", font="Sans 18")
    long = TextLabel(text="Hello there, world", font="Sans 18")
    assert long.text_size()[0] > short.text_size()[0]


def test_larger_font_renders_larger():
    small = TextLabel(text="Hello", font="Sans 10")
    large = TextLabel(text="Hello", font="Sans 30")
    assert large.text_size()[1] > small.text_size()[1]


def test_wrap_width_makes_text_taller_and_narrower():
    unwrapped = TextLabel(text="one two three four five six seven", font="Sans 14")
    wrapped = TextLabel(
        text="one two three four five six seven", font="Sans 14", wrap_width=60
    )
    assert wrapped.text_size()[0] <= 60
    assert wrapped.text_size()[1] > unwrapped.text_size()[1]


def test_empty_text_draws_nothing_but_stays_clickable():
    label = TextLabel(text="", anchor=Point(10, 10))
    assert set(render(label).get_flattened_data()) == {(0, 0, 0, 0)}
    assert label.bounds().width > 0
    assert label.hit_test(Point(11, 11), 1)


def test_text_draws_pixels():
    label = TextLabel(text="X", font="Sans 24", anchor=Point(2, 2), color=(1, 0, 0, 1))
    image = render(label, size=(60, 60))
    assert any(image.getpixel((x, y))[3] > 0 for x in range(40) for y in range(40))


def test_background_plate_enlarges_the_bounds():
    plain = TextLabel(text="Hello", font="Sans 14")
    plated = TextLabel(text="Hello", font="Sans 14", background=True, padding=10)
    assert plated.bounds().width > plain.bounds().width
    assert plated.bounds().height > plain.bounds().height


def test_background_plate_is_drawn():
    label = TextLabel(
        text="Hi",
        font="Sans 14",
        anchor=Point(20, 20),
        background=True,
        background_color=(0, 0, 1, 1),
        padding=6,
    )
    image = render(label, size=(80, 60))
    # Just inside the plate, away from the glyphs.
    assert image.getpixel((16, 20))[2] > 100


def test_text_handles_adjust_the_wrap_width():
    label = TextLabel(text="some words here", font="Sans 14", anchor=Point(10, 10))
    label.set_handle(Handle.E, Point(90, 10))
    assert label.wrap_width == pytest.approx(80)


def test_dragging_the_west_handle_moves_the_anchor():
    label = TextLabel(text="words", font="Sans 14", anchor=Point(50, 10), wrap_width=100)
    label.set_handle(Handle.W, Point(30, 10))
    assert label.anchor.x == pytest.approx(30)
    assert label.wrap_width == pytest.approx(120)


def test_text_round_trip_preserves_everything():
    label = TextLabel(
        text="multi\nline",
        font="Serif Bold 22",
        anchor=Point(3, 4),
        wrap_width=120,
        background=True,
        padding=9,
    )
    restored = annotation_from_dict(label.to_dict())
    assert restored.text == "multi\nline"
    assert restored.font == "Serif Bold 22"
    assert restored.anchor == Point(3, 4)
    assert restored.wrap_width == pytest.approx(120)
    assert restored.background is True
    assert restored.padding == pytest.approx(9)


def test_text_round_trip_with_no_wrap_width():
    label = TextLabel(text="x", wrap_width=None)
    assert annotation_from_dict(label.to_dict()).wrap_width is None


# -- redaction styles ----------------------------------------------------


def test_redact_defaults_to_solid():
    from ganot8.effects import STYLE_SOLID

    assert Redact().style == STYLE_SOLID


def test_blur_redaction_falls_back_to_a_solid_block_without_pixels():
    """The fallback must cover, not skip.

    draw() is called with no RenderContext in plenty of places - a bare
    annotation preview, a caller that has no document. Drawing nothing there
    would silently expose exactly what the user asked to hide, so an
    unavailable patch degrades to the safest possible output.
    """
    from ganot8.effects import STYLE_BLUR

    redaction = Redact(rect=Rect(0, 0, 60, 40), style=STYLE_BLUR)
    image = render(redaction, background=(1, 1, 1))
    assert image.getpixel((30, 20)) == (0, 0, 0, 255)


def test_blur_redaction_falls_back_when_the_cache_is_missing():
    from ganot8.effects import STYLE_PIXELATE

    class HalfContext:
        source = object()
        cache = None

    redaction = Redact(rect=Rect(0, 0, 60, 40), style=STYLE_PIXELATE)
    surface = new_surface(60, 40)
    cr = cairo.Context(surface)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    redaction.draw(cr, HalfContext())
    assert surface_to_pil(surface).getpixel((30, 20)) == (0, 0, 0, 255)


def test_redact_round_trip_keeps_style_and_strength():
    from ganot8.effects import STYLE_PIXELATE

    redaction = Redact(rect=Rect(1, 2, 3, 4), style=STYLE_PIXELATE, strength=77.0)
    restored = annotation_from_dict(redaction.to_dict())
    assert restored.style == STYLE_PIXELATE
    assert restored.strength == pytest.approx(77.0)


def test_an_unknown_redaction_style_degrades_to_solid():
    """A project from a newer build must not produce a see-through redaction."""
    from ganot8.effects import STYLE_SOLID

    restored = annotation_from_dict(
        {"kind": "redact", "rect": [0, 0, 10, 10], "style": "hologram"}
    )
    assert restored.style == STYLE_SOLID


def test_redaction_style_controls_which_rows_apply():
    from ganot8.annotations import STYLE_COLOR, STYLE_STRENGTH
    from ganot8.effects import STYLE_BLUR

    solid = Redact(rect=Rect(0, 0, 10, 10))
    assert STYLE_COLOR in solid.visible_style_properties()
    assert STYLE_STRENGTH not in solid.visible_style_properties()

    blurred = Redact(rect=Rect(0, 0, 10, 10), style=STYLE_BLUR)
    assert STYLE_STRENGTH in blurred.visible_style_properties()
    assert STYLE_COLOR not in blurred.visible_style_properties()
