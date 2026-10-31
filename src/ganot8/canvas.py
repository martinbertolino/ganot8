"""The image canvas: a DrawingArea inside a ScrolledWindow.

The drawing area's content size is the image size multiplied by the zoom level,
so the ScrolledWindow provides panning and scrollbars for free. Zooming is
anchored on the pointer, which means the scroll adjustments have to be corrected
after the new content size has been allocated.
"""

from __future__ import annotations

import math

from . import gi_init  # noqa: F401
from gi.repository import Gdk, GLib, GObject, Gtk

from . import render

ZOOM_MIN = 0.1
ZOOM_MAX = 8.0
ZOOM_STEPS = (0.1, 0.17, 0.25, 0.33, 0.5, 0.67, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)

#: Size of one checkerboard square, in on-screen pixels.
_CHECKER = 8
_CHECKER_LIGHT = (0.55, 0.55, 0.57)
_CHECKER_DARK = (0.42, 0.42, 0.44)


class Canvas(Gtk.DrawingArea):
    """Displays a :class:`~ganot8.document.Document` with zoom and pan."""

    __gtype_name__ = "Ganot8Canvas"

    __gsignals__ = {
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    def __init__(self):
        super().__init__()
        self._document = None
        self._zoom = 1.0
        self._fit_mode = True
        self._scroller: Gtk.ScrolledWindow | None = None
        self._pan_origin: tuple[float, float] | None = None
        self._pointer: tuple[float, float] | None = None
        self._document_handler = 0

        #: While no annotation tool is active, dragging with the left button
        #: pans. Phase 2 sets this False when a tool takes over the button.
        self.pan_with_primary = True

        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._on_draw)
        self._install_controllers()

    # -- wiring ----------------------------------------------------------

    def set_scroller(self, scroller: Gtk.ScrolledWindow) -> None:
        """Tell the canvas which ScrolledWindow holds it.

        Needed to anchor zoom on the pointer and to recompute fit-to-window when
        the viewport resizes. A viewport resize surfaces as a change to the
        adjustments' page-size, which is the reliable hook for it: a
        DrawingArea's own "resize" reports its content size, not the viewport.
        """
        self._scroller = scroller
        for adjustment in (scroller.get_hadjustment(), scroller.get_vadjustment()):
            adjustment.connect("notify::page-size", self._on_viewport_resized)

    def _install_controllers(self) -> None:
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.BOTH_AXES)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        zoom_gesture = Gtk.GestureZoom()
        zoom_gesture.connect("scale-changed", self._on_pinch)
        self.add_controller(zoom_gesture)

        for button in (Gdk.BUTTON_PRIMARY, Gdk.BUTTON_MIDDLE):
            drag = Gtk.GestureDrag(button=button)
            drag.connect("drag-begin", self._on_pan_begin)
            drag.connect("drag-update", self._on_pan_update)
            drag.connect("drag-end", self._on_pan_end)
            self.add_controller(drag)

    # -- document --------------------------------------------------------

    @property
    def document(self):
        return self._document

    def set_document(self, document) -> None:
        if self._document is not None and self._document_handler:
            self._document.disconnect(self._document_handler)
            self._document_handler = 0
        self._document = document
        if document is not None:
            self._document_handler = document.connect("changed", lambda *_: self.queue_draw())
        self._fit_mode = True
        self._apply_zoom(self._compute_fit_zoom(), notify=True)

    # -- zoom ------------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def fit_mode(self) -> bool:
        return self._fit_mode

    def zoom_in(self) -> None:
        self._set_zoom_stepped(+1)

    def zoom_out(self) -> None:
        self._set_zoom_stepped(-1)

    def zoom_to(self, zoom: float, *, anchor: tuple[float, float] | None = None) -> None:
        self._fit_mode = False
        self._apply_zoom(zoom, anchor=anchor, notify=True)

    def zoom_actual(self) -> None:
        self.zoom_to(1.0, anchor=self._viewport_centre())

    def zoom_fit(self) -> None:
        self._fit_mode = True
        self._apply_zoom(self._compute_fit_zoom(), notify=True)

    def _set_zoom_stepped(self, direction: int) -> None:
        current = self._zoom
        if direction > 0:
            target = next((z for z in ZOOM_STEPS if z > current + 1e-6), ZOOM_MAX)
        else:
            target = next((z for z in reversed(ZOOM_STEPS) if z < current - 1e-6), ZOOM_MIN)
        self.zoom_to(target, anchor=self._viewport_centre())

    def _viewport_centre(self) -> tuple[float, float] | None:
        """Centre of the visible area, in canvas-widget coordinates."""
        if self._scroller is None:
            return None
        hadj = self._scroller.get_hadjustment()
        vadj = self._scroller.get_vadjustment()
        return (
            hadj.get_value() + hadj.get_page_size() / 2,
            vadj.get_value() + vadj.get_page_size() / 2,
        )

    def _compute_fit_zoom(self) -> float:
        """Largest zoom that fits the image in the viewport, never above 1:1."""
        if self._document is None or self._scroller is None:
            return 1.0
        available_w = self._scroller.get_width()
        available_h = self._scroller.get_height()
        if available_w <= 1 or available_h <= 1:
            return 1.0
        margin = 24
        scale = min(
            (available_w - margin) / self._document.width,
            (available_h - margin) / self._document.height,
        )
        return max(ZOOM_MIN, min(1.0, scale))

    def _apply_zoom(
        self,
        zoom: float,
        *,
        anchor: tuple[float, float] | None = None,
        notify: bool = False,
    ) -> None:
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        if self._document is None:
            self._zoom = zoom
            self.set_content_width(0)
            self.set_content_height(0)
            if notify:
                self.emit("zoom-changed", zoom)
            return

        old_zoom = self._zoom
        self._zoom = zoom
        self.set_content_width(max(1, math.ceil(self._document.width * zoom)))
        self.set_content_height(max(1, math.ceil(self._document.height * zoom)))
        self.queue_draw()

        if anchor is not None and self._scroller is not None and old_zoom > 0:
            self._preserve_anchor(anchor, old_zoom, zoom)

        if notify:
            self.emit("zoom-changed", zoom)

    def _preserve_anchor(
        self, anchor: tuple[float, float], old_zoom: float, new_zoom: float
    ) -> None:
        """Keep the image point under ``anchor`` in the same place on screen.

        ``anchor`` is in canvas-widget coordinates at the *old* zoom. The
        adjustments can only be set once the new content size is allocated,
        hence the idle callback.
        """
        assert self._scroller is not None
        hadj = self._scroller.get_hadjustment()
        vadj = self._scroller.get_vadjustment()
        anchor_x, anchor_y = anchor
        # Where that point currently sits inside the visible viewport.
        viewport_x = anchor_x - hadj.get_value()
        viewport_y = anchor_y - vadj.get_value()
        image_x = anchor_x / old_zoom
        image_y = anchor_y / old_zoom

        def reposition() -> bool:
            hadj.set_value(image_x * new_zoom - viewport_x)
            vadj.set_value(image_y * new_zoom - viewport_y)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(reposition, priority=GLib.PRIORITY_HIGH_IDLE)

    def _on_viewport_resized(self, *_args) -> None:
        if self._fit_mode and self._document is not None:
            fit = self._compute_fit_zoom()
            if abs(fit - self._zoom) > 1e-4:
                self._apply_zoom(fit, notify=True)

    # -- coordinates -----------------------------------------------------

    def widget_to_image(self, x: float, y: float) -> tuple[float, float]:
        """Canvas-widget coordinates to source-image pixel coordinates."""
        return (x / self._zoom, y / self._zoom)

    def image_to_widget(self, x: float, y: float) -> tuple[float, float]:
        return (x * self._zoom, y * self._zoom)

    # -- input -----------------------------------------------------------

    def _on_motion(self, _controller, x: float, y: float) -> None:
        self._pointer = (x, y)

    def _on_leave(self, _controller) -> None:
        self._pointer = None

    def _on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        state = controller.get_current_event_state()
        if not (state & Gdk.ModifierType.CONTROL_MASK):
            return Gdk.EVENT_PROPAGATE  # plain scroll: let the ScrolledWindow pan
        if self._document is None or dy == 0:
            return Gdk.EVENT_STOP

        # Smooth (touchpad) deltas are fractional; a wheel click reports 1.0.
        factor = math.pow(0.85, dy)
        self._fit_mode = False
        anchor = self._pointer or self._viewport_centre()
        self._apply_zoom(self._zoom * factor, anchor=anchor, notify=True)
        return Gdk.EVENT_STOP

    def _on_pinch(self, gesture: Gtk.GestureZoom, scale: float) -> None:
        if self._document is None:
            return
        found, centre_x, centre_y = gesture.get_bounding_box_center()
        self._fit_mode = False
        anchor = (centre_x, centre_y) if found else self._viewport_centre()
        self._apply_zoom(self._zoom * scale, anchor=anchor, notify=True)

    def _on_pan_begin(self, gesture: Gtk.GestureDrag, _start_x: float, _start_y: float) -> None:
        if self._scroller is None or self._document is None:
            return
        if gesture.get_current_button() == Gdk.BUTTON_PRIMARY and not self.pan_with_primary:
            return
        self._pan_origin = (
            self._scroller.get_hadjustment().get_value(),
            self._scroller.get_vadjustment().get_value(),
        )
        self.set_cursor(Gdk.Cursor.new_from_name("grabbing", None))

    def _on_pan_update(self, _gesture, offset_x: float, offset_y: float) -> None:
        if self._pan_origin is None or self._scroller is None:
            return
        origin_x, origin_y = self._pan_origin
        self._scroller.get_hadjustment().set_value(origin_x - offset_x)
        self._scroller.get_vadjustment().set_value(origin_y - offset_y)

    def _on_pan_end(self, *_args) -> None:
        if self._pan_origin is None:
            return
        self._pan_origin = None
        self.set_cursor(None)

    # -- drawing ---------------------------------------------------------

    def _on_draw(self, _area: Gtk.DrawingArea, cr, _width: int, _height: int) -> None:
        if self._document is None:
            return

        scaled_w = self._document.width * self._zoom
        scaled_h = self._document.height * self._zoom

        self._draw_checkerboard(cr, scaled_w, scaled_h)

        cr.save()
        cr.rectangle(0, 0, scaled_w, scaled_h)
        cr.clip()
        cr.scale(self._zoom, self._zoom)
        # Past 1:1 the user is inspecting pixels, so stop interpolating.
        render.draw_document(cr, self._document, smooth=self._zoom < 1.0)
        cr.restore()

        # Hairline border, so a white image is distinguishable from the backdrop.
        cr.save()
        cr.set_line_width(1.0)
        cr.set_source_rgba(0, 0, 0, 0.35)
        cr.rectangle(0.5, 0.5, max(1.0, scaled_w - 1), max(1.0, scaled_h - 1))
        cr.stroke()
        cr.restore()

    def _draw_checkerboard(self, cr, width: float, height: float) -> None:
        """Checkerboard behind the image, so transparency is visible."""
        cr.save()
        cr.rectangle(0, 0, width, height)
        cr.clip()
        cr.set_source_rgb(*_CHECKER_LIGHT)
        cr.paint()
        cr.set_source_rgb(*_CHECKER_DARK)
        for row in range(int(height // _CHECKER) + 1):
            for col in range(int(width // _CHECKER) + 1):
                if (row + col) % 2:
                    cr.rectangle(col * _CHECKER, row * _CHECKER, _CHECKER, _CHECKER)
        cr.fill()
        cr.restore()
