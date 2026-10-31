"""Annotation objects: the extension seam.

Adding a new annotation kind means writing one class here and one tool in
``ganot8.tools``. Nothing else in the application needs to change: the renderer,
the Select tool, the history stack and the project serialiser all work through
the interface below.

Geometry is always in source-image pixel coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import cairo

from .geometry import (
    EMPTY_RECT,
    Handle,
    Point,
    RECT_HANDLES,
    Rect,
    rect_handle_positions,
    resize_rect,
)

RGBA = tuple[float, float, float, float]

#: Style properties an annotation may expose to the sidebar.
STYLE_COLOR = "color"
STYLE_STROKE_WIDTH = "stroke_width"
STYLE_OPACITY = "opacity"
STYLE_FILLED = "filled"

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
