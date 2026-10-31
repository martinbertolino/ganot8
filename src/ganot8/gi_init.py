"""Pin GObject-Introspection versions.

Import this before any ``gi.repository`` import. ``gi.require_version`` must run
before the namespace is first loaded, otherwise PyGObject emits a warning and
picks whatever version it finds.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
