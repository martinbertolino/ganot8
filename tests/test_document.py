"""The document model."""

from __future__ import annotations

from PIL import Image

from ganot8.document import Document
from ganot8.imageio.loader import LoadedImage


def make_document(tmp_path=None, image=None, path=None) -> Document:
    image = image or Image.new("RGBA", (10, 6), (0, 0, 0, 255))
    return Document(LoadedImage(image=image, path=path))


def test_exposes_size():
    document = make_document()
    assert document.size == (10, 6)
    assert (document.width, document.height) == (10, 6)


def test_cairo_surface_is_cached():
    document = make_document()
    assert document.cairo_image is document.cairo_image


def test_replace_source_invalidates_the_cache():
    document = make_document()
    first = document.cairo_image
    document.replace_source(Image.new("RGBA", (4, 4), (255, 255, 255, 255)))
    assert document.cairo_image is not first
    assert document.size == (4, 4)


def test_replace_source_converts_to_rgba():
    document = make_document()
    document.replace_source(Image.new("L", (3, 3), 200))
    assert document.source.mode == "RGBA"


def test_display_name_falls_back_to_untitled(tmp_path):
    assert make_document().display_name == "Untitled"
    assert make_document(path=tmp_path / "pic.png").display_name == "pic.png"


def test_is_untitled():
    assert make_document().is_untitled
    assert not make_document(path="/tmp/x.png").is_untitled


def test_changed_signal_fires_on_mark_dirty():
    document = make_document()
    seen = []
    document.connect("changed", lambda *_: seen.append(True))
    assert not document.dirty
    document.mark_dirty()
    assert document.dirty and seen == [True]
    document.mark_clean()
    assert not document.dirty


def test_no_redactions_on_a_fresh_document():
    assert not make_document().has_redactions
