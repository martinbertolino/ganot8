"""Burning redactions into the source pixels (docs/SPEC.md section 6.4)."""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8.annotations import Box, Redact
from ganot8.document import Document
from ganot8.geometry import Rect
from ganot8.imageio import project
from ganot8.imageio.loader import LoadedImage


def secret_image(size=(60, 40)) -> Image.Image:
    """A noisy image, so a surviving region is obvious."""
    image = Image.new("RGBA", size, (255, 255, 255, 255))
    for x in range(size[0]):
        for y in range(size[1]):
            image.putpixel((x, y), ((x * 7) % 256, (y * 11) % 256, (x * y) % 256, 255))
    return image


@pytest.fixture
def document() -> Document:
    doc = Document(LoadedImage(image=secret_image()))
    doc.annotations.append(Redact(rect=Rect(0, 0, 30, 20)))
    return doc


def colours_in(image, box) -> set:
    return set(image.crop(box).convert("RGB").get_flattened_data())


def test_burn_in_destroys_the_covered_pixels(document):
    before = colours_in(document.source, (0, 0, 30, 20))
    assert len(before) > 1, "precondition: the area should be varied"

    assert document.burn_in_redactions()
    assert colours_in(document.source, (0, 0, 30, 20)) == {(0, 0, 0)}


def test_burn_in_leaves_the_rest_of_the_image_alone(document):
    untouched_before = colours_in(document.source, (35, 25, 60, 40))
    document.burn_in_redactions()
    assert colours_in(document.source, (35, 25, 60, 40)) == untouched_before


def test_burn_in_removes_the_redaction_annotations(document):
    document.annotations.append(Box(rect=Rect(40, 20, 10, 10)))
    document.burn_in_redactions()
    assert [a.kind for a in document.annotations] == ["box"]
    assert not document.has_redactions


def test_burn_in_is_one_undo_step(document):
    document.burn_in_redactions()
    assert document.history.depth == 1
    assert document.history.undo_label == "Burn In Redactions"


def test_undo_restores_both_pixels_and_annotations(document):
    before = colours_in(document.source, (0, 0, 30, 20))
    document.burn_in_redactions()
    document.history.undo()

    assert colours_in(document.source, (0, 0, 30, 20)) == before
    assert document.has_redactions


def test_undo_restores_redactions_at_their_original_z_position(document):
    lower = Box(rect=Rect(40, 0, 10, 10))
    document.annotations.insert(0, lower)
    document.burn_in_redactions()
    document.history.undo()
    assert [a.kind for a in document.annotations] == ["box", "redact"]


def test_burn_in_with_nothing_to_burn_is_a_no_op():
    document = Document(LoadedImage(image=secret_image()))
    document.annotations.append(Box(rect=Rect(0, 0, 10, 10)))
    assert not document.burn_in_redactions()
    assert not document.history.can_undo


def test_a_project_saved_after_burn_in_does_not_contain_the_hidden_pixels(
    document, tmp_path
):
    """The reason burn-in exists: the project file keeps the original otherwise."""
    plain = project.save(document, tmp_path / "before.ganot8")
    assert len(colours_in(project.load(plain).image, (0, 0, 30, 20))) > 1

    document.burn_in_redactions()
    burnt = project.save(document, tmp_path / "after.ganot8")
    assert colours_in(project.load(burnt).image, (0, 0, 30, 20)) == {(0, 0, 0)}


def test_burn_in_respects_the_redaction_colour(document):
    document.annotations[0].color = (1.0, 0.0, 0.0, 1.0)
    document.burn_in_redactions()
    assert colours_in(document.source, (0, 0, 30, 20)) == {(255, 0, 0)}


def test_burnt_source_carries_no_metadata(document):
    document.burn_in_redactions()
    assert document.source.info == {}


def test_burn_in_marks_the_document_dirty(document):
    document.mark_clean()
    document.burn_in_redactions()
    assert document.dirty
