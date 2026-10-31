"""Geometry primitives, in source-image pixel coordinates.

Nothing here knows about zoom, scroll or widgets. Annotations store their
geometry in image pixels so that what is exported never depends on how the
canvas happened to be displayed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def translated(self, dx: float, dy: float) -> Point:
        return Point(self.x + dx, self.y + dy)

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    def to_list(self) -> list[float]:
        return [self.x, self.y]

    @classmethod
    def from_list(cls, values) -> Point:
        x, y = values
        return cls(float(x), float(y))


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    # -- construction ----------------------------------------------------

    @classmethod
    def from_points(cls, a: Point, b: Point) -> Rect:
        """A normalised rect spanning two corners, in any order."""
        left, right = min(a.x, b.x), max(a.x, b.x)
        top, bottom = min(a.y, b.y), max(a.y, b.y)
        return cls(left, top, right - left, bottom - top)

    @classmethod
    def from_list(cls, values) -> Rect:
        x, y, width, height = values
        return cls(float(x), float(y), float(width), float(height))

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.width, self.height]

    # -- edges -----------------------------------------------------------

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    # -- operations ------------------------------------------------------

    def normalized(self) -> Rect:
        """Return an equivalent rect with non-negative width and height."""
        x = self.x + min(0.0, self.width)
        y = self.y + min(0.0, self.height)
        return Rect(x, y, abs(self.width), abs(self.height))

    def translated(self, dx: float, dy: float) -> Rect:
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def inflated(self, amount: float) -> Rect:
        return Rect(
            self.x - amount,
            self.y - amount,
            self.width + amount * 2,
            self.height + amount * 2,
        )

    def contains(self, point: Point) -> bool:
        rect = self.normalized()
        return rect.left <= point.x <= rect.right and rect.top <= point.y <= rect.bottom

    def contains_rect(self, other: Rect) -> bool:
        a, b = self.normalized(), other.normalized()
        return a.left <= b.left and a.top <= b.top and a.right >= b.right and a.bottom >= b.bottom

    def intersects(self, other: Rect) -> bool:
        a, b = self.normalized(), other.normalized()
        return not (
            a.right < b.left or b.right < a.left or a.bottom < b.top or b.bottom < a.top
        )

    def union(self, other: Rect) -> Rect:
        a, b = self.normalized(), other.normalized()
        left, top = min(a.left, b.left), min(a.top, b.top)
        right, bottom = max(a.right, b.right), max(a.bottom, b.bottom)
        return Rect(left, top, right - left, bottom - top)

    def is_empty(self) -> bool:
        return self.width == 0 or self.height == 0


EMPTY_RECT = Rect(0.0, 0.0, 0.0, 0.0)


class Handle(Enum):
    """A draggable control point on a selected annotation."""

    NW = "nw"
    N = "n"
    NE = "ne"
    E = "e"
    SE = "se"
    S = "s"
    SW = "sw"
    W = "w"
    #: Endpoints, for annotations defined by two points rather than a rect.
    START = "start"
    END = "end"


CORNER_HANDLES = (Handle.NW, Handle.NE, Handle.SE, Handle.SW)
EDGE_HANDLES = (Handle.N, Handle.E, Handle.S, Handle.W)
RECT_HANDLES = CORNER_HANDLES + EDGE_HANDLES

#: Cursor names, so a handle shows the direction it resizes in.
HANDLE_CURSORS = {
    Handle.NW: "nw-resize",
    Handle.N: "n-resize",
    Handle.NE: "ne-resize",
    Handle.E: "e-resize",
    Handle.SE: "se-resize",
    Handle.S: "s-resize",
    Handle.SW: "sw-resize",
    Handle.W: "w-resize",
    Handle.START: "move",
    Handle.END: "move",
}


def rect_handle_positions(rect: Rect) -> dict[Handle, Point]:
    """The eight handle positions around a rect."""
    rect = rect.normalized()
    mid_x = rect.x + rect.width / 2
    mid_y = rect.y + rect.height / 2
    return {
        Handle.NW: Point(rect.left, rect.top),
        Handle.N: Point(mid_x, rect.top),
        Handle.NE: Point(rect.right, rect.top),
        Handle.E: Point(rect.right, mid_y),
        Handle.SE: Point(rect.right, rect.bottom),
        Handle.S: Point(mid_x, rect.bottom),
        Handle.SW: Point(rect.left, rect.bottom),
        Handle.W: Point(rect.left, mid_y),
    }


def resize_rect(rect: Rect, handle: Handle, point: Point, *, square: bool = False) -> Rect:
    """Move one handle of ``rect`` to ``point``.

    Dragging an edge past its opposite is allowed: the result is normalised, so
    the rect flips rather than inverting.
    """
    rect = rect.normalized()
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom

    if handle in (Handle.NW, Handle.W, Handle.SW):
        left = point.x
    elif handle in (Handle.NE, Handle.E, Handle.SE):
        right = point.x
    if handle in (Handle.NW, Handle.N, Handle.NE):
        top = point.y
    elif handle in (Handle.SW, Handle.S, Handle.SE):
        bottom = point.y

    if square and handle in CORNER_HANDLES:
        size = max(abs(right - left), abs(bottom - top))
        if handle in (Handle.NW, Handle.SW):
            left = right - math.copysign(size, right - left)
        else:
            right = left + math.copysign(size, right - left)
        if handle in (Handle.NW, Handle.NE):
            top = bottom - math.copysign(size, bottom - top)
        else:
            bottom = top + math.copysign(size, bottom - top)

    return Rect.from_points(Point(left, top), Point(right, bottom))


def distance_to_segment(point: Point, start: Point, end: Point) -> float:
    """Shortest distance from a point to a line segment."""
    dx, dy = end.x - start.x, end.y - start.y
    if dx == 0 and dy == 0:
        return point.distance_to(start)
    # Projection parameter of point onto the segment, clamped to it.
    t = ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return point.distance_to(Point(start.x + t * dx, start.y + t * dy))


def constrain_to_axis(start: Point, end: Point) -> Point:
    """Snap ``end`` to the nearest horizontal, vertical or 45 degree direction."""
    dx, dy = end.x - start.x, end.y - start.y
    if dx == 0 and dy == 0:
        return end
    angle = math.atan2(dy, dx)
    step = math.pi / 4
    snapped = round(angle / step) * step
    length = math.hypot(dx, dy)
    return Point(start.x + math.cos(snapped) * length, start.y + math.sin(snapped) * length)


def clamp(value: float, lowest: float, highest: float) -> float:
    return max(lowest, min(highest, value))
