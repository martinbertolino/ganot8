#!/usr/bin/env python
"""Render the live application UI to PNG files, without a screenshot tool.

GNOME 50 denies org.gnome.Shell.Screenshot to unauthorized callers and there is
no Xvfb here, so the window cannot be captured from outside. GTK can do it from
the inside instead: a realized widget is snapshotted to a Gsk render node and
rendered to a texture by the toplevel's own renderer.

A window does appear briefly while this runs.

Usage:
    PYTHONPATH=src .venv/bin/python devtools/shoot_ui.py IMAGE [OUTDIR]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ganot8 import gi_init  # noqa: F401
from gi.repository import Adw, GLib, Gtk

from ganot8.annotations import Box
from ganot8.geometry import Rect
from ganot8.window import Window

WINDOW_SIZE = (1150, 760)


def pump(predicate, timeout: float = 5.0) -> bool:
    """Run the main loop until ``predicate`` holds, or time runs out."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def force_layout(window: Gtk.Widget) -> None:
    """Run a layout pass now, without waiting for the compositor.

    A window that is mapped but never presented - normal here, since the
    terminal keeps focus - gets no frame callbacks, so its GdkFrameClock
    stalls at frame 1 and nothing is ever laid out or painted. The snapshot
    then comes back empty. Allocating the toplevel at its current size drives
    the pass synchronously.
    """
    width, height = window.get_width(), window.get_height()
    if width > 0 and height > 0:
        window.queue_resize()
        window.allocate(width, height, -1, None)


def shoot(widget: Gtk.Widget, path: Path) -> bool:
    """Render ``widget`` to a PNG using its toplevel's renderer."""
    native = widget.get_native()
    if native is None:
        print(f"  {path.name}: widget is not realized", file=sys.stderr)
        return False
    if isinstance(native, Gtk.Window):
        force_layout(native)

    # A toplevel's own paintable renders nothing while the frame clock is
    # stalled - painting a window goes through its surface, which the
    # compositor drives. Its content child snapshots on demand, and for an
    # Adw.ApplicationWindow that child holds the header bar too, so nothing
    # of interest is lost.
    if isinstance(widget, Adw.ApplicationWindow):
        widget = widget.get_content() or widget
    elif isinstance(widget, Gtk.Window):
        widget = widget.get_child() or widget

    width, height = widget.get_width(), widget.get_height()
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable(widget=widget).snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        print(f"  {path.name}: nothing to draw", file=sys.stderr)
        return False

    native.get_renderer().render_texture(node, None).save_to_png(str(path))
    print(f"  {path}  ({width}x{height})")
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    source = Path(argv[1])
    out_dir = Path(argv[2]) if len(argv) > 2 else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    Adw.init()
    app = Adw.Application(application_id="io.github.martinb.Ganot8.Devtool")

    def on_activate(application: Adw.Application) -> None:
        window = Window(application=application)
        window.set_default_size(*WINDOW_SIZE)
        window.present()
        pump(window.get_mapped)
        # Animations are driven by the frame clock, which never ticks for an
        # unpresented window, so a crossfade would be frozen half-way and the
        # snapshot would show both pages at once.
        window._stack.set_transition_type(Gtk.StackTransitionType.NONE)
        window.open_path(source)
        pump(lambda: window._scroller.get_width() > 1)

        # Select something, so the sidebar is shown in its populated state.
        sample = Box(rect=Rect(40, 80, 500, 40))
        window.document.annotations.append(sample)
        window.canvas.set_selection([sample])
        for _ in range(8):
            pump(lambda: False, timeout=0.05)
            force_layout(window)

        shoot(window, out_dir / "ui-window.png")
        shoot(window._split.get_sidebar(), out_dir / "ui-sidebar.png")
        application.quit()

    app.connect("activate", on_activate)
    return app.run([])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
