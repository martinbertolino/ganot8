"""Annotation objects: the extension seam.

Adding a new annotation kind means writing one class here and one tool in
``ganot8.tools``. Nothing else in the application needs to change: the renderer,
the Select tool, the history stack and the project serialiser all work through
the interface below.

Geometry is always in source-image pixel coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, ClassVar

import cairo

from . import gi_init  # noqa: F401
from gi.repository import Pango, PangoCairo

from .geometry import (
    EMPTY_RECT,
    Handle,
    Point,
    RECT_HANDLES,
    Rect,
    distance_to_segment,
    rect_handle_positions,
    resize_rect,
)

RGBA = tuple[float, float, float, float]

#: Style properties an annotation may expose to the sidebar.
STYLE_COLOR = "color"
STYLE_STROKE_WIDTH = "stroke_width"
STYLE_OPACITY = "opacity"
STYLE_FILLED = "filled"
STYLE_FONT = "font"
STYLE_WAVY = "wavy"
STYLE_BACKGROUND = "background"

#: Every style key a sidebar row can edit, in the order they are shown.
STYLE_KEYS = (
    STYLE_COLOR,
    STYLE_FONT,
    STYLE_STROKE_WIDTH,
    STYLE_OPACITY,
    STYLE_FILLED,
    STYLE_WAVY,
    STYLE_BACKGROUND,
)

_REGISTRY: dict[str, type["Annotation"]] = {}


def register(cls: type["Annotation"]) -> type["Annotation"]:
    """Class decorator that makes a kind loadable from a project file."""
    if not cls.kind:
        raise ValueError(f"{cls.__name__} must define a kind")
    _REGISTRY[cls.kind] = cls
    return cls


def registered_kinds() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


@dataclass(eq=False)
class Annotation:
    """Base class for everything drawn on top of the image.

    ``eq=False`` is deliberate. Annotations are **identity** objects, not value
    objects: two boxes with identical geometry are two different annotations.
    With dataclass value equality, ``list.index()`` and ``list.remove()`` on
    ``document.annotations`` would match whichever came first, so deleting one
    of a pair of identical annotations removed the wrong one and undo restored
    it at the wrong z-position. Identity equality also keeps them hashable.
    """

    kind: ClassVar[str] = ""
    label: ClassVar[str] = "Annotation"
    #: Unknown kinds are kept but cannot be picked up with the mouse.
    selectable: ClassVar[bool] = True
    #: Which rows the style sidebar should show for this kind.
    style_properties: ClassVar[tuple[str, ...]] = (STYLE_COLOR, STYLE_STROKE_WIDTH)

    color: RGBA = (0.90, 0.16, 0.16, 1.0)
    stroke_width: float = 3.0
    opacity: float = 1.0

    # -- geometry (subclasses implement) ---------------------------------

    def bounds(self) -> Rect:
        """Bounding box in image coordinates, including stroke width."""
        raise NotImplementedError

    def draw(self, cr: cairo.Context) -> None:
        """Draw in image coordinates. The caller has already saved the context."""
        raise NotImplementedError

    def hit_test(self, point: Point, tolerance: float) -> bool:
        raise NotImplementedError

    def handles(self) -> dict[Handle, Point]:
        return {}

    def move(self, dx: float, dy: float) -> None:
        raise NotImplementedError

    def set_handle(self, handle: Handle, point: Point, *, constrain: bool = False) -> None:
        raise NotImplementedError

    # -- serialisation ---------------------------------------------------

    def geometry_to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "color": list(self.color),
            "stroke_width": self.stroke_width,
            "opacity": self.opacity,
        }
        data.update(self.geometry_to_dict())
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Annotation":
        annotation = cls()
        annotation.apply_dict(data)
        return annotation

    def apply_dict(self, data: dict[str, Any]) -> None:
        if "color" in data:
            self.color = tuple(float(c) for c in data["color"])  # type: ignore[assignment]
        if "stroke_width" in data:
            self.stroke_width = float(data["stroke_width"])
        if "opacity" in data:
            self.opacity = float(data["opacity"])
        self.geometry_from_dict(data)

    # -- undo support ----------------------------------------------------

    def state(self) -> dict[str, Any]:
        """A snapshot for the history stack."""
        return self.to_dict()

    def restore(self, state: dict[str, Any]) -> None:
        """Restore a snapshot **in place**.

        Mutating rather than replacing matters: the selection and any pending
        command hold references to this object, and they must stay valid across
        an undo.
        """
        self.apply_dict(state)

    def clone(self) -> "Annotation":
        return type(self).from_dict(self.to_dict())

    # -- drawing helpers -------------------------------------------------

    def _set_stroke(self, cr: cairo.Context) -> None:
        red, green, blue, alpha = self.color
        cr.set_source_rgba(red, green, blue, alpha * self.opacity)
        cr.set_line_width(max(0.1, self.stroke_width))
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)


@dataclass(eq=False)
class RectAnnotation(Annotation):
    """Shared behaviour for every annotation defined by a rectangle."""

    rect: Rect = EMPTY_RECT

    def bounds(self) -> Rect:
        return self.rect.normalized().inflated(self.stroke_width / 2 + 1)

    def handles(self) -> dict[Handle, Point]:
        return rect_handle_positions(self.rect)

    def move(self, dx: float, dy: float) -> None:
        self.rect = self.rect.translated(dx, dy)

    def set_handle(self, handle: Handle, point: Point, *, constrain: bool = False) -> None:
        if handle in RECT_HANDLES:
            self.rect = resize_rect(self.rect, handle, point, square=constrain)

    def geometry_to_dict(self) -> dict[str, Any]:
        return {"rect": self.rect.to_list()}

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        if "rect" in data:
            self.rect = Rect.from_list(data["rect"])


@register
@dataclass(eq=False)
class Box(RectAnnotation):
    """A rectangular outline, optionally filled.

    This is the reference implementation of the annotation interface; the
    phase 3 tools follow the same shape.
    """

    kind: ClassVar[str] = "box"
    label: ClassVar[str] = "Box"
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_COLOR,
        STYLE_STROKE_WIDTH,
        STYLE_OPACITY,
        STYLE_FILLED,
    )

    filled: bool = False

    def draw(self, cr: cairo.Context) -> None:
        rect = self.rect.normalized()
        if rect.is_empty():
            return
        cr.rectangle(rect.x, rect.y, rect.width, rect.height)
        if self.filled:
            red, green, blue, alpha = self.color
            cr.set_source_rgba(red, green, blue, alpha * self.opacity)
            cr.fill()
            return
        self._set_stroke(cr)
        cr.stroke()

    def hit_test(self, point: Point, tolerance: float) -> bool:
        rect = self.rect.normalized()
        if self.filled:
            return rect.inflated(tolerance).contains(point)
        reach = self.stroke_width / 2 + tolerance
        if not rect.inflated(reach).contains(point):
            return False
        # Hollow: only the outline is clickable, not the empty middle.
        return not rect.inflated(-reach).contains(point)

    def geometry_to_dict(self) -> dict[str, Any]:
        data = super().geometry_to_dict()
        data["filled"] = self.filled
        return data

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        super().geometry_from_dict(data)
        if "filled" in data:
            self.filled = bool(data["filled"])


@dataclass(eq=False)
class UnknownAnnotation(Annotation):
    """An annotation kind this build does not understand.

    Kept so that opening and re-saving a project written by a newer version
    does not silently destroy its work (see docs/SPEC.md section 4). It draws
    nothing and cannot be selected.
    """

    kind: ClassVar[str] = "__unknown__"
    label: ClassVar[str] = "Unsupported"
    selectable: ClassVar[bool] = False
    style_properties: ClassVar[tuple[str, ...]] = ()

    raw: dict[str, Any] = field(default_factory=dict)

    def bounds(self) -> Rect:
        return EMPTY_RECT

    def draw(self, cr: cairo.Context) -> None:
        return

    def hit_test(self, point: Point, tolerance: float) -> bool:
        return False

    def move(self, dx: float, dy: float) -> None:
        return

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)

    def state(self) -> dict[str, Any]:
        return dict(self.raw)

    def restore(self, state: dict[str, Any]) -> None:
        self.raw = dict(state)

    def clone(self) -> "UnknownAnnotation":
        return UnknownAnnotation(raw=dict(self.raw))

    def geometry_to_dict(self) -> dict[str, Any]:
        return {}

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        self.raw = dict(data)


def annotation_from_dict(data: dict[str, Any]) -> Annotation:
    """Rebuild an annotation, preserving kinds this build does not know."""
    kind = data.get("kind")
    annotation_type = _REGISTRY.get(kind) if isinstance(kind, str) else None
    if annotation_type is None:
        return UnknownAnnotation(raw=dict(data))
    return annotation_type.from_dict(data)


# ---------------------------------------------------------------------------
# Phase 3: the five core annotation kinds
# ---------------------------------------------------------------------------


@register
@dataclass(eq=False)
class Highlight(RectAnnotation):
    """A translucent wash that leaves the content underneath readable.

    Drawn with ``OPERATOR_MULTIPLY`` rather than plain alpha so dark text shows
    through at full contrast, the way a real highlighter behaves.
    """

    kind: ClassVar[str] = "highlight"
    label: ClassVar[str] = "Highlight"
    style_properties: ClassVar[tuple[str, ...]] = (STYLE_COLOR, STYLE_OPACITY)

    color: RGBA = (1.0, 0.92, 0.23, 1.0)
    opacity: float = 0.35

    def bounds(self) -> Rect:
        return self.rect.normalized()

    def draw(self, cr: cairo.Context) -> None:
        rect = self.rect.normalized()
        if rect.is_empty():
            return
        red, green, blue, alpha = self.color
        cr.save()
        cr.set_operator(cairo.OPERATOR_MULTIPLY)
        cr.set_source_rgba(red, green, blue, alpha * self.opacity)
        cr.rectangle(rect.x, rect.y, rect.width, rect.height)
        cr.fill()
        cr.restore()

    def hit_test(self, point: Point, tolerance: float) -> bool:
        return self.rect.normalized().inflated(tolerance).contains(point)


@register
@dataclass(eq=False)
class Redact(RectAnnotation):
    """An opaque block that hides what is underneath.

    Deliberately exposes no opacity control: a translucent redaction still
    leaks the content it is meant to hide (docs/SPEC.md section 6), so
    ``draw`` ignores ``opacity`` outright rather than trusting callers.
    ``style`` is reserved for the blur and pixelate modes added in phase 5.
    """

    kind: ClassVar[str] = "redact"
    label: ClassVar[str] = "Redaction"
    style_properties: ClassVar[tuple[str, ...]] = (STYLE_COLOR,)

    color: RGBA = (0.0, 0.0, 0.0, 1.0)
    style: str = "solid"

    def bounds(self) -> Rect:
        return self.rect.normalized()

    def draw(self, cr: cairo.Context) -> None:
        rect = self.rect.normalized()
        if rect.is_empty():
            return
        red, green, blue, _ = self.color
        cr.save()
        cr.set_operator(cairo.OPERATOR_OVER)
        # Alpha is forced to 1.0: a see-through redaction is not a redaction.
        cr.set_source_rgba(red, green, blue, 1.0)
        cr.rectangle(rect.x, rect.y, rect.width, rect.height)
        cr.fill()
        cr.restore()

    def hit_test(self, point: Point, tolerance: float) -> bool:
        return self.rect.normalized().inflated(tolerance).contains(point)

    def geometry_to_dict(self) -> dict[str, Any]:
        data = super().geometry_to_dict()
        data["style"] = self.style
        return data

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        super().geometry_from_dict(data)
        if "style" in data:
            self.style = str(data["style"])


@dataclass(eq=False)
class LineAnnotation(Annotation):
    """Shared behaviour for annotations defined by two endpoints."""

    start: Point = Point(0.0, 0.0)
    end: Point = Point(0.0, 0.0)

    @property
    def length(self) -> float:
        return self.start.distance_to(self.end)

    @property
    def angle(self) -> float:
        return math.atan2(self.end.y - self.start.y, self.end.x - self.start.x)

    def bounds(self) -> Rect:
        return Rect.from_points(self.start, self.end).inflated(self.stroke_width / 2 + 1)

    def handles(self) -> dict[Handle, Point]:
        return {Handle.START: self.start, Handle.END: self.end}

    def move(self, dx: float, dy: float) -> None:
        self.start = self.start.translated(dx, dy)
        self.end = self.end.translated(dx, dy)

    def set_handle(self, handle: Handle, point: Point, *, constrain: bool = False) -> None:
        if handle is Handle.START:
            self.start = point
        elif handle is Handle.END:
            self.end = point

    def hit_test(self, point: Point, tolerance: float) -> bool:
        reach = self.stroke_width / 2 + tolerance
        return distance_to_segment(point, self.start, self.end) <= reach

    def geometry_to_dict(self) -> dict[str, Any]:
        return {"start": self.start.to_list(), "end": self.end.to_list()}

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        if "start" in data:
            self.start = Point.from_list(data["start"])
        if "end" in data:
            self.end = Point.from_list(data["end"])


@register
@dataclass(eq=False)
class Underline(LineAnnotation):
    """A straight or wavy rule, for marking a line of text."""

    kind: ClassVar[str] = "underline"
    label: ClassVar[str] = "Underline"
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_COLOR,
        STYLE_STROKE_WIDTH,
        STYLE_OPACITY,
        STYLE_WAVY,
    )

    wavy: bool = False

    def bounds(self) -> Rect:
        reach = self.stroke_width / 2 + 1
        if self.wavy:
            reach += self._amplitude
        return Rect.from_points(self.start, self.end).inflated(reach)

    @property
    def _amplitude(self) -> float:
        return max(1.5, self.stroke_width)

    @property
    def _wavelength(self) -> float:
        return max(4.0, self.stroke_width * 4)

    def draw(self, cr: cairo.Context) -> None:
        if self.length <= 0:
            return
        self._set_stroke(cr)
        if not self.wavy:
            cr.move_to(self.start.x, self.start.y)
            cr.line_to(self.end.x, self.end.y)
            cr.stroke()
            return

        # Draw the wave along a rotated axis so the stroke stays even.
        cr.save()
        cr.translate(self.start.x, self.start.y)
        cr.rotate(self.angle)
        amplitude, wavelength = self._amplitude, self._wavelength
        steps = max(2, int(self.length / max(1.0, wavelength / 8)))
        cr.move_to(0, 0)
        for step in range(1, steps + 1):
            x = self.length * step / steps
            cr.line_to(x, math.sin(x / wavelength * math.tau) * amplitude)
        cr.stroke()
        cr.restore()

    def hit_test(self, point: Point, tolerance: float) -> bool:
        reach = self.stroke_width / 2 + tolerance
        if self.wavy:
            reach += self._amplitude
        return distance_to_segment(point, self.start, self.end) <= reach

    def geometry_to_dict(self) -> dict[str, Any]:
        data = super().geometry_to_dict()
        data["wavy"] = self.wavy
        return data

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        super().geometry_from_dict(data)
        if "wavy" in data:
            self.wavy = bool(data["wavy"])


@register
@dataclass(eq=False)
class Arrow(LineAnnotation):
    """A line with a solid head, for pointing at something."""

    kind: ClassVar[str] = "arrow"
    label: ClassVar[str] = "Arrow"
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_COLOR,
        STYLE_STROKE_WIDTH,
        STYLE_OPACITY,
    )

    #: Head length as a multiple of the stroke width.
    head_scale: float = 4.0

    @property
    def head_length(self) -> float:
        return max(6.0, self.stroke_width * self.head_scale)

    def bounds(self) -> Rect:
        reach = max(self.stroke_width / 2, self.head_length * 0.6) + 1
        return Rect.from_points(self.start, self.end).inflated(reach)

    def draw(self, cr: cairo.Context) -> None:
        length = self.length
        if length <= 0:
            return
        self._set_stroke(cr)
        head = min(self.head_length, length)
        half_width = head * 0.45

        cr.save()
        cr.translate(self.end.x, self.end.y)
        cr.rotate(self.angle)
        # Local space: the tip is at the origin, the tail runs out to -length.
        if length > head:
            cr.move_to(-length, 0)
            # Stop short of the tip so the stroke cap cannot poke through it.
            cr.line_to(-head * 0.75, 0)
            cr.stroke()
        cr.move_to(0, 0)
        cr.line_to(-head, -half_width)
        cr.line_to(-head, half_width)
        cr.close_path()
        cr.fill()
        cr.restore()

    def hit_test(self, point: Point, tolerance: float) -> bool:
        reach = max(self.stroke_width / 2, self.head_length * 0.5) + tolerance
        return distance_to_segment(point, self.start, self.end) <= reach

    def geometry_to_dict(self) -> dict[str, Any]:
        data = super().geometry_to_dict()
        data["head_scale"] = self.head_scale
        return data

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        super().geometry_from_dict(data)
        if "head_scale" in data:
            self.head_scale = float(data["head_scale"])


#: A 1x1 scratch surface, so text can be measured without a drawing target.
_MEASURE_CONTEXT = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


@register
@dataclass(eq=False)
class TextLabel(Annotation):
    """A short text label, optionally on a filled background plate."""

    kind: ClassVar[str] = "text"
    label: ClassVar[str] = "Text"
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_COLOR,
        STYLE_FONT,
        STYLE_OPACITY,
        STYLE_BACKGROUND,
    )

    anchor: Point = Point(0.0, 0.0)
    text: str = ""
    font: str = "Sans 18"
    #: Wrap width in image pixels, or None for no wrapping.
    wrap_width: float | None = None
    background: bool = False
    background_color: RGBA = (1.0, 1.0, 1.0, 0.85)
    padding: float = 6.0

    # -- layout ----------------------------------------------------------

    def _build_layout(self, cr: cairo.Context):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription.from_string(self.font))
        layout.set_text(self.text, -1)
        if self.wrap_width is not None and self.wrap_width > 0:
            layout.set_width(int(self.wrap_width * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        return layout

    def text_size(self) -> tuple[float, float]:
        """Rendered size in image pixels, measured off-screen."""
        if not self.text:
            return (0.0, 0.0)
        width, height = self._build_layout(_MEASURE_CONTEXT).get_pixel_size()
        return (float(width), float(height))

    def bounds(self) -> Rect:
        width, height = self.text_size()
        if width <= 0 or height <= 0:
            # An empty label still needs a clickable footprint.
            width = height = max(8.0, self.stroke_width * 4)
        rect = Rect(self.anchor.x, self.anchor.y, width, height)
        return rect.inflated(self.padding) if self.background else rect

    def handles(self) -> dict[Handle, Point]:
        """Only the horizontal handles: they set the wrap width."""
        rect = self.bounds()
        middle = rect.y + rect.height / 2
        return {Handle.W: Point(rect.left, middle), Handle.E: Point(rect.right, middle)}

    def move(self, dx: float, dy: float) -> None:
        self.anchor = self.anchor.translated(dx, dy)

    def set_handle(self, handle: Handle, point: Point, *, constrain: bool = False) -> None:
        if handle is Handle.E:
            self.wrap_width = max(16.0, point.x - self.anchor.x)
        elif handle is Handle.W:
            right = self.anchor.x + (self.wrap_width or self.text_size()[0])
            new_x = min(point.x, right - 16.0)
            self.wrap_width = max(16.0, right - new_x)
            self.anchor = Point(new_x, self.anchor.y)

    def hit_test(self, point: Point, tolerance: float) -> bool:
        return self.bounds().inflated(tolerance).contains(point)

    def draw(self, cr: cairo.Context) -> None:
        if not self.text:
            return
        layout = self._build_layout(cr)
        width, height = layout.get_pixel_size()

        if self.background:
            red, green, blue, alpha = self.background_color
            cr.save()
            cr.set_source_rgba(red, green, blue, alpha * self.opacity)
            _rounded_rect(
                cr,
                Rect(self.anchor.x, self.anchor.y, width, height).inflated(self.padding),
                radius=min(6.0, self.padding + 2),
            )
            cr.fill()
            cr.restore()

        red, green, blue, alpha = self.color
        cr.save()
        cr.set_source_rgba(red, green, blue, alpha * self.opacity)
        cr.move_to(self.anchor.x, self.anchor.y)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def geometry_to_dict(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor.to_list(),
            "text": self.text,
            "font": self.font,
            "wrap_width": self.wrap_width,
            "background": self.background,
            "background_color": list(self.background_color),
            "padding": self.padding,
        }

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        if "anchor" in data:
            self.anchor = Point.from_list(data["anchor"])
        if "text" in data:
            self.text = str(data["text"])
        if "font" in data:
            self.font = str(data["font"])
        if "wrap_width" in data:
            value = data["wrap_width"]
            self.wrap_width = None if value is None else float(value)
        if "background" in data:
            self.background = bool(data["background"])
        if "background_color" in data:
            self.background_color = tuple(float(c) for c in data["background_color"])
        if "padding" in data:
            self.padding = float(data["padding"])


def _rounded_rect(cr: cairo.Context, rect: Rect, radius: float) -> None:
    radius = min(radius, rect.width / 2, rect.height / 2)
    if radius <= 0:
        cr.rectangle(rect.x, rect.y, rect.width, rect.height)
        return
    cr.new_sub_path()
    cr.arc(rect.right - radius, rect.top + radius, radius, -math.pi / 2, 0)
    cr.arc(rect.right - radius, rect.bottom - radius, radius, 0, math.pi / 2)
    cr.arc(rect.left + radius, rect.bottom - radius, radius, math.pi / 2, math.pi)
    cr.arc(rect.left + radius, rect.top + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()
