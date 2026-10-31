"""Read images into straight-alpha RGBA PIL images.

Pillow is the primary decoder. GdkPixbuf is a fallback: it is already in the
process because GTK is loaded, and it covers formats Pillow does not, most
notably SVG (via librsvg) and JPEG XL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

log = logging.getLogger(__name__)

#: Pillow refuses very large images as a decompression-bomb guard. Raise the
#: limit rather than remove it: a 20000x20000 screenshot is not a thing.
Image.MAX_IMAGE_PIXELS = 512_000_000


def _register_optional_plugins() -> None:
    """Register format plugins that ship as separate packages, if present."""
    try:
        import pillow_heif
    except ImportError:
        log.debug("pillow-heif not installed; HEIC/HEIF will fall back to GdkPixbuf")
    else:
        pillow_heif.register_heif_opener()
        log.debug("pillow-heif %s registered", pillow_heif.__version__)


_register_optional_plugins()


class UnsupportedImageError(Exception):
    """Raised when neither Pillow nor GdkPixbuf can decode a file."""


@dataclass(frozen=True)
class LoadedImage:
    """An image decoded into RGBA, plus how it got there."""

    image: Image.Image
    path: Path | None = None
    format: str | None = None
    loader: str = "pillow"
    frame_count: int = 1
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    @property
    def is_animated(self) -> bool:
        return self.frame_count > 1


def load(path: str | Path) -> LoadedImage:
    """Decode ``path`` into an RGBA image, trying Pillow then GdkPixbuf."""
    path = Path(path)
    if not path.exists():
        raise UnsupportedImageError(f"{path.name}: file does not exist")
    if path.is_dir():
        raise UnsupportedImageError(f"{path.name}: is a directory")

    try:
        return _load_with_pillow(path)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as pillow_error:
        log.info("Pillow could not decode %s (%s); trying GdkPixbuf", path.name, pillow_error)
        try:
            return _load_with_pixbuf(path)
        except Exception as pixbuf_error:
            raise UnsupportedImageError(
                f"{path.name}: unsupported or damaged image\n"
                f"  Pillow: {pillow_error}\n"
                f"  GdkPixbuf: {pixbuf_error}"
            ) from pixbuf_error


def _load_with_pillow(path: Path) -> LoadedImage:
    warnings: list[str] = []
    with Image.open(path) as opened:
        image_format = opened.format
        frame_count = int(getattr(opened, "n_frames", 1))
        if frame_count > 1:
            warnings.append(
                f"{image_format or 'This image'} has {frame_count} frames; "
                "only the first frame is annotated."
            )
            opened.seek(0)
        # Apply EXIF orientation so the image appears the way a viewer shows it
        # and annotation coordinates line up with what the user sees.
        oriented = ImageOps.exif_transpose(opened)
        if oriented is None:
            oriented = opened
        rgba = oriented.convert("RGBA")
        rgba.load()

    # A fresh image carries no EXIF/ICC in .info, which is what the export path
    # relies on to avoid leaking source metadata.
    rgba.info.clear()
    return LoadedImage(
        image=rgba,
        path=path,
        format=image_format,
        loader="pillow",
        frame_count=frame_count,
        warnings=tuple(warnings),
    )


def _load_with_pixbuf(path: Path) -> LoadedImage:
    from .. import gi_init  # noqa: F401  (pins GI versions before the import below)
    from gi.repository import GdkPixbuf

    pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
    image = pixbuf_to_pil(pixbuf)
    return LoadedImage(image=image, path=path, format=None, loader="gdkpixbuf")


def pixbuf_to_pil(pixbuf) -> Image.Image:
    """Copy a GdkPixbuf's pixels into an RGBA PIL image.

    ``rowstride`` is not necessarily ``width * channels`` - GdkPixbuf pads rows
    for alignment - so rows are copied individually when it differs.
    """
    bits = pixbuf.get_bits_per_sample()
    if bits != 8:
        raise ValueError(f"unsupported pixbuf depth: {bits} bits per sample")

    width = pixbuf.get_width()
    height = pixbuf.get_height()
    channels = pixbuf.get_n_channels()
    mode = "RGBA" if pixbuf.get_has_alpha() else "RGB"
    if channels != len(mode):
        raise ValueError(f"pixbuf has {channels} channels but mode {mode}")

    stride = pixbuf.get_rowstride()
    data = pixbuf.get_pixels()
    row_bytes = width * channels

    if stride == row_bytes and len(data) >= row_bytes * height:
        packed = data[: row_bytes * height]
    else:
        buffer = bytearray(row_bytes * height)
        for y in range(height):
            start = y * stride
            chunk = data[start : start + row_bytes]
            # The final row can be short: pixbuf only guarantees
            # stride * (height - 1) + row_bytes bytes of storage.
            buffer[y * row_bytes : y * row_bytes + len(chunk)] = chunk
        packed = bytes(buffer)

    image = Image.frombytes(mode, (width, height), packed)
    return image.convert("RGBA") if mode != "RGBA" else image


def load_from_pixbuf(pixbuf, *, name: str | None = None) -> LoadedImage:
    """Wrap an in-memory pixbuf (clipboard, screenshot portal) as a LoadedImage."""
    return LoadedImage(image=pixbuf_to_pil(pixbuf), path=None, format=name, loader="gdkpixbuf")
