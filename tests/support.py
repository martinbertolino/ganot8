"""Shared test helpers."""

from __future__ import annotations

import os
from pathlib import Path


def display_available() -> bool:
    """Whether a display server is reachable, checked without touching GTK.

    ``Gtk.init_check()`` cannot be used for this, despite the name. With no
    display it has been observed to return ``True`` and, in another run of the
    same configuration, to **segfault the interpreter** before returning at
    all - which no ``try``/``except`` can catch. So the check looks for the
    socket directly instead.

    The Wayland branch mirrors GDK's own behaviour: it falls back to the
    ``wayland-0`` socket name, so an unset ``WAYLAND_DISPLAY`` does not mean
    there is no display.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    wayland = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    socket = Path(wayland)
    if not socket.is_absolute():
        socket = Path(runtime_dir) / wayland
    if socket.exists():
        return True
    return bool(os.environ.get("DISPLAY"))


SKIP_REASON = (
    "no display server; run under xvfb-run (see ./run-tests.sh) to exercise "
    "the widget tests"
)


def force_layout(window) -> None:
    """Run a layout pass now, without waiting for the compositor.

    A window that is mapped but never presented - which is normal for a test
    run, since the terminal keeps focus - receives no frame callbacks, so its
    ``GdkFrameClock`` stalls at frame 1 and queued resizes are never processed.
    Layout then simply never happens: a DrawingArea can report
    ``content_width = 569`` while the viewport still has it allocated at 2400,
    and assertions about allocated sizes fail for reasons that have nothing to
    do with the code under test.

    Allocating the toplevel at its current size drives the pass synchronously.
    Verified: without this the adjustment keeps the stale upper indefinitely;
    with it, the sizes agree immediately.
    """
    width, height = window.get_width(), window.get_height()
    if width <= 0 or height <= 0:
        return
    window.queue_resize()
    window.allocate(width, height, -1, None)
