"""The Crop tool: drag out the region to keep."""

from __future__ import annotations

from typing import ClassVar

import cairo

from .. import gi_init  # noqa: F401
from gi.repository import Gdk

from ..geometry import Point, Rect
from .base import Tool

#: A crop smaller than this in either direction is treated as a stray click.
_MINIMUM_SIZE = 8.0


class CropTool(Tool):
    """Crops on release.

    There is no separate confirm step: the crop is a single undoable command,
    so Ctrl+Z is the confirm step, and an extra round of handles and an Apply
    button would be more ceremony than the operation deserves.
    """

    name: ClassVar[str] = "crop"
    label: ClassVar[str] = "Crop"
    icon_name: ClassVar[str] = "ganot8-crop-symbolic"
    accelerator: ClassVar[str] = "c"
    tooltip: ClassVar[str] = "Crop the image to a region (C)"
    cursor: ClassVar[str] = "crosshair"

    def __init__(self, canvas):
        super().__init__(canvas)
        self._origin: Point | None = None
        self._region: Rect | None = None

    def deactivate(self) -> None:
        self._origin = None
        self._region = None
        self.canvas.queue_draw()

    def on_drag_begin(self, point: Point, state) -> None:
        if self.document is None:
            return
        self._origin = point
        self._region = Rect(point.x, point.y, 0, 0)

    def on_drag_update(self, point: Point, state) -> None:
        if self._origin is None:
            return
        region = Rect.from_points(self._origin, point)
        if state & Gdk.ModifierType.SHIFT_MASK:
            side = max(region.width, region.height)
            region = Rect(
                self._origin.x if point.x >= self._origin.x else self._origin.x - side,
                self._origin.y if point.y >= self._origin.y else self._origin.y - side,
                side,
                side,
            )
        self._region = region
        self.canvas.queue_draw()

    def on_drag_end(self, point: Point, state) -> None:
        document = self.document
        region, self._region = self._region, None
        self._origin = None
        if document is None or region is None:
            self.canvas.queue_draw()
            return

        region = region.normalized()
        if region.width < _MINIMUM_SIZE or region.height < _MINIMUM_SIZE:
            self.canvas.queue_draw()
            return

        self.canvas.clear_selection()
        if document.crop_to(region):
            self.canvas.zoom_fit()
        self.canvas.activate_tool("select")

    def on_key(self, keyval: int, state) -> bool:
        if keyval == Gdk.KEY_Escape and self._region is not None:
            self.deactivate()
            return True
        return False

    def draw_overlay(self, cr: cairo.Context, zoom: float) -> None:
        """Dim everything outside the region being kept."""
        document = self.document
        if document is None or self._region is None:
            return
        region = self._region.normalized()
        if region.is_empty():
            return

        width = document.width * zoom
        height = document.height * zoom
        x, y = region.x * zoom, region.y * zoom
        w, h = region.width * zoom, region.height * zoom

        cr.save()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, width, height)
        cr.rectangle(x, y, w, h)
        cr.set_source_rgba(0, 0, 0, 0.55)
        cr.fill()

        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.restore()
