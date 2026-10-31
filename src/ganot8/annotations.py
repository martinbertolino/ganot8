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

from .effects import (
    DEFAULT_STRENGTH,
    REDACT_STYLES,
    STYLE_BLUR,
    STYLE_PIXELATE,
    STYLE_SOLID,
)
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
STYLE_REDACT_STYLE = "style"
STYLE_STRENGTH = "strength"

#: Every style key a sidebar row can edit, in the order they are shown.
STYLE_KEYS = (
    STYLE_COLOR,
    STYLE_FONT,
    STYLE_STROKE_WIDTH,
    STYLE_OPACITY,
    STYLE_FILLED,
    STYLE_WAVY,
    STYLE_BACKGROUND,
    STYLE_REDACT_STYLE,
    STYLE_STRENGTH,
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
    #: 7px rather than a hairline: an annotation has to read clearly on a
    #: screenshot that may later be scaled down in a document or chat.
    stroke_width: float = 7.0
    opacity: float = 1.0

    # -- geometry (subclasses implement) ---------------------------------

    def bounds(self) -> Rect:
        """Bounding box in image coordinates, including stroke width."""
        raise NotImplementedError

    def draw(self, cr: cairo.Context, ctx=None) -> None:
        """Draw in image coordinates. The caller has already saved the context.

        ``ctx`` is a :class:`~ganot8.render.RenderContext` when one is
        available. It is optional because only blur and pixelate redactions
        need to read the pixels underneath."""
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

    def visible_style_properties(self) -> tuple[str, ...]:
        """Which style rows apply *right now*.

        Defaults to :attr:`style_properties`. A kind overrides this when a
        setting makes another one inert - showing a control that does nothing
        is worse than not showing it.
        """
        return self.style_properties

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

    #: Filled by default: a solid block is what a box is usually wanted for,
    #: and an outline is one switch away.
    filled: bool = True

    def draw(self, cr: cairo.Context, ctx=None) -> None:
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

    def visible_style_properties(self) -> tuple[str, ...]:
        # draw() either fills or strokes, never both, so line width has no
        # effect at all while the box is filled.
        if self.filled:
            return tuple(p for p in self.style_properties if p != STYLE_STROKE_WIDTH)
        return self.style_properties

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

    def draw(self, cr: cairo.Context, ctx=None) -> None:
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

    def draw(self, cr: cairo.Context, ctx=None) -> None:
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
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_REDACT_STYLE,
        STYLE_COLOR,
        STYLE_STRENGTH,
    )

    color: RGBA = (0.0, 0.0, 0.0, 1.0)
    style: str = STYLE_SOLID
    strength: float = DEFAULT_STRENGTH

    def bounds(self) -> Rect:
        return self.rect.normalized()

    def visible_style_properties(self) -> tuple[str, ...]:
        # Colour only means something for a solid block; strength only means
        # something for the two that actually process pixels.
        if self.style == STYLE_SOLID:
            return (STYLE_REDACT_STYLE, STYLE_COLOR)
        return (STYLE_REDACT_STYLE, STYLE_STRENGTH)

    def draw(self, cr: cairo.Context, ctx=None) -> None:
        rect = self.rect.normalized()
        if rect.is_empty():
            return
        if self.style in (STYLE_BLUR, STYLE_PIXELATE) and self._draw_effect(cr, rect, ctx):
            return
        # Solid, and the fallback whenever the pixels are unavailable: covering
        # the region completely is always safe, whereas skipping the draw would
        # silently expose what the user asked to hide.
        red, green, blue, _ = self.color
        cr.save()
        cr.set_operator(cairo.OPERATOR_OVER)
        # Alpha is forced to 1.0: a see-through redaction is not a redaction.
        cr.set_source_rgba(red, green, blue, 1.0)
        cr.rectangle(rect.x, rect.y, rect.width, rect.height)
        cr.fill()
        cr.restore()

    def _draw_effect(self, cr: cairo.Context, rect: Rect, ctx) -> bool:
        """Paint the blurred or pixelated patch. False if it could not be built."""
        source = getattr(ctx, "source", None)
        cache = getattr(ctx, "cache", None)
        if source is None or cache is None:
            return False
        patch = cache.patch(source, self.style, self.strength, rect)
        if patch is None:
            return False

        cr.save()
        cr.rectangle(rect.x, rect.y, rect.width, rect.height)
        cr.clip()
        # The patch was cut from integer pixel bounds, so it is placed on them.
        cr.set_source_surface(patch.surface, float(int(rect.x)), float(int(rect.y)))
        cr.get_source().set_extend(cairo.EXTEND_PAD)
        cr.paint()
        cr.restore()
        return True

    def hit_test(self, point: Point, tolerance: float) -> bool:
        return self.rect.normalized().inflated(tolerance).contains(point)

    def geometry_to_dict(self) -> dict[str, Any]:
        data = super().geometry_to_dict()
        data["style"] = self.style
        data["strength"] = self.strength
        return data

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        super().geometry_from_dict(data)
        if "style" in data:
            style = str(data["style"])
            # An unknown style must fall back to solid, never to "draw nothing".
            self.style = style if style in REDACT_STYLES else STYLE_SOLID
        if "strength" in data:
            self.strength = float(data["strength"])


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

    def draw(self, cr: cairo.Context, ctx=None) -> None:
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

    def draw(self, cr: cairo.Context, ctx=None) -> None:
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

    def draw(self, cr: cairo.Context, ctx=None) -> None:
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


