"""Undo/redo invariants."""

from __future__ import annotations

from PIL import Image

from ganot8.annotations import Box
from ganot8.document import Document
from ganot8.geometry import Rect
from ganot8.history import (
    AddAnnotations,
    History,
    RemoveAnnotations,
    Reorder,
    StateChange,
)
from ganot8.imageio.loader import LoadedImage


def make_document() -> Document:
    return Document(LoadedImage(image=Image.new("RGBA", (100, 100))))


def box(x=0, y=0, size=10) -> Box:
    return Box(rect=Rect(x, y, size, size))


def test_push_executes_the_command():
    document = make_document()
    annotation = box()
    document.history.push(AddAnnotations(document, [annotation]))
    assert document.annotations == [annotation]


def test_undo_then_redo_restores():
    document = make_document()
    annotation = box()
    document.history.push(AddAnnotations(document, [annotation]))
    document.history.undo()
    assert document.annotations == []
    document.history.redo()
    assert document.annotations == [annotation]


def test_n_operations_then_n_undos_restores_the_initial_model():
    """The core invariant from docs/SPEC.md section 11."""
    document = make_document()
    initial = document.annotations_to_list()

    annotations = [box(i * 10) for i in range(5)]
    for annotation in annotations:
        document.history.push(AddAnnotations(document, [annotation]))
    moved = annotations[2]
    before = [moved.state()]
    moved.move(13, 17)
    document.history.push(StateChange(document, [moved], before))
    document.history.push(RemoveAnnotations(document, [annotations[0]]))
    document.history.push(Reorder(document, annotations[4], 0))

    operations = document.history.depth
    assert operations == 8
    for _ in range(operations):
        assert document.history.undo()

    assert document.annotations_to_list() == initial
    assert not document.history.can_undo


def test_redo_branch_is_discarded_by_a_new_command():
    document = make_document()
    first, second = box(0), box(50)
    document.history.push(AddAnnotations(document, [first]))
    document.history.undo()
    assert document.history.can_redo
    document.history.push(AddAnnotations(document, [second]))
    assert not document.history.can_redo
    assert document.annotations == [second]


def test_remove_restores_original_z_order():
    document = make_document()
    annotations = [box(i * 10) for i in range(4)]
    document.annotations.extend(annotations)
    document.history.push(RemoveAnnotations(document, [annotations[1], annotations[2]]))
    assert document.annotations == [annotations[0], annotations[3]]
    document.history.undo()
    assert document.annotations == annotations


def test_state_change_round_trips_geometry_and_style():
    document = make_document()
    annotation = box()
    document.annotations.append(annotation)
    before = [annotation.state()]
    annotation.move(5, 5)
    annotation.stroke_width = 11.0
    document.history.push(StateChange(document, [annotation], before))

    document.history.undo()
    assert annotation.rect == Rect(0, 0, 10, 10)
    assert annotation.stroke_width == 7.0
    document.history.redo()
    assert annotation.rect == Rect(5, 5, 10, 10)
    assert annotation.stroke_width == 11.0


def test_reorder_moves_within_z_order():
    document = make_document()
    annotations = [box(i * 10) for i in range(3)]
    document.annotations.extend(annotations)
    document.history.push(Reorder(document, annotations[0], 2))
    assert document.annotations == [annotations[1], annotations[2], annotations[0]]
    document.history.undo()
    assert document.annotations == annotations


def test_noop_commands_are_not_recorded():
    document = make_document()
    annotation = box()
    document.annotations.append(annotation)
    assert not document.history.push(AddAnnotations(document, []))
    assert not document.history.push(RemoveAnnotations(document, []))
    assert not document.history.push(Reorder(document, annotation, 0))
    assert not document.history.push(StateChange(document, [annotation], [annotation.state()]))
    assert not document.history.can_undo


def test_undo_redo_on_an_empty_stack_is_safe():
    history = History()
    assert not history.undo()
    assert not history.redo()


def test_limit_discards_the_oldest_commands():
    document = make_document()
    history = History(limit=3)
    for index in range(10):
        history.push(AddAnnotations(document, [box(index)]))
    assert history.depth == 3


def test_changed_signal_fires_on_every_transition():
    document = make_document()
    seen = []
    document.history.connect("changed", lambda *_: seen.append(True))
    document.history.push(AddAnnotations(document, [box()]))
    document.history.undo()
    document.history.redo()
    document.history.clear()
    assert len(seen) == 4


def test_drop_redo_leaves_undo_intact():
    """Burning in redactions discards redo without losing earlier undo steps."""
    document = make_document()
    document.history.push(AddAnnotations(document, [box(0)]))
    document.history.push(AddAnnotations(document, [box(50)]))
    document.history.undo()
    assert document.history.can_redo and document.history.depth == 1

    document.history.drop_redo()
    assert not document.history.can_redo
    assert document.history.can_undo


def test_labels_describe_the_pending_operation():
    document = make_document()
    document.history.push(AddAnnotations(document, [box()], label="Add Box"))
    assert document.history.undo_label == "Add Box"
    document.history.undo()
    assert document.history.redo_label == "Add Box"


def test_document_is_marked_dirty():
    document = make_document()
    assert not document.dirty
    document.history.push(AddAnnotations(document, [box()]))
    assert document.dirty
