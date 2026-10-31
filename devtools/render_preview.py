#!/usr/bin/env python
"""Render the real Canvas draw path to PNG files, without a visible window.

GNOME 50 denies org.gnome.Shell.Screenshot to unauthorized callers and there is
no Xvfb here, so the canvas cannot be screenshotted automatically. This drives
``Canvas._on_draw`` - the actual on-screen drawing function, not a copy of it -
into an image surface instead, which is enough to check rendering, scaling,
filtering and the checkerboard after a change.

A Wayland or X display must be present for Gtk.init(), but nothing is shown.

Usage:
    PYTHONPATH=src .venv/bin/python devtools/render_preview.py IMAGE [OUTDIR]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cairo

from ganot8 import gi_init  # noqa: F401
from gi.repository import Gtk

from ganot8.canvas import Canvas
from ganot8.document import Document
from ganot8.surfaces import surface_to_pil

BACKDROP = (0.16, 0.16, 0.17)
PAD = 20


def render(document: Document, zoom: float, out_path: Path) -> None:
    canvas = Canvas()
    canvas.set_document(document)
    canvas._zoom = zoom  # bypass fit-to-window, which needs a real scroller

    width = int(document.width * zoom) + PAD * 2
    height = int(document.height * zoom) + PAD * 2
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*BACKDROP)
    cr.paint()
    cr.translate(PAD, PAD)
    canvas._on_draw(canvas, cr, width, height)
    surface.flush()
    surface_to_pil(surface).save(out_path)
    print(f"{out_path}  (zoom {zoom:g}, {width}x{height})")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    source = Path(argv[1])
    out_dir = Path(argv[2]) if len(argv) > 2 else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    Gtk.init()
    document = Document.from_file(source)
    print(f"{source.name}: {document.size[0]}x{document.size[1]} via {document.loaded.loader}")
    for zoom in (0.5, 1.0, 4.0):
        render(document, zoom, out_dir / f"{source.stem}-zoom{zoom:g}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
