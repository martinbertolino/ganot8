"""Export flattening, format handling and the privacy invariants."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ganot8.document import Document
from ganot8.imageio import exporter
from ganot8.imageio.loader import LoadedImage


@pytest.fixture
def document(rgba_image, tmp_path) -> Document:
    source = tmp_path / "shot.png"
    rgba_image.save(source, format="PNG")
    return Document(LoadedImage(image=rgba_image, path=source, format="PNG"))


def test_flatten_matches_source_pixels(document, rgba_image):
    flattened = exporter.flatten(document)
    assert flattened.size == rgba_image.size
    assert flattened.getpixel((0, 0)) == (255, 0, 0, 255)
    assert flattened.getpixel((5, 3)) == (255, 255, 255, 255)


def test_flatten_output_has_no_metadata(document):
    assert exporter.flatten(document).info == {}


@pytest.mark.parametrize(
    "name,fmt",
    [
        ("out.png", "PNG"),
        ("out.jpg", "JPEG"),
        ("out.webp", "WEBP"),
        ("out.avif", "AVIF"),
        ("out.gif", "GIF"),
        ("out.tiff", "TIFF"),
        ("out.bmp", "BMP"),
    ],
)
def test_exports_every_format(document, tmp_path, name, fmt):
    target = tmp_path / name
    written = exporter.export(document, target)
    assert written == target and target.stat().st_size > 0
    with Image.open(target) as reopened:
        assert reopened.format == fmt
        assert reopened.size == document.size


def test_export_carries_no_exif_xmp_or_icc(tmp_path, rgba_image):
    """SPEC section 6.2: source metadata must not survive an export."""
    source = tmp_path / "tagged.png"
    rgba_image.save(source, format="PNG", icc_profile=b"not-a-real-profile")
    document = Document(LoadedImage(image=rgba_image, path=source))

    target = exporter.export(document, tmp_path / "clean.png")
    with Image.open(target) as reopened:
        assert "icc_profile" not in reopened.info
        assert "exif" not in reopened.info
        assert "XML:com.adobe.xmp" not in reopened.info
        assert reopened.getexif().items() == {}.items()


def test_default_export_path_never_equals_the_source():
    source = Path("/tmp/holiday.png")
    assert exporter.default_export_path(source) == Path("/tmp/holiday-annotated.png")


def test_default_export_path_avoids_collision_with_source():
    """An already-suffixed source must not be its own export target."""
    source = Path("/tmp/holiday-annotated.png")
    assert exporter.default_export_path(source) != source


def test_default_export_path_for_untitled_document():
    assert exporter.default_export_path(None).name == "Untitled-annotated.png"


def test_format_is_chosen_from_the_extension():
    assert exporter.format_for_path("a.JPEG").name == "JPEG"
    assert exporter.format_for_path("a.webp").name == "WEBP"
    # Unknown extensions fall back to PNG rather than failing.
    assert exporter.format_for_path("a.xyz").name == "PNG"


def test_jpeg_export_mattes_transparency_onto_white(document, tmp_path):
    target = exporter.export(document, tmp_path / "out.jpg")
    with Image.open(target) as reopened:
        assert reopened.mode == "RGB"
        # The fully transparent pixel at (1, 0) becomes white.
        r, g, b = reopened.getpixel((1, 0))
        assert min(r, g, b) > 240


def test_gif_export_keeps_transparency(document, tmp_path):
    target = exporter.export(document, tmp_path / "out.gif")
    with Image.open(target) as reopened:
        assert "transparency" in reopened.info
        assert reopened.convert("RGBA").getpixel((1, 0))[3] == 0


def test_export_creates_missing_parent_directories(document, tmp_path):
    target = tmp_path / "nested" / "deeper" / "out.png"
    assert exporter.export(document, target).exists()
