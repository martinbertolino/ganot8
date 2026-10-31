"""The Freehand tool: draw by dragging."""

from __future__ import annotations

from typing import ClassVar

import cairo

from ..annotations import Freehand
from ..geometry import Point
from .base import Tool

#: Points closer together than this are dropped. Motion events arrive far more
#: densely than the drawing needs, and keeping them all bloats both the project
#: file and the redraw.
_MIN_SPACING = 1.5

#: A stroke shorter than this in total is treated as a stray click.
_MIN_LENGTH = 4.0


class FreehandTool(Tool):
    name: ClassVar[str] = "freehand"
    label: ClassVar[str] = "Freehand"
    icon_name: ClassVar[str] = "document-edit-symbolic"
    accelerator: ClassVar[str] = "f"
    tooltip: ClassVar[str] = "Draw freehand (F)"
    cursor: ClassVar[str] = "crosshair"
    annotation_type: ClassVar[type] = Freehand
    create_label: ClassVar[str] = "Add Freehand"

    def __init__(self, canvas):
        super().__init__(canvas)
        self._pending: Freehand | None = None

    def deactivate(self) -> None:
        self._pending = None
        self.canvas.queue_draw()

    def on_drag_begin(self, point: Point, state) -> None:
        if self.document is None:
            return
        self._pending = Freehand(points=[point])
        self.canvas.apply_style_to(self._pending)
        self._pending.points = [point]

    def on_drag_update(self, point: Point, state) -> None:
        if self._pending is None:
            return
        if point.distance_to(self._pending.points[-1]) < _MIN_SPACING:
            return
        self._pending.points.append(point)
        self.canvas.queue_draw()

    def on_drag_end(self, point: Point, state) -> None:
        from ..history import AddAnnotations

        document = self.document
        pending, self._pending = self._pending, None
        if document is None or pending is None:
            return

        if point.distance_to(pending.points[-1]) >= _MIN_SPACING:
            pending.points.append(point)
        if self._length(pending) < _MIN_LENGTH:
            self.canvas.queue_draw()
            return

        document.history.push(AddAnnotations(document, [pending], label=self.create_label))
        self.canvas.set_selection([pending])
        self.canvas.activate_tool("select")

    @staticmethod
    def _length(stroke: Freehand) -> float:
        return sum(
            a.distance_to(b) for a, b in zip(stroke.points, stroke.points[1:])
        )

    def draw_overlay(self, cr: cairo.Context, zoom: float) -> None:
        if self._pending is None:
            return
        cr.save()
        cr.scale(zoom, zoom)
        try:
            self._pending.draw(cr)
        finally:
            cr.restore()
