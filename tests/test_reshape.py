"""Crop and rotate.

The property that matters is not that the image changes size - it is that
annotations stay on the content they were placed over. A redaction that slides
off the thing it was hiding is worse than no redaction at all.
"""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8.annotations import Badge, Box, Redact, TextLabel, annotation_from_dict
from ganot8.document import Document
from ganot8.geometry import Point, Rect
from ganot8.imageio.loader import LoadedImage

MARKER = (255, 0, 0, 255)


def marked_image(size=(100, 60), marker=(80, 10)) -> Image.Image:
    image = Image.new("RGBA", size, (255, 255, 255, 255))
    image.putpixel(marker, MARKER)
    return image


def document_with_badge_on_marker(size=(100, 60), marker=(80, 10)) -> Document:
    document = Document(LoadedImage(image=marked_image(size, marker)))
    # Pixel centres, so the point is unambiguously inside that pixel.
    document.annotations.append(
        Badge(centre=Point(marker[0] + 0.5, marker[1] + 0.5), radius=4)
    )
    return document


def pixel_under(document: Document, annotation) -> tuple:
    centre = annotation.centre
    return document.source.getpixel((int(centre.x), int(centre.y)))


# -- rotation ------------------------------------------------------------


@pytest.mark.parametrize("degrees,expected_size", [(90, (60, 100)), (180, (100, 60)), (270, (60, 100))])
def test_rotation_swaps_the_dimensions_as_expected(degrees, expected_size):
    document = document_with_badge_on_marker()
    assert document.rotate_by(degrees)
    assert document.size == expected_size


@pytest.mark.parametrize("degrees", [90, 180, 270])
def test_annotations_stay_on_their_content_through_a_rotation(degrees):
    document = document_with_badge_on_marker()
    document.rotate_by(degrees)
    assert pixel_under(document, document.annotations[0]) == MARKER


def test_four_quarter_turns_return_to_the_start():
    document = document_with_badge_on_marker()
    original = document.annotations[0].centre
    for _ in range(4):
        document.rotate_by(90)
    assert document.size == (100, 60)
    assert document.annotations[0].centre == original


def test_rotating_left_then_right_is_a_round_trip():
    document = document_with_badge_on_marker()
    original = document.annotations[0].centre
    document.rotate_by(90)
    document.rotate_by(-90)
    assert document.size == (100, 60)
    assert document.annotations[0].centre == original


def test_rotation_is_one_undo_step():
    document = document_with_badge_on_marker()
    document.rotate_by(90)
    assert document.history.depth == 1
    assert document.history.undo_label == "Rotate Right"


def test_undoing_a_rotation_restores_pixels_and_geometry():
    document = document_with_badge_on_marker()
    before = document.annotations[0].centre
    document.rotate_by(90)
    document.history.undo()
    assert document.size == (100, 60)
    assert document.annotations[0].centre == before
    assert pixel_under(document, document.annotations[0]) == MARKER


@pytest.mark.parametrize("degrees", [0, 360, 45, 1])
def test_rotation_only_accepts_quarter_turns(degrees):
    document = document_with_badge_on_marker()
    assert not document.rotate_by(degrees)
    assert not document.history.can_undo


def test_rotation_moves_every_kind_of_annotation():
    document = Document(LoadedImage(image=marked_image()))
    document.annotations.extend(
        [
            Box(rect=Rect(10, 10, 20, 20)),
            Redact(rect=Rect(40, 20, 15, 10)),
            TextLabel(text="x", anchor=Point(5, 5)),
            Badge(centre=Point(70, 30)),
        ]
    )
    before = [a.to_dict() for a in document.annotations]
    document.rotate_by(90)
    assert [a.to_dict() for a in document.annotations] != before, "nothing moved"
    document.history.undo()
    assert [a.to_dict() for a in document.annotations] == before


def test_rotation_clears_the_effect_cache():
    """Cached blur patches were cut from pixels that have now moved."""
    from ganot8.effects import STYLE_BLUR

    document = Document(LoadedImage(image=marked_image()))
    document.effect_cache.patch(document.source, STYLE_BLUR, 50, Rect(0, 0, 20, 20))
    assert len(document.effect_cache) == 1
    document.rotate_by(90)
    assert len(document.effect_cache) == 0


