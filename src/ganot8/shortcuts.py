"""The keyboard shortcuts window.

Built on ``Adw.ShortcutsDialog`` rather than ``Gtk.ShortcutsWindow``: the GTK
one is deprecated, and the libadwaita replacement is available here (1.9).

The listing is generated from the same tables the accelerators come from, so a
shortcut cannot be added without appearing here, or documented without being
bound.
"""

from __future__ import annotations

from . import gi_init  # noqa: F401
from gi.repository import Adw, Gtk

#: (section title, [(label, action name)]). Accelerators are looked up from
#: the application, so this never restates a key combination.
SECTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Images",
        (
            ("Open an image or project", "win.open"),
            ("New from screenshot", "win.screenshot"),
            ("Paste as a new image", "win.paste"),
            ("Copy the result to the clipboard", "win.copy"),
            ("Export a flattened copy", "win.export"),
            ("Export as…", "win.export-as"),
            ("Save project", "win.save-project"),
            ("Quit", "app.quit"),
        ),
    ),
    (
        "Editing",
        (
            ("Undo", "win.undo"),
            ("Redo", "win.redo"),
            ("Select all", "win.select-all"),
            ("Deselect", "win.deselect"),
            ("Delete selection", "win.delete"),
            ("Bring forward", "win.raise-annotation"),
            ("Send backward", "win.lower-annotation"),
            ("Rotate left", "win.rotate-left"),
            ("Rotate right", "win.rotate-right"),
        ),
    ),
    (
        "View",
        (
            ("Zoom in", "win.zoom-in"),
            ("Zoom out", "win.zoom-out"),
            ("Zoom to fit", "win.zoom-fit"),
            ("Actual size", "win.zoom-100"),
            ("Show or hide the style sidebar", "win.toggle-sidebar"),
            ("Keyboard shortcuts", "win.shortcuts"),
        ),
    ),
)


def build_dialog(window) -> Adw.ShortcutsDialog:
    """Build the dialog, listing only shortcuts that are actually bound."""
    dialog = Adw.ShortcutsDialog()
    application = window.get_application()

    for title, entries in SECTIONS:
        section = Adw.ShortcutsSection(title=title)
        added = False
        for label, action in entries:
            accelerators = (
                application.get_accels_for_action(action) if application else []
            )
            if not accelerators:
                continue
            section.add(Adw.ShortcutsItem(title=label, accelerator=accelerators[0]))
            added = True
        if added:
            dialog.add(section)

    tools = Adw.ShortcutsSection(title="Tools")
    tool_added = False
    for tool in window.canvas.available_tools():
        accelerators = (
            application.get_accels_for_action(f"win.tool::{tool.name}")
            if application
            else []
        )
        if not accelerators:
            continue
        tools.add(Adw.ShortcutsItem(title=tool.label, accelerator=accelerators[0]))
        tool_added = True
    if tool_added:
        dialog.add(tools)

    return dialog


def present_shortcuts(window: Gtk.Widget) -> None:
    build_dialog(window).present(window)