@register
@dataclass(eq=False)
class Ellipse(RectAnnotation):
    """An ellipse inscribed in its rect, outlined or filled."""

    kind: ClassVar[str] = "ellipse"
    label: ClassVar[str] = "Ellipse"
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_COLOR,
        STYLE_STROKE_WIDTH,
        STYLE_OPACITY,
        STYLE_FILLED,
    )

    filled: bool = False

    def visible_style_properties(self) -> tuple[str, ...]:
        if self.filled:
            return tuple(p for p in self.style_properties if p != STYLE_STROKE_WIDTH)
        return self.style_properties

    def _path(self, cr: cairo.Context, rect: Rect) -> None:
        """Trace the ellipse by scaling a unit circle into the rect."""
        cr.save()
        cr.translate(rect.x + rect.width / 2, rect.y + rect.height / 2)
        cr.scale(max(rect.width, 1e-6) / 2, max(rect.height, 1e-6) / 2)
        cr.arc(0, 0, 1, 0, math.tau)
        cr.restore()

    def draw(self, cr: cairo.Context, ctx=None) -> None:
        rect = self.rect.normalized()
        if rect.is_empty():
            return
        red, green, blue, alpha = self.color
        if self.filled:
            # The scaling that traces the path would also scale the stroke
            # unevenly, so the path is built inside save/restore and the
            # paint happens in plain user space.
            self._path(cr, rect)
            cr.set_source_rgba(red, green, blue, alpha * self.opacity)
            cr.fill()
            return
        self._path(cr, rect)
        self._set_stroke(cr)
        cr.stroke()

    def hit_test(self, point: Point, tolerance: float) -> bool:
        rect = self.rect.normalized()
        half_w = max(rect.width / 2, 1e-6)
        half_h = max(rect.height / 2, 1e-6)
        centre = rect.center
        # Normalised radius: 1.0 is exactly on the outline.
        radius = math.hypot(
            (point.x - centre.x) / half_w, (point.y - centre.y) / half_h
        )
        if self.filled:
            slack = tolerance / min(half_w, half_h)
            return radius <= 1.0 + slack
        reach = (self.stroke_width / 2 + tolerance) / min(half_w, half_h)
        return abs(radius - 1.0) <= reach

    def geometry_to_dict(self) -> dict[str, Any]:
        data = super().geometry_to_dict()
        data["filled"] = self.filled
        return data

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        super().geometry_from_dict(data)
        if "filled" in data:
            self.filled = bool(data["filled"])


