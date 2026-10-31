"""The image canvas: a DrawingArea inside a ScrolledWindow.

Three coordinate spaces meet here:

* **image** pixels - what annotations store and what tools receive;
* **widget** pixels - image multiplied by zoom, what Cairo draws into;
* **viewport** pixels - what is scrolled into view.

The drawing area's content size is the image size times the zoom, so the
ScrolledWindow provides panning and scrollbars for free.
"""

from __future__ import annotations

import math

from . import gi_init  # noqa: F401
from gi.repository import Gdk, GLib, GObject, Gtk

from . import render
from .geometry import Point, Rect
from .history import RemoveAnnotations
from .tools import registered_tools

ZOOM_MIN = 0.1
ZOOM_MAX = 8.0
ZOOM_STEPS = (0.1, 0.17, 0.25, 0.33, 0.5, 0.67, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)

#: Size of one checkerboard square, in on-screen pixels.
_CHECKER = 8
_CHECKER_LIGHT = (0.55, 0.55, 0.57)
_CHECKER_DARK = (0.42, 0.42, 0.44)

#: Selection chrome, in on-screen pixels so it does not change with zoom.
HANDLE_SIZE_PX = 9.0
HIT_TOLERANCE_PX = 4.0
_SELECT_RGBA = (0.21, 0.52, 0.89, 1.0)

DEFAULT_TOOL_STYLE: dict[str, object] = {
    "color": (0.90, 0.16, 0.16, 1.0),
    "stroke_width": 3.0,
    "opacity": 1.0,
    "filled": False,
}


