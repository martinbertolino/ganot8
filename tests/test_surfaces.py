"""The PIL <-> Cairo bridge. Everything drawn relies on this being exact."""

from __future__ import annotations

import cairo
import pytest
from PIL import Image

from ganot8.surfaces import new_surface, pil_to_surface, surface_to_pil


def test_round_trip_preserves_opaque_pixels(rgba_image):
    back = surface_to_pil(pil_to_surface(rgba_image).surface)
    assert back.size == rgba_image.size
    assert back.getpixel((0, 0)) == (255, 0, 0, 255)
    assert back.getpixel((5, 3)) == (255, 255, 255, 255)


def test_round_trip_zeroes_fully_transparent_pixels(rgba_image):
    back = surface_to_pil(pil_to_surface(rgba_image).surface)
    # Premultiplying by alpha=0 discards colour, irreversibly and correctly.
    assert back.getpixel((1, 0)) == (0, 0, 0, 0)


def test_round_trip_semi_transparent_within_one_level(rgba_image):
    back = surface_to_pil(pil_to_surface(rgba_image).surface)
    r, g, b, a = back.getpixel((2, 0))
    assert a == 128
    # 8-bit premultiplication is lossy by up to one level per channel.
    for got, expected in zip((r, g, b), (200, 100, 50)):
        assert abs(got - expected) <= 1


def test_surface_is_argb32_with_queried_stride(rgba_image):
    cairo_image = pil_to_surface(rgba_image)
    surface = cairo_image.surface
    assert surface.get_format() == cairo.FORMAT_ARGB32
    assert surface.get_width() == 6
    assert surface.get_height() == 4
    expected = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, 6)
    assert surface.get_stride() == expected


def test_buffer_is_retained_so_surface_stays_valid(rgba_image):
    """create_for_data does not copy; the wrapper must keep the buffer alive."""
    import gc

    cairo_image = pil_to_surface(rgba_image)
    surface = cairo_image.surface
    gc.collect()
    # Reading pixels after a collection would be a use-after-free if the
    # backing bytearray had been released.
    assert surface_to_pil(surface).getpixel((0, 0)) == (255, 0, 0, 255)


def test_converts_non_rgba_input():
    grey = Image.new("L", (3, 3), 128)
    assert pil_to_surface(grey).size == (3, 3)


def test_rejects_empty_image():
    with pytest.raises(ValueError):
        pil_to_surface(Image.new("RGBA", (0, 0)))


def test_new_surface_starts_transparent():
    image = surface_to_pil(new_surface(2, 2))
    assert set(image.convert("RGBA").get_flattened_data()) == {(0, 0, 0, 0)}


def test_drawing_into_a_surface_round_trips():
    surface = new_surface(4, 4)
    cr = cairo.Context(surface)
    cr.set_source_rgb(1, 0, 0)
    cr.paint()
    image = surface_to_pil(surface)
    assert image.getpixel((2, 2)) == (255, 0, 0, 255)
