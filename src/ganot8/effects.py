"""Pixel effects used by redactions, with a cache.

Blur and pixelate have to read the pixels they are covering, which plain
drawing does not. They are also far too slow to redo on every frame, so each
computed patch is cached and only rebuilt when its inputs change.

Both have a **floor** on strength. A lightly blurred or coarsely-but-not-coarsely-
enough pixelated region is still readable, or recoverable by someone who knows
the font - so a redaction that the user believes is safe must not be
expressible as a cosmetic smudge (docs/SPEC.md section 6).
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageFilter

from .geometry import Rect
from .surfaces import CairoImage, pil_to_surface

#: Styles a Redact annotation can be drawn in.
STYLE_SOLID = "solid"
STYLE_BLUR = "blur"
STYLE_PIXELATE = "pixelate"
REDACT_STYLES = (STYLE_SOLID, STYLE_BLUR, STYLE_PIXELATE)

#: Strength is a 1-100 slider. These are the hard floors it cannot go below.
MIN_PIXELATE_BLOCK = 8
MIN_BLUR_RADIUS = 6.0

DEFAULT_STRENGTH = 50.0


def pixelate_block(rect: Rect, strength: float) -> int:
    """Block size in image pixels, scaled to the region and floored at 8."""
    span = min(abs(rect.width), abs(rect.height))
    scaled = span * (_clamp_strength(strength) / 100.0) * 0.6
    return max(MIN_PIXELATE_BLOCK, int(round(scaled)))


def blur_radius(rect: Rect, strength: float) -> float:
    """Gaussian radius in image pixels, scaled to the region and floored at 6."""
    span = min(abs(rect.width), abs(rect.height))
    scaled = span * (_clamp_strength(strength) / 100.0) * 0.5
    return max(MIN_BLUR_RADIUS, scaled)


def _clamp_strength(strength: float) -> float:
    return max(1.0, min(100.0, float(strength)))


def pixelate(patch: Image.Image, block: int) -> Image.Image:
    """Average ``patch`` into blocks of ``block`` pixels.

    The downscale uses BOX (a true average, so the detail is genuinely gone)
    and the upscale NEAREST (so the blocks stay hard-edged rather than being
    smoothed back into something suggestive of the original).
    """
    width, height = patch.size
    if width <= 0 or height <= 0:
        return patch
    block = max(1, int(block))
    small = (max(1, width // block), max(1, height // block))
    return patch.resize(small, Image.Resampling.BOX).resize(
        (width, height), Image.Resampling.NEAREST
    )


def blur(patch: Image.Image, radius: float) -> Image.Image:
    """Gaussian-blur ``patch``.

    Only the region itself is blurred, so nothing from outside it bleeds in -
    and nothing inside bleeds out.
    """
    return patch.filter(ImageFilter.GaussianBlur(radius=max(0.1, float(radius))))


@dataclass(frozen=True)
class EffectKey:
    """Everything a cached patch depends on."""

    style: str
    strength: float
    x: int
    y: int
    width: int
    height: int

    @classmethod
    def build(cls, style: str, strength: float, rect: Rect) -> "EffectKey":
        rect = rect.normalized()
        return cls(
            style=style,
            strength=round(_clamp_strength(strength), 2),
            x=int(rect.x),
            y=int(rect.y),
            width=max(0, int(round(rect.width))),
            height=max(0, int(round(rect.height))),
        )


class EffectCache:
    """Caches rendered patches for one document's source image.

    Owned by the Document and dropped whenever the source pixels change, which
    is the only thing that can invalidate every entry at once.
    """

    def __init__(self, limit: int = 64):
        self._entries: dict[EffectKey, CairoImage] = {}
        self._limit = limit

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def patch(self, source: Image.Image, style: str, strength: float, rect: Rect):
        """The effect patch for ``rect``, computing it only if not already held."""
        key = EffectKey.build(style, strength, rect)
        if key.width <= 0 or key.height <= 0:
            return None

        cached = self._entries.get(key)
        if cached is not None:
            return cached

        box = _clamp_box(key, source.size)
        if box is None:
            return None

        patch = source.crop(box)
        if style == STYLE_PIXELATE:
            patch = pixelate(patch, pixelate_block(rect, strength))
        elif style == STYLE_BLUR:
            patch = blur(patch, blur_radius(rect, strength))
        else:
            return None

        if len(self._entries) >= self._limit:
            # Plain FIFO: these are cheap to rebuild and the working set is a
            # handful of redactions, so an LRU would be ceremony for nothing.
            self._entries.pop(next(iter(self._entries)))

        surface = pil_to_surface(patch)
        self._entries[key] = surface
        return surface


def _clamp_box(key: EffectKey, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """Clip a requested region to the image, since a rect may hang off the edge."""
    width, height = size
    left = max(0, min(key.x, width))
    top = max(0, min(key.y, height))
    right = max(left, min(key.x + key.width, width))
    bottom = max(top, min(key.y + key.height, height))
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)
