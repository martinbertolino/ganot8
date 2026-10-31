"""Flatten a document and write it to an image file.

Two invariants, both from docs/SPEC.md section 6:

1. Output contains composited pixels only. No annotation data is ever written
   into image metadata, so a redaction cannot be recovered from an export.
2. Source metadata (EXIF, XMP, GPS, ICC) is not carried over. The flattened
   image is built fresh from a Cairo surface, so it starts with empty
   ``.info``, and nothing is passed to ``save()`` that would reintroduce any.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cairo
from PIL import Image

from .. import render
from ..surfaces import new_surface, surface_to_pil

#: White, used wherever transparency has to be discarded.
_MATTE = (255, 255, 255)


@dataclass(frozen=True)
class ExportFormat:
    name: str
    label: str
    extensions: tuple[str, ...]
    mime: str
    keeps_alpha: bool


EXPORT_FORMATS: tuple[ExportFormat, ...] = (
    ExportFormat("PNG", "PNG image", (".png",), "image/png", True),
    ExportFormat("JPEG", "JPEG image", (".jpg", ".jpeg"), "image/jpeg", False),
    ExportFormat("WEBP", "WebP image", (".webp",), "image/webp", True),
    ExportFormat("AVIF", "AVIF image", (".avif",), "image/avif", True),
    ExportFormat("GIF", "GIF image", (".gif",), "image/gif", True),
    ExportFormat("TIFF", "TIFF image", (".tiff", ".tif"), "image/tiff", True),
    ExportFormat("BMP", "BMP image", (".bmp",), "image/bmp", False),
)

_BY_EXTENSION = {ext: fmt for fmt in EXPORT_FORMATS for ext in fmt.extensions}

DEFAULT_FORMAT = EXPORT_FORMATS[0]
DEFAULT_SUFFIX = "-annotated"


def format_for_path(path: str | Path) -> ExportFormat:
    """Pick an export format from a filename's extension, defaulting to PNG."""
    return _BY_EXTENSION.get(Path(path).suffix.lower(), DEFAULT_FORMAT)


def default_export_path(source: Path | None, *, suffix: str = DEFAULT_SUFFIX) -> Path:
    """Suggest ``<stem>-annotated.png`` beside the source.

    Never returns the source path itself: Ctrl+S must not overwrite the original
    (docs/SPEC.md section 1).
    """
    if source is None:
        return Path.home() / f"Untitled{suffix}.png"
    candidate = source.with_name(f"{source.stem}{suffix}.png")
    if candidate.resolve() == source.resolve():
        candidate = source.with_name(f"{source.stem}{suffix}-1.png")
    return candidate


def flatten(document) -> Image.Image:
    """Composite the document into a new RGBA image at full resolution."""
    width, height = document.width, document.height
    surface = new_surface(width, height)
    cr = cairo.Context(surface)
    render.draw_document(cr, document, smooth=False)
    surface.flush()
    flattened = surface_to_pil(surface)
    # Built from raw pixels, so there is nothing inherited to strip - but be
    # explicit, because Pillow's savers read icc_profile straight out of .info.
    flattened.info.clear()
    return flattened


def export(document, path: str | Path, *, jpeg_quality: int = 92) -> Path:
    """Flatten ``document`` and write it to ``path``. Returns the path written."""
    path = Path(path)
    export_format = format_for_path(path)
    image = flatten(document)

    if not export_format.keeps_alpha:
        image = _matte(image)

    options: dict[str, object] = {}
    if export_format.name == "JPEG":
        options["quality"] = int(jpeg_quality)
        options["subsampling"] = 0
        options["optimize"] = True
    elif export_format.name == "WEBP":
        options["quality"] = 95
        options["method"] = 4
    elif export_format.name == "AVIF":
        options["quality"] = 85
    elif export_format.name == "PNG":
        options["optimize"] = True
    elif export_format.name == "GIF":
        image = _to_gif_palette(image)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format=export_format.name, **options)
    return path


def _matte(image: Image.Image) -> Image.Image:
    """Composite onto white and drop the alpha channel."""
    background = Image.new("RGB", image.size, _MATTE)
    background.paste(image, mask=image.getchannel("A"))
    return background


def _to_gif_palette(image: Image.Image) -> Image.Image:
    """Quantise to 256 colours, keeping fully transparent pixels transparent."""
    alpha = image.getchannel("A")
    # Reserve one palette slot for transparency.
    palette_image = _matte(image).quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    transparent_index = 255
    palette_image.paste(transparent_index, mask=alpha.point(lambda a: 255 if a < 128 else 0))
    palette_image.info["transparency"] = transparent_index
    return palette_image
