"""Blur and pixelate: the pixel effects behind non-solid redactions.

The point of these tests is not that the patch looks different - it is that
the content underneath is genuinely unreadable, and cannot be made readable by
dialling the strength down.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from ganot8 import effects
from ganot8.annotations import Redact
from ganot8.document import Document
from ganot8.geometry import Rect
from ganot8.imageio import exporter
from ganot8.imageio.loader import LoadedImage

TEXT_BOX = (0, 0, 360, 48)


def text_image() -> Image.Image:
    """Small dark text on a light field - what a redaction usually covers."""
    image = Image.new("RGBA", (360, 48), (246, 246, 246, 255))
    ImageDraw.Draw(image).text((8, 16), "Password: hunter2-correct-horse", fill=(20, 20, 20))
    return image


def edge_detail(image: Image.Image) -> float:
    """Mean absolute difference between neighbouring pixels.

    A proxy for legibility: glyphs are high-contrast edges, so if the edges are
    gone the text is gone. Colour count is useless for blur, which preserves
    plenty of distinct colours while destroying all structure.
    """
    grey = image.convert("L")
    pixels = grey.load()
    width, height = grey.size
    total = sum(
        abs(pixels[x, y] - pixels[x + 1, y]) for y in range(height) for x in range(width - 1)
    )
    return total / (width * height)


def redacted(style: str, strength: float = effects.DEFAULT_STRENGTH) -> Image.Image:
    document = Document(LoadedImage(image=text_image()))
    document.annotations.append(
        Redact(rect=Rect(0, 0, 360, 48), style=style, strength=strength)
    )
    return exporter.flatten(document)


# -- the floors ----------------------------------------------------------


@pytest.mark.parametrize("strength", [-100, 0, 1, 10, 50])
def test_pixelate_block_never_drops_below_the_floor(strength):
    block = effects.pixelate_block(Rect(0, 0, 360, 48), strength)
    assert block >= effects.MIN_PIXELATE_BLOCK


@pytest.mark.parametrize("strength", [-100, 0, 1, 10, 50])
def test_blur_radius_never_drops_below_the_floor(strength):
    assert effects.blur_radius(Rect(0, 0, 360, 48), strength) >= effects.MIN_BLUR_RADIUS


def test_strength_scales_with_the_region():
    """A floor sized for a text line would barely touch a large area."""
    small = Rect(0, 0, 360, 48)
    large = Rect(0, 0, 800, 600)
    assert effects.pixelate_block(large, 50) > effects.pixelate_block(small, 50)
    assert effects.blur_radius(large, 50) > effects.blur_radius(small, 50)


def test_strength_is_clamped_to_the_slider_range():
    huge = effects.pixelate_block(Rect(0, 0, 360, 48), 10_000)
    at_max = effects.pixelate_block(Rect(0, 0, 360, 48), 100)
    assert huge == at_max


# -- does it actually hide anything? -------------------------------------


def test_text_is_legible_before_redaction():
    """Guards the measure itself: a metric that never sees detail proves nothing."""
    assert edge_detail(text_image()) > 3.0


@pytest.mark.parametrize("style", [effects.STYLE_BLUR, effects.STYLE_PIXELATE])
def test_redaction_destroys_the_text(style):
    assert edge_detail(redacted(style)) < 0.5


@pytest.mark.parametrize("style", [effects.STYLE_BLUR, effects.STYLE_PIXELATE])
def test_even_the_weakest_setting_destroys_the_text(style):
    """The floor exists so a user cannot pick a reassuring but useless value."""
    assert edge_detail(redacted(style, strength=1)) < 0.5


def test_pixelate_collapses_the_colour_range():
    document = Document(LoadedImage(image=_noise()))
    document.annotations.append(
        Redact(rect=Rect(10, 10, 80, 30), style=effects.STYLE_PIXELATE)
    )
    before = _colours(document.source, (10, 10, 90, 40))
    after = _colours(exporter.flatten(document), (10, 10, 90, 40))
    assert after < before / 10


def test_solid_remains_the_most_thorough():
    assert edge_detail(redacted(effects.STYLE_SOLID)) == 0.0


# -- patch construction --------------------------------------------------


def test_pixelate_quantises_to_blocks():
    patch = Image.new("RGB", (32, 32))
    for x in range(32):
        for y in range(32):
            patch.putpixel((x, y), (x * 8 % 256, y * 8 % 256, 0))
    out = effects.pixelate(patch, 8)
    # Within one block every pixel must now be identical.
    assert out.getpixel((0, 0)) == out.getpixel((7, 7))


def test_pixelate_keeps_the_patch_size():
    patch = Image.new("RGB", (37, 23), (10, 20, 30))
    assert effects.pixelate(patch, 8).size == (37, 23)


def test_blur_keeps_the_patch_size():
    patch = Image.new("RGB", (37, 23), (10, 20, 30))
    assert effects.blur(patch, 6).size == (37, 23)


def test_pixelate_handles_a_region_smaller_than_one_block():
    patch = Image.new("RGB", (3, 2), (10, 20, 30))
    assert effects.pixelate(patch, 8).size == (3, 2)


# -- the cache -----------------------------------------------------------


def test_cache_reuses_an_identical_patch():
    cache = effects.EffectCache()
    source = _noise()
    rect = Rect(5, 5, 40, 20)
    first = cache.patch(source, effects.STYLE_BLUR, 50, rect)
    second = cache.patch(source, effects.STYLE_BLUR, 50, rect)
    assert first is second
    assert len(cache) == 1


@pytest.mark.parametrize(
    "style,strength,rect",
    [
        (effects.STYLE_PIXELATE, 50, Rect(5, 5, 40, 20)),
        (effects.STYLE_BLUR, 90, Rect(5, 5, 40, 20)),
        (effects.STYLE_BLUR, 50, Rect(6, 5, 40, 20)),
    ],
)
def test_cache_distinguishes_every_input(style, strength, rect):
    cache = effects.EffectCache()
    source = _noise()
    cache.patch(source, effects.STYLE_BLUR, 50, Rect(5, 5, 40, 20))
    cache.patch(source, style, strength, rect)
    assert len(cache) == 2


def test_cache_is_bounded():
    cache = effects.EffectCache(limit=4)
    source = _noise()
    for index in range(10):
        cache.patch(source, effects.STYLE_BLUR, 50, Rect(index, 0, 20, 10))
    assert len(cache) <= 4


def test_cache_is_dropped_when_the_source_changes():
    """Every cached patch was cut from pixels that no longer exist."""
    document = Document(LoadedImage(image=_noise()))
    document.effect_cache.patch(document.source, effects.STYLE_BLUR, 50, Rect(0, 0, 20, 10))
    assert len(document.effect_cache) == 1
    document.replace_source(_noise())
    assert len(document.effect_cache) == 0


def test_region_outside_the_image_yields_no_patch():
    cache = effects.EffectCache()
    assert cache.patch(_noise(), effects.STYLE_BLUR, 50, Rect(500, 500, 20, 20)) is None


def test_region_hanging_off_the_edge_is_clipped_not_rejected():
    cache = effects.EffectCache()
    assert cache.patch(_noise(), effects.STYLE_BLUR, 50, Rect(100, 40, 60, 60)) is not None


def test_empty_region_yields_no_patch():
    cache = effects.EffectCache()
    assert cache.patch(_noise(), effects.STYLE_BLUR, 50, Rect(10, 10, 0, 0)) is None


def test_solid_style_is_not_cached():
    """Solid needs no patch, so asking for one must not create an entry."""
    cache = effects.EffectCache()
    assert cache.patch(_noise(), effects.STYLE_SOLID, 50, Rect(0, 0, 20, 10)) is None
    assert len(cache) == 0


# -- helpers -------------------------------------------------------------


def _noise(size=(120, 60)) -> Image.Image:
    image = Image.new("RGBA", size)
    for x in range(size[0]):
        for y in range(size[1]):
            image.putpixel((x, y), ((x * 7) % 256, (y * 13) % 256, (x * y) % 256, 255))
    return image


def _colours(image: Image.Image, box) -> int:
    return len(set(image.crop(box).convert("RGB").get_flattened_data()))
