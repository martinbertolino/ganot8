"""Shape creation tools.

Phase 2 ships only Box, as the reference implementation of a creation tool.
The phase 3 tools (highlight, redact, underline, arrow, text) follow the same
shape: drag out a geometry, push an AddAnnotations command, select the result.
"""

from __future__ import annotations

from typing import ClassVar

import cairo

from .. import gi_init  # noqa: F401
from gi.repository import Gdk

from ..annotations import Box
from ..geometry import Point, Rect
from ..history import AddAnnotations
from .base import Tool, register

#: A drag smaller than this (in image pixels) is treated as a stray click.
_MINIMUM_SIZE = 3.0


class RectangleTool(Tool):
    """Shared behaviour for tools that drag out a rectangle."""

    annotation_type: ClassVar[type] = Box
    create_label: ClassVar[str] = "Add Box"

    def __init__(self, canvas):
        super().__init__(canvas)
        self._origin: Point | None = None
        self._pending = None

    def deactivate(self) -> None:
        self._origin = None
        self._pending = None
        self.canvas.queue_draw()

    def make_annotation(self, rect: Rect):
        """Build the annotation. Subclasses override to set their own style."""
        annotation = self.annotation_type(rect=rect)
        self.canvas.apply_tool_style(annotation)
        return annotation

    def on_drag_begin(self, point: Point, state) -> None:
        if self.document is None:
            return
        self._origin = point
        self._pending = self.make_annotation(Rect(point.x, point.y, 0, 0))

    def on_drag_update(self, point: Point, state) -> None:
        if self._origin is None or self._pending is None:
            return
        rect = Rect.from_points(self._origin, point)
        if state & Gdk.ModifierType.SHIFT_MASK:
            side = max(rect.width, rect.height)
            rect = Rect(
                self._origin.x if point.x >= self._origin.x else self._origin.x - side,
                self._origin.y if point.y >= self._origin.y else self._origin.y - side,
                side,
                side,
            )
        self._pending.rect = rect
        self.canvas.queue_draw()

    def on_drag_end(self, point: Point, state) -> None:
        document = self.document
        pending = self._pending
        self._origin = None
        self._pending = None
        if document is None or pending is None:
            return

        rect = pending.rect.normalized()
        if rect.width < _MINIMUM_SIZE or rect.height < _MINIMUM_SIZE:
            self.canvas.queue_draw()
            return

        pending.rect = rect
        document.history.push(AddAnnotations(document, [pending], label=self.create_label))
        self.canvas.set_selection([pending])
        # Hand back to Select so the new annotation can be adjusted at once.
        self.canvas.activate_tool("select")

    def draw_overlay(self, cr: cairo.Context, zoom: float) -> None:
        if self._pending is None:
            return
        cr.save()
        cr.scale(zoom, zoom)
        try:
            self._pending.draw(cr)
        finally:
            cr.restore()


@register
class BoxTool(RectangleTool):
    name: ClassVar[str] = "box"
    label: ClassVar[str] = "Box"
    icon_name: ClassVar[str] = "checkbox-symbolic"
    accelerator: ClassVar[str] = "b"
    tooltip: ClassVar[str] = "Draw a rectangle (B)"
    annotation_type: ClassVar[type] = Box
    create_label: ClassVar[str] = "Add Box"
