"""Clipboard transfer: paste an image in, copy a flattened one out.

Images cross the clipboard as PNG rather than raw pixels. ``Gdk.Texture``
already encodes and decodes PNG, so this stays lossless without either side
having to agree on a memory layout.
"""

from __future__ import annotations

import io
import logging
from typing import Callable

from PIL import Image

from . import gi_init  # noqa: F401
from gi.repository import Gdk, GLib

log = logging.getLogger(__name__)


class ClipboardError(Exception):
    """Raised when the clipboard holds nothing this application can use."""


def texture_to_pil(texture: Gdk.Texture) -> Image.Image:
    """Convert a clipboard texture into an RGBA image."""
    data = texture.save_to_png_bytes().get_data()
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGBA")
        image.load()
    # A fresh image, so nothing is inherited that an export would have to strip.
    image.info.clear()
    return image


def pil_to_texture(image: Image.Image) -> Gdk.Texture:
    """Convert an image into a texture suitable for the clipboard."""
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buffer.getvalue()))


def copy_image(clipboard: Gdk.Clipboard, image: Image.Image) -> None:
    """Put ``image`` on the clipboard as a texture."""
    provider = Gdk.ContentProvider.new_for_value(pil_to_texture(image))
    clipboard.set_content(provider)


def paste_image(
    clipboard: Gdk.Clipboard,
    on_image: Callable[[Image.Image], None],
    on_error: Callable[[str], None],
) -> None:
    """Read an image off the clipboard, calling back on the main loop.

    The read is asynchronous because the other application may still have to
    produce the data; blocking here would freeze the window while it did.
    """

    def finished(source: Gdk.Clipboard, result) -> None:
        try:
            texture = source.read_texture_finish(result)
        except GLib.Error as error:
            log.info("clipboard read failed: %s", error.message)
            on_error("The clipboard does not contain an image.")
            return
        if texture is None:
            on_error("The clipboard does not contain an image.")
            return
        try:
            on_image(texture_to_pil(texture))
        except Exception as error:  # a malformed texture is not worth crashing over
            log.exception("could not decode the pasted image")
            on_error(f"The pasted image could not be read: {error}")

    clipboard.read_texture_async(None, finished)
