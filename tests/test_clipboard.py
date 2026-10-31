"""Clipboard conversion. The transfer itself needs a display; this does not."""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8 import clipboard


def sample(size=(8, 6)) -> Image.Image:
    image = Image.new("RGBA", size, (255, 0, 0, 255))
    image.putpixel((0, 0), (0, 255, 0, 255))
    image.putpixel((1, 1), (0, 0, 255, 128))
    return image


def test_image_survives_a_texture_round_trip():
    original = sample()
    restored = clipboard.texture_to_pil(clipboard.pil_to_texture(original))
    assert restored.size == original.size
    assert restored.getpixel((0, 0)) == (0, 255, 0, 255)
    assert restored.getpixel((1, 1)) == (0, 0, 255, 128)


def test_round_trip_is_lossless_for_every_pixel():
    """PNG is used precisely so this holds; a lossy hop would corrupt edits."""
    original = sample((32, 24))
    for x in range(32):
        for y in range(24):
            original.putpixel((x, y), ((x * 7) % 256, (y * 11) % 256, (x * y) % 256, 255))
    restored = clipboard.texture_to_pil(clipboard.pil_to_texture(original))
    assert list(restored.get_flattened_data()) == list(original.get_flattened_data())


def test_pasted_images_carry_no_metadata():
    """So an export cannot inherit anything from whatever produced the image."""
    assert clipboard.texture_to_pil(clipboard.pil_to_texture(sample())).info == {}


def test_non_rgba_images_can_be_copied():
    grey = Image.new("L", (4, 4), 128)
    assert clipboard.texture_to_pil(clipboard.pil_to_texture(grey)).size == (4, 4)
