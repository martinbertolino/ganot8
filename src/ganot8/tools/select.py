"""The Select tool: pick, move, resize, marquee."""

from __future__ import annotations

from enum import Enum, auto
from typing import ClassVar

import cairo

from .. import gi_init  # noqa: F401
from gi.repository import Gdk

from ..geometry import HANDLE_CURSORS, Handle, Point, Rect
from ..history import StateChange
from .base import Tool, register

#: Minimum drag, in image pixels, before a press counts as a move rather than
#: a click. Scaled by zoom so it is a constant distance on screen.
_DRAG_THRESHOLD_PX = 3.0


class _Mode(Enum):
    IDLE = auto()
    MOVING = auto()
    RESIZING = auto()
    MARQUEE = auto()


@register
class SelectTool(Tool):
    """Default tool: manipulates existing annotations, never creates one."""

    name: ClassVar[str] = "select"
    label: ClassVar[str] = "Select"
    icon_name: ClassVar[str] = "pointer-primary-click-symbolic"
    accelerator: ClassVar[str] = "s"
    tooltip: ClassVar[str] = "Select, move and resize annotations (S)"
    cursor: ClassVar[str] = "default"

    def __init__(self, canvas):
        super().__init__(canvas)
        self._mode = _Mode.IDLE
        self._origin: Point | None = None
        self._last: Point | None = None
        self._handle: Handle | None = None
        self._subjects: list = []
        self._before: list[dict] = []
        self._marquee: Rect | None = None
        self._moved = False

    # -- lifecycle -------------------------------------------------------

    def deactivate(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._mode = _Mode.IDLE
        self._origin = self._last = None
        self._handle = None
        self._subjects = []
        self._before = []
        self._marquee = None
        self._moved = False

    # -- pointer ---------------------------------------------------------

    def on_drag_begin(self, point: Point, state) -> None:
        document = self.document
        if document is None:
            return
        self._origin = self._last = point
        self._moved = False
        extend = bool(state & Gdk.ModifierType.SHIFT_MASK)

        handle = self._handle_at(point)
        if handle is not None and len(self.canvas.selection) == 1:
            self._mode = _Mode.RESIZING
            self._handle = handle
            self._subjects = list(self.canvas.selection)
            self._before = [a.state() for a in self._subjects]
            return

        hit = document.annotation_at(point, self.canvas.hit_tolerance)
        if hit is None:
            self._mode = _Mode.MARQUEE
            self._marquee = Rect(point.x, point.y, 0, 0)
            if not extend:
                self.canvas.set_selection([])
            return

        if extend:
            self.canvas.toggle_selected(hit)
        elif hit not in self.canvas.selection:
            self.canvas.set_selection([hit])

        self._mode = _Mode.MOVING
        self._subjects = list(self.canvas.selection)
        self._before = [a.state() for a in self._subjects]

    def on_drag_update(self, point: Point, state) -> None:
        if self._origin is None:
            return
        if not self._moved and self._origin.distance_to(point) * self.canvas.zoom < _DRAG_THRESHOLD_PX:
            return
        self._moved = True
        constrain = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if self._mode is _Mode.MOVING and self._last is not None:
            dx, dy = point.x - self._last.x, point.y - self._last.y
            for annotation in self._subjects:
                annotation.move(dx, dy)
            self._last = point
            self._notify()
        elif self._mode is _Mode.RESIZING and self._handle is not None:
            for annotation in self._subjects:
                annotation.set_handle(self._handle, point, constrain=constrain)
            self._last = point
            self._notify()
        elif self._mode is _Mode.MARQUEE:
            self._marquee = Rect.from_points(self._origin, point)
            self.canvas.queue_draw()

    def on_drag_end(self, point: Point, state) -> None:
        document = self.document
        if document is None:
            self._reset()
            return

        if self._mode is _Mode.MARQUEE:
            if self._moved and self._marquee is not None:
                found = document.annotations_in(self._marquee)
                if state & Gdk.ModifierType.SHIFT_MASK:
                    found = list(self.canvas.selection) + [
                        a for a in found if a not in self.canvas.selection
                    ]
                self.canvas.set_selection(found)
        elif self._mode in (_Mode.MOVING, _Mode.RESIZING) and self._moved:
            label = "Move" if self._mode is _Mode.MOVING else "Resize"
            document.history.push(
                StateChange(document, self._subjects, self._before, label=label)
            )
        self._reset()
        self.canvas.queue_draw()

    def cursor_for(self, point: Point, state) -> str | None:
        document = self.document
        if document is None:
            return self.cursor
        handle = self._handle_at(point)
        if handle is not None and len(self.canvas.selection) == 1:
            return HANDLE_CURSORS.get(handle, "default")
        if document.annotation_at(point, self.canvas.hit_tolerance) is not None:
            return "move"
        return "default"

    # -- keyboard --------------------------------------------------------

    def on_key(self, keyval: int, state) -> bool:
        nudge = {
            Gdk.KEY_Left: (-1, 0),
            Gdk.KEY_Right: (1, 0),
            Gdk.KEY_Up: (0, -1),
            Gdk.KEY_Down: (0, 1),
        }.get(keyval)
        if nudge is None or not self.canvas.selection:
            return False

        step = 10 if state & Gdk.ModifierType.SHIFT_MASK else 1
        dx, dy = nudge[0] * step, nudge[1] * step
        document = self.document
        subjects = list(self.canvas.selection)
        before = [a.state() for a in subjects]
        for annotation in subjects:
            annotation.move(dx, dy)
        document.history.push(StateChange(document, subjects, before, label="Nudge"))
        return True

    # -- helpers ---------------------------------------------------------

    def _handle_at(self, point: Point) -> Handle | None:
        """Which resize handle is under ``point``, if any."""
        if len(self.canvas.selection) != 1:
            return None
        reach = self.canvas.handle_reach
        for handle, position in self.canvas.selection[0].handles().items():
            if abs(position.x - point.x) <= reach and abs(position.y - point.y) <= reach:
                return handle
        return None

    def _notify(self) -> None:
        document = self.document
        if document is not None:
            document.emit("changed")

    # -- drawing ---------------------------------------------------------

    def draw_overlay(self, cr: cairo.Context, zoom: float) -> None:
        if self._mode is not _Mode.MARQUEE or self._marquee is None or not self._moved:
            return
        rect = self._marquee.normalized()
        x, y = rect.x * zoom, rect.y * zoom
        width, height = rect.width * zoom, rect.height * zoom

        cr.save()
        cr.rectangle(x, y, width, height)
        cr.set_source_rgba(0.21, 0.52, 0.89, 0.18)
        cr.fill_preserve()
        cr.set_source_rgba(0.21, 0.52, 0.89, 0.9)
        cr.set_line_width(1.0)
        cr.set_dash([4.0, 3.0])
        cr.stroke()
        cr.restore()
