"""The one place a document is drawn.

Both the on-screen canvas and the file exporter call :func:`draw_document`. The
canvas draws through a zoom/pan matrix; the exporter draws at scale 1.0 into an
image surface. Sharing this function is what keeps an exported file identical to
what the user saw - a second drawing routine would inevitably drift from it.

Selection handles, the marquee and tool previews are deliberately **not** drawn
here. They belong to the canvas, so they cannot reach an export.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cairo


@dataclass(frozen=True)
class RenderContext:
    """What an annotation may need beyond the Cairo context itself.

    Only blur and pixelate redactions use it: they have to read the pixels they
    are covering, which nothing else does. It is optional everywhere so that a
    kind which does not need it can ignore it entirely.
    """

    source: Any = None
    cache: Any = None

    @classmethod
    def for_document(cls, document) -> "RenderContext":
        return cls(source=document.source, cache=document.effect_cache)


def draw_document(cr: cairo.Context, document, *, smooth: bool = True) -> None:
    """Draw ``document`` into ``cr`` in image pixel coordinates.

    The caller sets up any scaling beforehand, so everything here works in
    source-image pixels.

    :param smooth: use bilinear filtering. Callers pass ``False`` when zoomed in
        past 1:1 so that individual pixels stay crisp instead of being blurred.
    """
    cr.save()
    cr.set_source_surface(document.cairo_image.surface, 0, 0)
    pattern = cr.get_source()
    pattern.set_filter(cairo.FILTER_GOOD if smooth else cairo.FILTER_NEAREST)
    # EXTEND_PAD stops the edge pixels being blended with transparency outside
    # the image, which otherwise shows as a faint border when scaled.
    pattern.set_extend(cairo.EXTEND_PAD)
    cr.rectangle(0, 0, document.width, document.height)
    cr.fill()
    cr.restore()

    draw_annotations(cr, document)


def draw_annotations(cr: cairo.Context, document) -> None:
    """Draw every annotation in z-order (first in the list is furthest back)."""
    context = RenderContext.for_document(document)
    for annotation in document.annotations:
        cr.save()
        try:
            annotation.draw(cr, context)
        finally:
            cr.restore()