class Canvas(Gtk.DrawingArea):
    """Displays a :class:`~ganot8.document.Document` and hosts the active tool."""

    __gtype_name__ = "Ganot8Canvas"

    __gsignals__ = {
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "tool-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
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
        self._selection: list = []
        self._tools: dict[str, object] = {}
        self._tool = None
        self._drag_start: tuple[float, float] | None = None
        self.tool_style = dict(DEFAULT_TOOL_STYLE)

        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_focusable(True)
        self.set_draw_func(self._on_draw)
        self._build_tools()
        self._install_controllers()
        self.activate_tool("select")

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

    def _build_tools(self) -> None:
        for tool_type in registered_tools():
            self._tools[tool_type.name] = tool_type(self)

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

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

        primary = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        primary.connect("drag-begin", self._on_primary_begin)
        primary.connect("drag-update", self._on_primary_update)
        primary.connect("drag-end", self._on_primary_end)
        self.add_controller(primary)

        middle = Gtk.GestureDrag(button=Gdk.BUTTON_MIDDLE)
        middle.connect("drag-begin", self._on_pan_begin)
        middle.connect("drag-update", self._on_pan_update)
        middle.connect("drag-end", self._on_pan_end)
        self.add_controller(middle)

    # -- document --------------------------------------------------------

    @property
    def document(self):
        return self._document

    def set_document(self, document) -> None:
        if self._document is not None and self._document_handler:
            self._document.disconnect(self._document_handler)
            self._document_handler = 0
        self._document = document
        self._selection = []
        if document is not None:
            self._document_handler = document.connect("changed", self._on_document_changed)
        self._fit_mode = True
        self._apply_zoom(self._compute_fit_zoom(), notify=True)
        self.emit("selection-changed")

    def _on_document_changed(self, *_args) -> None:
        # Drop anything deleted (by an undo, say) from the selection.
        if self._document is not None:
            live = [a for a in self._selection if a in self._document.annotations]
            if len(live) != len(self._selection):
                self._selection = live
                self.emit("selection-changed")
        self.queue_draw()

    # -- selection -------------------------------------------------------

    @property
    def selection(self) -> list:
        return self._selection

    def set_selection(self, annotations) -> None:
        new_selection = [a for a in annotations if a.selectable]
        if new_selection == self._selection:
            return
        self._selection = new_selection
        self.emit("selection-changed")
        self.queue_draw()

    def toggle_selected(self, annotation) -> None:
        if annotation in self._selection:
            self.set_selection([a for a in self._selection if a is not annotation])
        else:
            self.set_selection([*self._selection, annotation])

    def select_all(self) -> None:
        if self._document is not None:
            self.set_selection(list(self._document.annotations))

    def clear_selection(self) -> None:
        self.set_selection([])

    def delete_selection(self) -> bool:
        if self._document is None or not self._selection:
            return False
        command = RemoveAnnotations(self._document, list(self._selection))
        self.set_selection([])
        return self._document.history.push(command)

    # -- tools -----------------------------------------------------------

    @property
    def tool(self):
        return self._tool

    @property
    def tool_name(self) -> str:
        return self._tool.name if self._tool is not None else ""

    def available_tools(self) -> tuple:
        return tuple(self._tools.values())

    def activate_tool(self, name: str) -> None:
        tool = self._tools.get(name)
        if tool is None or tool is self._tool:
            return
        if self._tool is not None:
            self._tool.deactivate()
        self._tool = tool
        tool.activate()
        self._update_cursor()
        self.emit("tool-changed", name)
        self.queue_draw()

    def apply_tool_style(self, annotation) -> None:
        """Stamp the current style settings onto a newly created annotation."""
        annotation.color = tuple(self.tool_style["color"])  # type: ignore[arg-type]
        annotation.stroke_width = float(self.tool_style["stroke_width"])  # type: ignore[arg-type]
        annotation.opacity = float(self.tool_style["opacity"])  # type: ignore[arg-type]
        if hasattr(annotation, "filled"):
            annotation.filled = bool(self.tool_style["filled"])

    # -- zoom ------------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def fit_mode(self) -> bool:
        return self._fit_mode

    @property
    def hit_tolerance(self) -> float:
        """Click slop in image pixels, constant on screen at any zoom."""
        return HIT_TOLERANCE_PX / max(self._zoom, 1e-6)

    @property
    def handle_reach(self) -> float:
        """Half a handle's size in image pixels, for hit-testing handles."""
        return (HANDLE_SIZE_PX / 2 + 1) / max(self._zoom, 1e-6)

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

        ``anchor`` is in widget coordinates at the *old* zoom. The adjustments
        can only be set once the new content size is allocated, hence the idle
        callback.
        """
        assert self._scroller is not None
        hadj = self._scroller.get_hadjustment()
        vadj = self._scroller.get_vadjustment()
        anchor_x, anchor_y = anchor
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

    def widget_to_image(self, x: float, y: float) -> Point:
        return Point(x / self._zoom, y / self._zoom)

    def image_to_widget(self, x: float, y: float) -> tuple[float, float]:
        return (x * self._zoom, y * self._zoom)

    # -- input -----------------------------------------------------------

    def _on_motion(self, _controller, x: float, y: float) -> None:
        self._pointer = (x, y)
        self._update_cursor()
        if self._tool is not None and self._document is not None:
            self._tool.on_motion(self.widget_to_image(x, y), self._modifier_state())

    def _on_leave(self, _controller) -> None:
        self._pointer = None

    def _modifier_state(self):
        display = self.get_display()
        seat = display.get_default_seat() if display is not None else None
        pointer = seat.get_pointer() if seat is not None else None
        return pointer.get_modifier_state() if pointer is not None else 0

    def _update_cursor(self) -> None:
        if self._tool is None or self._document is None or self._pointer is None:
            self.set_cursor(None)
            return
        if self._pan_origin is not None:
            return
        name = self._tool.cursor_for(
            self.widget_to_image(*self._pointer), self._modifier_state()
        )
        self.set_cursor(Gdk.Cursor.new_from_name(name, None) if name else None)

    def _on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        state = controller.get_current_event_state()
        if not (state & Gdk.ModifierType.CONTROL_MASK):
            return Gdk.EVENT_PROPAGATE  # plain scroll: let the ScrolledWindow pan
        if self._document is None or dy == 0:
            return Gdk.EVENT_STOP

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

    def _on_key_pressed(self, _controller, keyval: int, _keycode: int, state) -> bool:
        if self._document is None:
            return Gdk.EVENT_PROPAGATE
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            return Gdk.EVENT_STOP if self.delete_selection() else Gdk.EVENT_PROPAGATE
        if keyval == Gdk.KEY_Escape:
            if self._tool is not None:
                self._tool.deactivate()
            self.clear_selection()
            return Gdk.EVENT_STOP
        if self._tool is not None and self._tool.on_key(keyval, state):
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    # -- primary button: tool or pan -------------------------------------

    def _tool_takes_primary(self) -> bool:
        return self._document is not None and self._tool is not None and not self._tool.pans

    def _on_primary_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        self.grab_focus()
        if not self._tool_takes_primary():
            self._on_pan_begin(gesture, start_x, start_y)
            return
        self._drag_start = (start_x, start_y)
        self._tool.on_drag_begin(
            self.widget_to_image(start_x, start_y), gesture.get_current_event_state()
        )

    def _on_primary_update(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if self._drag_start is None:
            self._on_pan_update(gesture, dx, dy)
            return
        start_x, start_y = self._drag_start
        self._tool.on_drag_update(
            self.widget_to_image(start_x + dx, start_y + dy),
            gesture.get_current_event_state(),
        )

    def _on_primary_end(self, gesture: Gtk.GestureDrag, dx: float, dy: float) -> None:
        if self._drag_start is None:
            self._on_pan_end(gesture, dx, dy)
            return
        start_x, start_y = self._drag_start
        self._drag_start = None
        self._tool.on_drag_end(
            self.widget_to_image(start_x + dx, start_y + dy),
            gesture.get_current_event_state(),
        )
        self._update_cursor()

    # -- panning ---------------------------------------------------------

    def _on_pan_begin(self, _gesture, _start_x: float, _start_y: float) -> None:
        if self._scroller is None or self._document is None:
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
        self._update_cursor()

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

        # Selection chrome and tool feedback are screen-space, and deliberately
        # outside render.draw_document so they can never reach an export.
        self._draw_selection(cr)
        if self._tool is not None:
            cr.save()
            try:
                self._tool.draw_overlay(cr, self._zoom)
            finally:
                cr.restore()

    def _draw_selection(self, cr) -> None:
        if not self._selection:
            return
        red, green, blue, _ = _SELECT_RGBA

        for annotation in self._selection:
            bounds = annotation.bounds().normalized()
            x, y = self.image_to_widget(bounds.x, bounds.y)
            width = bounds.width * self._zoom
            height = bounds.height * self._zoom
            cr.save()
            cr.set_line_width(1.0)
            cr.set_dash([4.0, 3.0])
            cr.set_source_rgba(red, green, blue, 0.95)
            cr.rectangle(x - 0.5, y - 0.5, width + 1, height + 1)
            cr.stroke()
            cr.restore()

        if len(self._selection) != 1:
            return

        half = HANDLE_SIZE_PX / 2
        for position in self._selection[0].handles().values():
            hx, hy = self.image_to_widget(position.x, position.y)
            cr.save()
            cr.rectangle(hx - half, hy - half, HANDLE_SIZE_PX, HANDLE_SIZE_PX)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgba(red, green, blue, 1.0)
            cr.set_line_width(1.5)
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
