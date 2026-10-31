"""The Text tool.

Creating a label opens an editor straight away; an empty one is discarded
rather than left on the image as an invisible object.
"""

from __future__ import annotations

from typing import ClassVar

import cairo

from ..annotations import TextLabel
from ..geometry import Point
from .base import Tool

#: Drag at least this far (image pixels) to set a wrap width instead of
#: placing a label that grows to fit its text.
_WRAP_THRESHOLD = 24.0


class TextTool(Tool):
    name: ClassVar[str] = "text"
    label: ClassVar[str] = "Text"
    icon_name: ClassVar[str] = "format-text-rich-symbolic"
    accelerator: ClassVar[str] = "t"
    tooltip: ClassVar[str] = "Add a text label (T)"
    cursor: ClassVar[str] = "text"
    annotation_type: ClassVar[type] = TextLabel

    def __init__(self, canvas):
        super().__init__(canvas)
        self._origin: Point | None = None
        self._width: float | None = None

    def deactivate(self) -> None:
        self._origin = None
        self._width = None
        self.canvas.queue_draw()

    def on_drag_begin(self, point: Point, state) -> None:
        if self.document is None:
            return
        self._origin = point
        self._width = None

    def on_drag_update(self, point: Point, state) -> None:
        if self._origin is None:
            return
        width = point.x - self._origin.x
        self._width = width if width >= _WRAP_THRESHOLD else None
        self.canvas.queue_draw()

    def on_drag_end(self, point: Point, state) -> None:
        origin, width = self._origin, self._width
        self._origin = None
        self._width = None
        if self.document is None or origin is None:
            return

        annotation = TextLabel(anchor=origin, wrap_width=width)
        self.canvas.apply_style_to(annotation)
        # Style memory must not resurrect an old label's text.
        annotation.text = ""
        annotation.wrap_width = width
        self.canvas.begin_text_edit(annotation, is_new=True)

    def draw_overlay(self, cr: cairo.Context, zoom: float) -> None:
        """Preview the wrap width while dragging one out."""
        if self._origin is None or self._width is None:
            return
        x, y = self._origin.x * zoom, self._origin.y * zoom
        cr.save()
        cr.set_source_rgba(0.21, 0.52, 0.89, 0.9)
        cr.set_line_width(1.0)
        cr.set_dash([4.0, 3.0])
        cr.move_to(x, y)
        cr.line_to(x + self._width * zoom, y)
        cr.stroke()
        cr.restore()
