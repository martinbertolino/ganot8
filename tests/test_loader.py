"""Image loading across formats, plus the GdkPixbuf fallback."""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8.imageio.loader import UnsupportedImageError, load, pixbuf_to_pil

FORMATS = [
    ("png", "PNG", {}),
    ("jpg", "JPEG", {}),
    ("gif", "GIF", {}),
    ("webp", "WEBP", {}),
    ("tiff", "TIFF", {}),
    ("bmp", "BMP", {}),
    ("avif", "AVIF", {}),
]


@pytest.mark.parametrize("extension,fmt,options", FORMATS)
def test_loads_common_formats(tmp_path, rgba_image, extension, fmt, options):
    path = tmp_path / f"sample.{extension}"
    source = rgba_image if fmt not in ("JPEG", "BMP") else rgba_image.convert("RGB")
    source.save(path, format=fmt, **options)

    loaded = load(path)
    assert loaded.image.mode == "RGBA"
    assert loaded.image.size == rgba_image.size
    assert loaded.loader == "pillow"
    assert loaded.path == path


def test_avif_actually_decodes(tmp_path, rgba_image):
    """Guards the reason for using the PyPI wheel over Fedora's python3-pillow,
    whose AVIF reader is registered but has no working codec."""
    path = tmp_path / "sample.avif"
    rgba_image.convert("RGB").save(path, format="AVIF")
    assert load(path).image.size == rgba_image.size


def test_animated_gif_loads_first_frame_and_warns(tmp_path):
    frames = [Image.new("RGBA", (4, 4), colour) for colour in ((255, 0, 0, 255), (0, 0, 255, 255))]
    path = tmp_path / "anim.gif"
    frames[0].save(path, format="GIF", save_all=True, append_images=frames[1:], duration=80)

    loaded = load(path)
    assert loaded.frame_count == 2
    assert loaded.is_animated
    assert loaded.warnings and "first frame" in loaded.warnings[0]
    # Red, i.e. frame 0 - GIF quantisation keeps pure red exactly.
    assert loaded.image.getpixel((0, 0))[:3] == (255, 0, 0)


def test_svg_falls_back_to_gdkpixbuf(tmp_path):
    """Pillow cannot read SVG; librsvg via GdkPixbuf can."""
    path = tmp_path / "shape.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="8">'
        '<rect width="12" height="8" fill="#1e90ff"/></svg>'
    )
    loaded = load(path)
    assert loaded.loader == "gdkpixbuf"
    assert loaded.image.size == (12, 8)
    assert loaded.image.getpixel((6, 4)) == (30, 144, 255, 255)


def test_strips_source_metadata_on_load(tmp_path, rgba_image):
    """.info must be empty, because Pillow's savers read icc_profile from it."""
    path = tmp_path / "tagged.png"
    rgba_image.save(path, format="PNG", icc_profile=b"not-a-real-profile")
    assert load(path).image.info == {}


def test_applies_exif_orientation(tmp_path):
    """Orientation 6 means 'rotate 90 CW to display', so W/H swap on load."""
    import struct

    tall = Image.new("RGB", (8, 4), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6
    path = tmp_path / "rotated.jpg"
    tall.save(path, format="JPEG", exif=exif)

    assert load(path).image.size == (4, 8)
    del struct


def test_missing_file_raises():
    with pytest.raises(UnsupportedImageError, match="does not exist"):
        load("/nonexistent/nope.png")


def test_directory_raises(tmp_path):
    with pytest.raises(UnsupportedImageError, match="is a directory"):
        load(tmp_path)


def test_garbage_file_raises_with_both_reasons(tmp_path):
    path = tmp_path / "junk.png"
    path.write_bytes(b"this is not an image")
    with pytest.raises(UnsupportedImageError) as excinfo:
        load(path)
    message = str(excinfo.value)
    assert "Pillow:" in message and "GdkPixbuf:" in message


def test_pixbuf_rowstride_padding_is_honoured():
    """GdkPixbuf pads rows; rowstride is not always width * channels."""
    from ganot8 import gi_init  # noqa: F401
    from gi.repository import GdkPixbuf

    # Width 3 with 3 channels is 9 bytes per row, which GdkPixbuf pads to 12.
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 3, 2)
    pixbuf.fill(0xFF8800FF)
    assert pixbuf.get_rowstride() != pixbuf.get_width() * pixbuf.get_n_channels()

    image = pixbuf_to_pil(pixbuf)
    assert image.size == (3, 2)
    # Padding bytes must not have leaked into the pixel data.
    assert set(image.get_flattened_data()) == {(255, 136, 0, 255)}
