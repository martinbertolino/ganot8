"""Document-level annotation queries used by the Select tool."""

from __future__ import annotations

from PIL import Image

from ganot8.annotations import Box, annotation_from_dict
from ganot8.document import Document
from ganot8.geometry import Point, Rect
from ganot8.imageio.loader import LoadedImage


def make_document() -> Document:
    return Document(LoadedImage(image=Image.new("RGBA", (200, 200))))


def test_annotation_at_returns_the_topmost():
    """Later in the list is drawn on top, so it must win a hit test."""
    document = make_document()
    lower = Box(rect=Rect(0, 0, 100, 100), filled=True)
    upper = Box(rect=Rect(0, 0, 100, 100), filled=True)
    document.annotations.extend([lower, upper])
    assert document.annotation_at(Point(50, 50), 2) is upper


def test_annotation_at_returns_none_on_empty_space():
    document = make_document()
    document.annotations.append(Box(rect=Rect(0, 0, 10, 10)))
    assert document.annotation_at(Point(150, 150), 2) is None


def test_annotation_at_skips_unselectable_kinds():
    document = make_document()
    document.annotations.append(annotation_from_dict({"kind": "hologram"}))
    assert document.annotation_at(Point(0, 0), 100) is None


def test_annotations_in_requires_full_enclosure():
    document = make_document()
    inside = Box(rect=Rect(20, 20, 20, 20))
    straddling = Box(rect=Rect(90, 90, 40, 40))
    document.annotations.extend([inside, straddling])
    found = document.annotations_in(Rect(0, 0, 100, 100))
    assert found == [inside]


def test_annotations_round_trip_through_lists():
    document = make_document()
    document.annotations.extend([Box(rect=Rect(1, 2, 3, 4)), Box(rect=Rect(5, 6, 7, 8))])
    data = document.annotations_to_list()

    restored = make_document()
    restored.annotations_from_list(data)
    assert restored.annotations_to_list() == data


def test_unknown_kinds_survive_a_document_round_trip():
    document = make_document()
    payload = [{"kind": "hologram", "shimmer": True}]
    document.annotations_from_list(payload)
    assert document.annotations_to_list() == payload


def test_has_redactions_detects_the_kind():
    document = make_document()
    assert not document.has_redactions
    document.annotations_from_list([{"kind": "redact", "rect": [0, 0, 5, 5]}])
    # Not implemented until phase 3, so it loads as unknown and must not
    # masquerade as a real redaction.
    assert not document.has_redactions
