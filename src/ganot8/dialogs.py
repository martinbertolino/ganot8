"""Dialogs that need more than a file chooser.

``Gtk.FileDialog`` takes no custom widgets, so anything with options - export
format and quality - needs its own dialog ahead of the chooser.
"""

from __future__ import annotations

from typing import Callable

from . import gi_init  # noqa: F401
from gi.repository import Adw, Gtk

from .imageio import exporter

#: Formats whose quality setting is worth exposing.
_LOSSY = {"JPEG", "WEBP", "AVIF"}


class ExportOptionsDialog(Adw.Dialog):
    """Pick a format and quality, then hand back to the caller."""

    __gtype_name__ = "Ganot8ExportOptionsDialog"

    def __init__(self, *, initial_format: str = "PNG", initial_quality: int = 92):
        super().__init__()
        self.set_title("Export Image")
        self.set_content_width(420)
        self._on_confirm: Callable[[str, int], None] | None = None

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        self._confirm_button = Gtk.Button(label="Export…")
        self._confirm_button.add_css_class("suggested-action")
        self._confirm_button.connect("clicked", self._on_confirm_clicked)
        header.pack_end(self._confirm_button)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        page.add(group)

        self._formats = exporter.EXPORT_FORMATS
        names = Gtk.StringList()
        for fmt in self._formats:
            names.append(f"{fmt.label}  ({', '.join(fmt.extensions)})")
        self._format_row = Adw.ComboRow(title="Format", model=names)
        index = next(
            (i for i, f in enumerate(self._formats) if f.name == initial_format), 0
        )
        self._format_row.set_selected(index)
        self._format_row.connect("notify::selected", lambda *_: self._sync())
        group.add(self._format_row)

        self._quality_row = Adw.SpinRow(
            title="Quality",
            subtitle="Higher keeps more detail and makes a larger file",
            adjustment=Gtk.Adjustment(
                value=initial_quality, lower=10, upper=100, step_increment=1
            ),
        )
        group.add(self._quality_row)

        self._note = Adw.ActionRow(
            title="Annotations are flattened",
            subtitle=(
                "The exported image contains pixels only. Redactions cannot be "
                "recovered from it, and source metadata is removed."
            ),
        )
        self._note.add_css_class("property")
        group.add(self._note)

        toolbar.set_content(page)
        self.set_child(toolbar)
        self._sync()

    # -- state -----------------------------------------------------------

    @property
    def selected_format(self):
        return self._formats[self._format_row.get_selected()]

    @property
    def quality(self) -> int:
        return int(self._quality_row.get_value())

    def _sync(self) -> None:
        self._quality_row.set_visible(self.selected_format.name in _LOSSY)

    def _on_confirm_clicked(self, *_args) -> None:
        callback, self._on_confirm = self._on_confirm, None
        self.close()
        if callback is not None:
            callback(self.selected_format, self.quality)

    def choose(self, parent: Gtk.Widget, on_confirm: Callable) -> None:
        """Present the dialog; ``on_confirm(format, quality)`` runs if accepted."""
        self._on_confirm = on_confirm
        self.present(parent)
