"""Bundled resources: the icons shipped with the application.

Two ways in, tried in order:

1. A compiled **GResource**, which an installed build carries. Icons found
   through a resource path do not depend on the system icon cache having been
   refreshed after installation, which is a common way for a freshly installed
   application to come up with broken icons.
2. The **source tree**, for running straight from a checkout.

Kept separate from ``app`` so that a window built on its own - as the tests do -
finds the icons too, without importing the application class.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from . import APP_ID, gi_init  # noqa: F401
from gi.repository import Gdk, Gio, GLib, Gtk

log = logging.getLogger(__name__)

#: Where icons live inside the GResource bundle.
RESOURCE_PATH = "/io/github/martinbertolino/Ganot8/icons"

RESOURCE_NAME = f"{APP_ID}.gresource"

#: Repository layout: <root>/data/icons/hicolor/scalable/actions/*.svg
ICON_PATH = Path(__file__).resolve().parents[2] / "data" / "icons"

_installed = False
_registered_resource = None


def _candidate_bundles() -> list[Path]:
    """Places an installed build may have put the resource bundle."""
    here = Path(__file__).resolve().parent
    candidates = [here / RESOURCE_NAME, here.parent / RESOURCE_NAME]
    override = os.environ.get("GANOT8_RESOURCE_DIR")
    if override:
        candidates.insert(0, Path(override) / RESOURCE_NAME)
    for data_dir in GLib.get_system_data_dirs():
        candidates.append(Path(data_dir) / "ganot8" / RESOURCE_NAME)
    return candidates


def _register_bundle() -> bool:
    """Load and register the GResource, if one was installed alongside us."""
    global _registered_resource
    if _registered_resource is not None:
        return True
    for path in _candidate_bundles():
        if not path.is_file():
            continue
        try:
            resource = Gio.resource_load(str(path))
        except GLib.Error as error:
            log.warning("could not load %s: %s", path, error.message)
            continue
        Gio.resources_register(resource)
        _registered_resource = resource
        log.debug("icons loaded from %s", path)
        return True
    return False


def install_icons() -> bool:
    """Make the bundled icons findable by name. Idempotent.

    Adwaita ships no marker or redaction glyph, and the nearest stock icons - an
    eyedropper and a ticked checkbox - said the wrong thing entirely, so those
    tools use icons drawn for them.

    Returns True once the icons are reachable. A display is required, so this is
    a no-op before GTK is initialised.
    """
    global _installed
    if _installed:
        return True
    display = Gdk.Display.get_default()
    if display is None:
        return False

    theme = Gtk.IconTheme.get_for_display(display)
    if _register_bundle():
        theme.add_resource_path(RESOURCE_PATH)
        _installed = True
        return True

    if ICON_PATH.is_dir():
        theme.add_search_path(str(ICON_PATH))
        _installed = True
        return True

    log.warning("no icon bundle and no %s; tool icons will be missing", ICON_PATH)
    return False
