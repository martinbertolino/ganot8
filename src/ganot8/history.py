"""Undo/redo.

Every mutation of a document goes through a :class:`Command`. Geometry and
style edits use :class:`StateChange`, which snapshots annotations before and
after - one command per gesture, not one per motion event, so a drag undoes in
a single step.
"""

from __future__ import annotations

from typing import Any, Sequence

from . import gi_init  # noqa: F401
from gi.repository import GObject

#: Commands kept before the oldest is discarded.
HISTORY_LIMIT = 250


class Command:
    """One reversible change."""

    label: str = "Change"

    def do(self) -> None:
        raise NotImplementedError

    def undo(self) -> None:
        raise NotImplementedError

    def is_noop(self) -> bool:
        """True if pushing this would record nothing worth undoing."""
        return False


class AddAnnotations(Command):
    """Insert annotations at the top of the z-order."""

    def __init__(self, document, annotations: Sequence, label: str = "Add"):
        self.document = document
        self.annotations = list(annotations)
        self.label = label

    def do(self) -> None:
        self.document.annotations.extend(self.annotations)
        self.document.mark_dirty()

    def undo(self) -> None:
        for annotation in self.annotations:
            if annotation in self.document.annotations:
                self.document.annotations.remove(annotation)
        self.document.mark_dirty()

    def is_noop(self) -> bool:
        return not self.annotations


class RemoveAnnotations(Command):
    """Delete annotations, remembering where they were so undo restores order."""

    def __init__(self, document, annotations: Sequence, label: str = "Delete"):
        self.document = document
        self.label = label
        current = document.annotations
        # Sorted by index so re-insertion on undo is stable.
        self.entries = sorted(
            ((current.index(a), a) for a in annotations if a in current),
            key=lambda entry: entry[0],
        )

    def do(self) -> None:
        for _, annotation in reversed(self.entries):
            if annotation in self.document.annotations:
                self.document.annotations.remove(annotation)
        self.document.mark_dirty()

    def undo(self) -> None:
        for index, annotation in self.entries:
            self.document.annotations.insert(index, annotation)
        self.document.mark_dirty()

    def is_noop(self) -> bool:
        return not self.entries


class StateChange(Command):
    """Restore annotation snapshots - the generic move/resize/restyle command."""

    def __init__(
        self,
        document,
        annotations: Sequence,
        before: Sequence[dict[str, Any]],
        after: Sequence[dict[str, Any]] | None = None,
        label: str = "Edit",
    ):
        self.document = document
        self.annotations = list(annotations)
        self.before = [dict(state) for state in before]
        self.after = (
            [dict(state) for state in after]
            if after is not None
            else [a.state() for a in self.annotations]
        )
        self.label = label

    def do(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)

    def _apply(self, states: Sequence[dict[str, Any]]) -> None:
        for annotation, state in zip(self.annotations, states):
            annotation.restore(state)
        self.document.mark_dirty()

    def is_noop(self) -> bool:
        return not self.annotations or self.before == self.after


class Reorder(Command):
    """Move one annotation within the z-order."""

    def __init__(self, document, annotation, new_index: int, label: str = "Reorder"):
        self.document = document
        self.annotation = annotation
        self.old_index = document.annotations.index(annotation)
        self.new_index = max(0, min(len(document.annotations) - 1, new_index))
        self.label = label

    def do(self) -> None:
        self._move(self.old_index, self.new_index)

    def undo(self) -> None:
        self._move(self.new_index, self.old_index)

    def _move(self, source: int, target: int) -> None:
        annotations = self.document.annotations
        annotations.insert(target, annotations.pop(source))
        self.document.mark_dirty()

    def is_noop(self) -> bool:
        return self.old_index == self.new_index


class BurnInRedactions(Command):
    """Composite redactions into the source pixels and drop the annotations.

    After this, saving a project no longer carries the hidden content - which
    is the whole point (docs/SPEC.md section 6.4). Undo restores the previous
    pixels, so the hidden content *does* remain reachable in memory for as long
    as this document is open; the confirmation dialog says so rather than
    implying a stronger guarantee than the code provides.
    """

    label = "Burn In Redactions"

    def __init__(self, document, burnt_image, redactions):
        self.document = document
        self.previous_image = document.source
        self.burnt_image = burnt_image
        self.entries = sorted(
            ((document.annotations.index(a), a) for a in redactions),
            key=lambda entry: entry[0],
        )

    def do(self) -> None:
        for _, annotation in reversed(self.entries):
            if annotation in self.document.annotations:
                self.document.annotations.remove(annotation)
        self.document.replace_source(self.burnt_image)

    def undo(self) -> None:
        for index, annotation in self.entries:
            self.document.annotations.insert(index, annotation)
        self.document.replace_source(self.previous_image)

    def is_noop(self) -> bool:
        return not self.entries


class ReshapeDocument(Command):
    """Replace the source pixels and move every annotation to match.

    Crop and rotate both change the image's shape, so annotations have to be
    carried across or they would end up pointing at the wrong content. The
    annotations are transformed by the caller; this records both ends so the
    whole thing undoes as one step.
    """

    def __init__(self, document, before_image, after_image, annotations, before, after, label):
        self.document = document
        self.before_image = before_image
        self.after_image = after_image
        self.annotations = list(annotations)
        self.before = [dict(state) for state in before]
        self.after = [dict(state) for state in after]
        self.label = label

    def do(self) -> None:
        self._apply(self.after_image, self.after)

    def undo(self) -> None:
        self._apply(self.before_image, self.before)

    def _apply(self, image, states) -> None:
        for annotation, state in zip(self.annotations, states):
            annotation.restore(state)
        self.document.replace_source(image)

    def is_noop(self) -> bool:
        return self.before_image is self.after_image


class History(GObject.Object):
    """A linear undo stack. Doing something new discards the redo branch."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, limit: int = HISTORY_LIMIT):
        super().__init__()
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._limit = limit

    # -- mutation --------------------------------------------------------

    def push(self, command: Command) -> bool:
        """Execute ``command`` and record it. Returns False if it was a no-op."""
        if command.is_noop():
            return False
        command.do()
        self._undo_stack.append(command)
        del self._redo_stack[:]
        if len(self._undo_stack) > self._limit:
            del self._undo_stack[0 : len(self._undo_stack) - self._limit]
        self.emit("changed")
        return True

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        self.emit("changed")
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        command = self._redo_stack.pop()
        command.do()
        self._undo_stack.append(command)
        self.emit("changed")
        return True

    def clear(self) -> None:
        del self._undo_stack[:]
        del self._redo_stack[:]
        self.emit("changed")

    def drop_redo(self) -> None:
        """Discard the redo branch without touching the undo stack.

        Used by irreversible operations such as burning in redactions, where
        redoing past the change would resurrect hidden pixels.
        """
        if self._redo_stack:
            del self._redo_stack[:]
            self.emit("changed")

    # -- state -----------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def undo_label(self) -> str:
        return self._undo_stack[-1].label if self._undo_stack else ""

    @property
    def redo_label(self) -> str:
        return self._redo_stack[-1].label if self._redo_stack else ""

    @property
    def depth(self) -> int:
        return len(self._undo_stack)