@register
@dataclass(eq=False)
class Freehand(Annotation):
    """A line drawn by hand, stored as the points it passed through."""

    kind: ClassVar[str] = "freehand"
    label: ClassVar[str] = "Freehand"
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_COLOR,
        STYLE_STROKE_WIDTH,
        STYLE_OPACITY,
    )

    points: list[Point] = field(default_factory=list)

    def bounds(self) -> Rect:
        if not self.points:
            return EMPTY_RECT
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        reach = self.stroke_width / 2 + 1
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).inflated(reach)

    def draw(self, cr: cairo.Context, ctx=None) -> None:
        if len(self.points) < 2:
            if len(self.points) == 1:
                # A tap still leaves a mark, rather than vanishing.
                point = self.points[0]
                red, green, blue, alpha = self.color
                cr.set_source_rgba(red, green, blue, alpha * self.opacity)
                cr.arc(point.x, point.y, max(0.5, self.stroke_width / 2), 0, math.tau)
                cr.fill()
            return
        self._set_stroke(cr)
        cr.move_to(self.points[0].x, self.points[0].y)
        for point in self.points[1:]:
            cr.line_to(point.x, point.y)
        cr.stroke()

    def hit_test(self, point: Point, tolerance: float) -> bool:
        reach = self.stroke_width / 2 + tolerance
        if len(self.points) == 1:
            return point.distance_to(self.points[0]) <= reach
        return any(
            distance_to_segment(point, a, b) <= reach
            for a, b in zip(self.points, self.points[1:])
        )

    def handles(self) -> dict[Handle, Point]:
        """None: a hand-drawn stroke has no meaningful control points."""
        return {}

    def move(self, dx: float, dy: float) -> None:
        self.points = [p.translated(dx, dy) for p in self.points]

    def set_handle(self, handle: Handle, point: Point, *, constrain: bool = False) -> None:
        return

    def geometry_to_dict(self) -> dict[str, Any]:
        return {"points": [p.to_list() for p in self.points]}

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        if "points" in data:
            self.points = [Point.from_list(entry) for entry in data["points"]]


@register
@dataclass(eq=False)
class Badge(Annotation):
    """A numbered disc, for walking someone through a screenshot step by step."""

    kind: ClassVar[str] = "badge"
    label: ClassVar[str] = "Badge"
    style_properties: ClassVar[tuple[str, ...]] = (
        STYLE_COLOR,
        STYLE_FONT,
        STYLE_OPACITY,
    )

    centre: Point = Point(0.0, 0.0)
    number: int = 1
    radius: float = 18.0
    text_color: RGBA = (1.0, 1.0, 1.0, 1.0)
    font: str = "Sans Bold 16"

    def bounds(self) -> Rect:
        return Rect(
            self.centre.x - self.radius,
            self.centre.y - self.radius,
            self.radius * 2,
            self.radius * 2,
        )

    def handles(self) -> dict[Handle, Point]:
        """East only: dragging it resizes the disc."""
        return {Handle.E: Point(self.centre.x + self.radius, self.centre.y)}

    def move(self, dx: float, dy: float) -> None:
        self.centre = self.centre.translated(dx, dy)

    def set_handle(self, handle: Handle, point: Point, *, constrain: bool = False) -> None:
        if handle is Handle.E:
            self.radius = max(6.0, abs(point.x - self.centre.x))

    def hit_test(self, point: Point, tolerance: float) -> bool:
        return point.distance_to(self.centre) <= self.radius + tolerance

    def draw(self, cr: cairo.Context, ctx=None) -> None:
        if self.radius <= 0:
            return
        red, green, blue, alpha = self.color
        cr.save()
        cr.set_source_rgba(red, green, blue, alpha * self.opacity)
        cr.arc(self.centre.x, self.centre.y, self.radius, 0, math.tau)
        cr.fill()
        cr.restore()

        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription.from_string(self.font))
        layout.set_text(str(self.number), -1)
        width, height = layout.get_pixel_size()

        text_red, text_green, text_blue, text_alpha = self.text_color
        cr.save()
        cr.set_source_rgba(text_red, text_green, text_blue, text_alpha * self.opacity)
        cr.move_to(self.centre.x - width / 2, self.centre.y - height / 2)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def geometry_to_dict(self) -> dict[str, Any]:
        return {
            "centre": self.centre.to_list(),
            "number": self.number,
            "radius": self.radius,
            "text_color": list(self.text_color),
            "font": self.font,
        }

    def geometry_from_dict(self, data: dict[str, Any]) -> None:
        if "centre" in data:
            self.centre = Point.from_list(data["centre"])
        if "number" in data:
            self.number = int(data["number"])
        if "radius" in data:
            self.radius = float(data["radius"])
        if "text_color" in data:
            self.text_color = tuple(float(c) for c in data["text_color"])
        if "font" in data:
            self.font = str(data["font"])


def next_badge_number(annotations) -> int:
    """One past the highest badge already placed, so numbering continues.

    Counting badges would restart at a number already used once an earlier one
    had been deleted.
    """
    numbers = [a.number for a in annotations if isinstance(a, Badge)]
    return max(numbers) + 1 if numbers else 1
