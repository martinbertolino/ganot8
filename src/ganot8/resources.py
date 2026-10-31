"""Bundled resources: the icons shipped with the application.

Kept separate from ``app`` so that a window built on its own - as the tests do -
finds the icons too, without importing the application class.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import gi_init  # noqa: F401
from gi.repository import Gdk, Gtk

log = logging.getLogger(__name__)

#: Repository layout: <root>/data/icons/hicolor/scalable/actions/*.svg
ICON_PATH = Path(__file__).resolve().parents[2] / "data" / "icons"

_installed = False


def install_icons() -> bool:
    """Add the bundled icons to the display's icon theme. Idempotent.

    Adwaita ships no marker or redaction glyph, and the nearest stock icons - an
    eyedropper and a ticked checkbox - said the wrong thing entirely, so those
    two tools use icons drawn for them.

    Returns True once the path is registered. A display is required, so this is
    a no-op before GTK is initialised.
    """
    global _installed
    if _installed:
        return True
    display = Gdk.Display.get_default()
    if display is None:
        return False
    if not ICON_PATH.is_dir():
        log.warning("bundled icons not found at %s", ICON_PATH)
        return False
    Gtk.IconTheme.get_for_display(display).add_search_path(str(ICON_PATH))
    _installed = True
    return True
