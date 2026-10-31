"""Bridge between PIL images and Cairo surfaces.

Cairo's ``FORMAT_ARGB32`` stores **alpha-premultiplied** pixels in native byte
order: B, G, R, A on a little-endian machine. PIL stores straight (non
premultiplied) R, G, B, A. Both conversions below are done with Pillow channel
operations so that numpy is not a dependency.
"""

from __future__ import annotations

import sys

import cairo
from PIL import Image, ImageChops

#: Cairo uses native 32-bit word order, so the byte order depends on the CPU.
_LITTLE_ENDIAN = sys.byteorder == "little"


class CairoImage:
    """A Cairo surface together with the buffer that backs it.

    ``cairo.ImageSurface.create_for_data`` does **not** copy the buffer it is
    given, so something must keep that buffer alive for as long as the surface
    is used. Losing the reference means the surface reads freed memory.
    """

    __slots__ = ("surface", "width", "height", "_buffer")

    def __init__(self, surface: cairo.ImageSurface, buffer: bytearray, width: int, height: int):
        self.surface = surface
        self.width = width
        self.height = height
        self._buffer = buffer

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


def pil_to_surface(image: Image.Image) -> CairoImage:
    """Convert an RGBA PIL image into a premultiplied ARGB32 Cairo surface."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError(f"cannot convert a {width}x{height} image")

    red, green, blue, alpha = image.split()
    # ImageChops.multiply computes (a * b) / 255, which is exactly the
    # premultiplication Cairo expects.
    red_p = ImageChops.multiply(red, alpha)
    green_p = ImageChops.multiply(green, alpha)
    blue_p = ImageChops.multiply(blue, alpha)

    if _LITTLE_ENDIAN:
        packed = Image.merge("RGBA", (blue_p, green_p, red_p, alpha))
    else:
        packed = Image.merge("RGBA", (alpha, red_p, green_p, blue_p))

    raw = packed.tobytes()
    row_bytes = width * 4
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, width)

    if stride == row_bytes:
        buffer = bytearray(raw)
    else:
        # Cairo may want rows padded to a wider alignment than width * 4.
        buffer = bytearray(stride * height)
        for y in range(height):
            buffer[y * stride : y * stride + row_bytes] = raw[y * row_bytes : (y + 1) * row_bytes]

    surface = cairo.ImageSurface.create_for_data(
        buffer, cairo.FORMAT_ARGB32, width, height, stride
    )
    return CairoImage(surface, buffer, width, height)


def surface_to_pil(surface: cairo.ImageSurface) -> Image.Image:
    """Convert an ARGB32 Cairo surface back into a straight-alpha RGBA image."""
    if surface.get_format() != cairo.FORMAT_ARGB32:
        raise ValueError("expected a FORMAT_ARGB32 surface")
    if not _LITTLE_ENDIAN:
        raise NotImplementedError(
            "big-endian hosts need a manual un-premultiply; Pillow has no 'aRGB' raw mode"
        )

    surface.flush()
    width, height = surface.get_width(), surface.get_height()
    data = bytes(surface.get_data())
    # "BGRa" is Pillow's premultiplied raw mode: it un-premultiplies on read.
    return Image.frombuffer("RGBA", (width, height), data, "raw", "BGRa", surface.get_stride(), 1)


def new_surface(width: int, height: int) -> cairo.ImageSurface:
    """Create a transparent ARGB32 surface of the given pixel size."""
    return cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
