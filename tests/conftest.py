"""Shared fixtures.

The GSettings backend is forced to memory for the whole suite, before anything
imports Gio. Without it the tests write to the real dconf database: they create
windows, those windows save their state on close, and a later test then reads
back whatever an earlier one happened to leave. That made results depend on run
order and on the developer's own settings - and quietly changed those settings
as a side effect of running the tests.
"""

from __future__ import annotations

import os

os.environ["GSETTINGS_BACKEND"] = "memory"

import pytest  # noqa: E402
from PIL import Image  # noqa: E402


@pytest.fixture
def rgba_image() -> Image.Image:
    """A small image with opaque, transparent and semi-transparent pixels."""
    image = Image.new("RGBA", (6, 4), (30, 144, 255, 255))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 0))
    image.putpixel((2, 0), (200, 100, 50, 128))
    image.putpixel((5, 3), (255, 255, 255, 255))
    return image