# -- cropping ------------------------------------------------------------


def test_crop_resizes_the_image():
    document = document_with_badge_on_marker()
    assert document.crop_to(Rect(20, 5, 60, 40))
    assert document.size == (60, 40)


def test_annotations_stay_on_their_content_through_a_crop():
    document = document_with_badge_on_marker()
    document.crop_to(Rect(50, 0, 50, 40))
    assert pixel_under(document, document.annotations[0]) == MARKER


def test_crop_translates_every_annotation():
    document = Document(LoadedImage(image=marked_image()))
    document.annotations.append(Box(rect=Rect(30, 20, 10, 10)))
    document.crop_to(Rect(20, 10, 60, 40))
    assert document.annotations[0].rect == Rect(10, 10, 10, 10)


def test_crop_is_one_undo_step_and_restores_everything():
    document = document_with_badge_on_marker()
    before = document.annotations[0].centre
    document.crop_to(Rect(50, 0, 50, 40))
    assert document.history.depth == 1

    document.history.undo()
    assert document.size == (100, 60)
    assert document.annotations[0].centre == before


def test_cropping_to_the_whole_image_does_nothing():
    document = document_with_badge_on_marker()
    assert not document.crop_to(Rect(0, 0, 100, 60))
    assert not document.history.can_undo


def test_crop_is_clamped_to_the_image():
    """A drag can start or end outside the image; that must not fail."""
    document = document_with_badge_on_marker()
    assert document.crop_to(Rect(-40, -40, 120, 80))
    assert document.size == (80, 40)


@pytest.mark.parametrize("rect", [Rect(10, 10, 0, 0), Rect(200, 200, 50, 50), Rect(5, 5, 0.2, 0.2)])
def test_a_degenerate_crop_is_refused(rect):
    document = document_with_badge_on_marker()
    assert not document.crop_to(rect)
    assert document.size == (100, 60)


def test_crop_accepts_a_rect_dragged_backwards():
    document = document_with_badge_on_marker()
    assert document.crop_to(Rect(80, 50, -60, -40))
    assert document.size == (60, 40)


def test_crop_clears_the_effect_cache():
    from ganot8.effects import STYLE_PIXELATE

    document = Document(LoadedImage(image=marked_image()))
    document.effect_cache.patch(document.source, STYLE_PIXELATE, 50, Rect(0, 0, 20, 20))
    document.crop_to(Rect(10, 10, 50, 30))
    assert len(document.effect_cache) == 0


def test_unknown_annotation_kinds_survive_a_reshape():
    """They cannot be moved, but they must not break the operation either."""
    document = Document(LoadedImage(image=marked_image()))
    document.annotations.append(annotation_from_dict({"kind": "hologram", "shimmer": True}))
    assert document.crop_to(Rect(10, 10, 50, 30))
    assert document.annotations[0].to_dict() == {"kind": "hologram", "shimmer": True}


# -- interaction with the rest ------------------------------------------


def test_crop_then_export_produces_the_cropped_size(tmp_path):
    from ganot8.imageio import exporter

    document = document_with_badge_on_marker()
    document.crop_to(Rect(20, 5, 60, 40))
    written = exporter.export(document, tmp_path / "out.png")
    with Image.open(written) as image:
        assert image.size == (60, 40)


def test_crop_then_save_project_round_trips(tmp_path):
    document = document_with_badge_on_marker()
    # A region that keeps the marker: the right edge is exclusive, so a crop
    # ending at x=80 would cut the pixel at x=80 out.
    document.crop_to(Rect(50, 0, 50, 40))
    path = document.save_project(tmp_path / "cropped.ganot8")

    reopened = Document.from_project(path)
    assert reopened.size == (50, 40)
    assert pixel_under(reopened, reopened.annotations[0]) == MARKER


def test_an_annotation_outside_the_crop_is_kept_not_deleted():
    """It is off-image rather than gone, so undoing the crop brings it back."""
    document = document_with_badge_on_marker()
    document.crop_to(Rect(0, 0, 40, 40))
    assert len(document.annotations) == 1
    assert document.annotations[0].centre.x > document.width

    document.history.undo()
    assert document.annotations[0].centre == Point(80.5, 10.5)
