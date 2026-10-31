"""The Badge tool: numbered step markers."""

from __future__ import annotations

from typing import ClassVar

import cairo

from ..annotations import Badge, next_badge_number
from ..geometry import Point
from .base import Tool


class BadgeTool(Tool):
    name: ClassVar[str] = "badge"
    label: ClassVar[str] = "Badge"
    icon_name: ClassVar[str] = "ganot8-badge-symbolic"
    accelerator: ClassVar[str] = "n"
    tooltip: ClassVar[str] = "Place a numbered step marker (N)"
    annotation_type: ClassVar[type] = Badge
    create_label: ClassVar[str] = "Add Badge"

    def __init__(self, canvas):
        super().__init__(canvas)
        self._pending: Badge | None = None

    def deactivate(self) -> None:
        self._pending = None
        self.canvas.queue_draw()

    def on_drag_begin(self, point: Point, state) -> None:
        document = self.document
        if document is None:
            return
        self._pending = Badge(
            centre=point, number=next_badge_number(document.annotations)
        )
        self.canvas.apply_style_to(self._pending)

    def on_drag_update(self, point: Point, state) -> None:
        """Dragging away from the drop point sizes the badge."""
        if self._pending is None:
            return
        distance = point.distance_to(self._pending.centre)
        if distance > 6.0:
            self._pending.radius = distance
        self.canvas.queue_draw()

    def on_drag_end(self, point: Point, state) -> None:
        from ..history import AddAnnotations

        document = self.document
        pending, self._pending = self._pending, None
        if document is None or pending is None:
            return

        document.history.push(AddAnnotations(document, [pending], label=self.create_label))
        self.canvas.set_selection([pending])
        # Badges are usually placed in a run, so the tool stays active rather
        # than handing back to Select after every one.
        self.canvas.queue_draw()

    def draw_overlay(self, cr: cairo.Context, zoom: float) -> None:
        if self._pending is None:
            return
        cr.save()
        cr.scale(zoom, zoom)
        try:
            self._pending.draw(cr)
        finally:
            cr.restore()
