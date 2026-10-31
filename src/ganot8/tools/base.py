"""The tool interface and registry.

A tool translates pointer gestures into document edits. The canvas owns exactly
one active tool and forwards gestures to it in **image coordinates**; overlay
drawing happens in **widget coordinates** so that handles and outlines keep a
constant size however far the view is zoomed.
"""

from __future__ import annotations

from typing import ClassVar

import cairo

from ..geometry import Point

_REGISTRY: list[type["Tool"]] = []


def register(cls: type["Tool"]) -> type["Tool"]:
    """Class decorator that puts a tool in the tool strip."""
    _REGISTRY.append(cls)
    return cls


def registered_tools() -> tuple[type["Tool"], ...]:
    return tuple(_REGISTRY)


class Tool:
    """Base class for canvas tools."""

    name: ClassVar[str] = ""
    label: ClassVar[str] = ""
    icon_name: ClassVar[str] = "edit-symbolic"
    accelerator: ClassVar[str] = ""
    tooltip: ClassVar[str] = ""
    #: Cursor shown over the canvas while this tool is active.
    cursor: ClassVar[str | None] = "crosshair"
    #: True if dragging with the left button should pan instead of edit.
    pans: ClassVar[bool] = False

    def __init__(self, canvas):
        self.canvas = canvas

    # -- convenience -----------------------------------------------------

    @property
    def document(self):
        return self.canvas.document

    @property
    def history(self):
        document = self.document
        return document.history if document is not None else None

    # -- lifecycle -------------------------------------------------------

    def activate(self) -> None:
        """Called when the tool becomes active."""

    def deactivate(self) -> None:
        """Called when another tool takes over. Must abandon any in-progress edit."""

    # -- pointer ---------------------------------------------------------

    def on_drag_begin(self, point: Point, state) -> None:
        """Pointer pressed at ``point`` (image coordinates)."""

    def on_drag_update(self, point: Point, state) -> None:
        """Pointer moved to ``point`` while held."""

    def on_drag_end(self, point: Point, state) -> None:
        """Pointer released at ``point``. Push the resulting command here."""

    def on_motion(self, point: Point, state) -> None:
        """Pointer moved with no button held; used for cursor feedback."""

    def on_double_click(self, point: Point, state) -> None:
        """Pointer double-clicked at ``point``."""

    def cursor_for(self, point: Point, state) -> str | None:
        """Cursor name for the pointer at ``point``."""
        return self.cursor

    # -- keyboard --------------------------------------------------------

    def on_key(self, keyval: int, state) -> bool:
        """Return True if the key was consumed."""
        return False

    # -- drawing ---------------------------------------------------------

    def draw_overlay(self, cr: cairo.Context, zoom: float) -> None:
        """Draw tool feedback in widget coordinates.

        Never part of an export: the exporter calls ``render.draw_document``
        directly and never reaches a tool.
        """
