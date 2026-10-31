"""Shared fixtures. These tests are headless: no display is needed."""

from __future__ import annotations

import pytest
from PIL import Image


@pytest.fixture
def rgba_image() -> Image.Image:
    """A small image with opaque, transparent and semi-transparent pixels."""
    image = Image.new("RGBA", (6, 4), (30, 144, 255, 255))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 0))
    image.putpixel((2, 0), (200, 100, 50, 128))
    image.putpixel((5, 3), (255, 255, 255, 255))
    return image
