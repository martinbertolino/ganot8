"""The main window: header bar, canvas, empty state, export flow."""

from __future__ import annotations

import logging
from pathlib import Path

from . import gi_init  # noqa: F401
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_NAME
from .canvas import Canvas
from .document import Document
from .imageio import exporter
from .imageio.loader import UnsupportedImageError, load

log = logging.getLogger(__name__)

_OPENABLE_MIME = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/heif",
    "image/tiff",
    "image/bmp",
    "image/x-icon",
    "image/svg+xml",
    "image/jxl",
)


class Window(Adw.ApplicationWindow):
    """One window, one document (multi-document is out of scope for v1)."""

    __gtype_name__ = "Ganot8Window"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1100, 760)
        self._document: Document | None = None

        self._build_ui()
        self._install_actions()
        self._install_drop_target()
        self._update_sensitivity()

    # -- construction ----------------------------------------------------

    def _build_ui(self) -> None:
        self._toasts = Adw.ToastOverlay()
        self.set_content(self._toasts)

        toolbar_view = Adw.ToolbarView()
        self._toasts.set_child(toolbar_view)
        toolbar_view.add_top_bar(self._build_header())

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._banner = Adw.Banner(revealed=False)
        self._banner.set_button_label("Dismiss")
        self._banner.connect("button-clicked", lambda *_: self._banner.set_revealed(False))
        content.append(self._banner)

        self._stack = Gtk.Stack(vexpand=True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.add_named(self._build_empty_state(), "empty")
        self._stack.add_named(self._build_canvas(), "canvas")
        self._stack.set_visible_child_name("empty")
        content.append(self._stack)

        toolbar_view.set_content(content)

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()

        open_button = Gtk.Button(label="Open")
        open_button.set_tooltip_text("Open an image (Ctrl+O)")
        open_button.set_action_name("win.open")
        header.pack_start(open_button)

        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        zoom_box.add_css_class("linked")
        zoom_out = Gtk.Button(icon_name="zoom-out-symbolic")
        zoom_out.set_tooltip_text("Zoom out (Ctrl+minus)")
        zoom_out.set_action_name("win.zoom-out")
        self._zoom_label_button = Gtk.Button(label="100%")
        self._zoom_label_button.set_tooltip_text("Zoom to fit (Ctrl+0)")
        self._zoom_label_button.set_action_name("win.zoom-fit")
        zoom_in = Gtk.Button(icon_name="zoom-in-symbolic")
        zoom_in.set_tooltip_text("Zoom in (Ctrl+plus)")
        zoom_in.set_action_name("win.zoom-in")
        for widget in (zoom_out, self._zoom_label_button, zoom_in):
            zoom_box.append(widget)
        header.pack_start(zoom_box)

        self._export_button = Gtk.Button(label="Export")
        self._export_button.add_css_class("suggested-action")
        self._export_button.set_tooltip_text("Export a flattened copy (Ctrl+S)")
        self._export_button.set_action_name("win.export")
        header.pack_end(self._export_button)

        menu = Gio.Menu()
        file_section = Gio.Menu()
        file_section.append("Open…", "win.open")
        file_section.append("Export As…", "win.export-as")
        menu.append_section(None, file_section)
        view_section = Gio.Menu()
        view_section.append("Zoom to Fit", "win.zoom-fit")
        view_section.append("Actual Size", "win.zoom-100")
        menu.append_section(None, view_section)
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "win.show-help-overlay")
        app_section.append(f"About {APP_NAME}", "app.about")
        menu.append_section(None, app_section)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_button.set_tooltip_text("Main menu")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        self._title = Adw.WindowTitle(title=APP_NAME, subtitle="")
        header.set_title_widget(self._title)
        return header

    def _build_empty_state(self) -> Gtk.Widget:
        status = Adw.StatusPage(
            icon_name="image-x-generic-symbolic",
            title="No Image Open",
            description="Open an image or drop one here to start annotating.",
        )
        button = Gtk.Button(label="Open Image…")
        button.add_css_class("pill")
        button.add_css_class("suggested-action")
        button.set_halign(Gtk.Align.CENTER)
        button.set_action_name("win.open")
        status.set_child(button)
        return status

    def _build_canvas(self) -> Gtk.Widget:
        self._canvas = Canvas()
        self._canvas.connect("zoom-changed", self._on_zoom_changed)

        self._scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._scroller.add_css_class("ganot8-canvas-area")
        self._scroller.set_child(self._canvas)
        self._canvas.set_scroller(self._scroller)
        return self._scroller

    def _install_actions(self) -> None:
        for name, callback in (
            ("open", self._action_open),
            ("export", self._action_export),
            ("export-as", self._action_export_as),
            ("zoom-in", lambda *_: self._canvas.zoom_in()),
            ("zoom-out", lambda *_: self._canvas.zoom_out()),
            ("zoom-fit", lambda *_: self._canvas.zoom_fit()),
            ("zoom-100", lambda *_: self._canvas.zoom_actual()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _install_drop_target(self) -> None:
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

    # -- document handling -----------------------------------------------

    def open_path(self, path: str | Path) -> bool:
        """Load ``path`` into this window. Returns True on success."""
        try:
            loaded = load(path)
        except UnsupportedImageError as error:
            self._show_error("Could not open image", str(error))
            return False
        except Exception as error:  # defensive: a decoder can fail in novel ways
            log.exception("unexpected failure loading %s", path)
            self._show_error("Could not open image", f"{Path(path).name}: {error}")
            return False

        self.set_document(Document(loaded))
        for warning in loaded.warnings:
            self._banner.set_title(warning)
            self._banner.set_revealed(True)
        return True

    def set_document(self, document: Document) -> None:
        self._document = document
        self._canvas.set_document(document)
        self._stack.set_visible_child_name("canvas")
        self._update_title()
        self._update_sensitivity()

    @property
    def document(self) -> Document | None:
        return self._document

    def _update_title(self) -> None:
        if self._document is None:
            self._title.set_title(APP_NAME)
            self._title.set_subtitle("")
            self.set_title(APP_NAME)
            return
        name = self._document.display_name
        width, height = self._document.size
        loader = self._document.loaded.loader
        detail = f"{width} × {height}"
        if loader == "gdkpixbuf":
            detail += "  ·  via GdkPixbuf"
        self._title.set_title(name)
        self._title.set_subtitle(detail)
        self.set_title(f"{name} — {APP_NAME}")

    def _update_sensitivity(self) -> None:
        has_document = self._document is not None
        for name in ("export", "export-as", "zoom-in", "zoom-out", "zoom-fit", "zoom-100"):
            action = self.lookup_action(name)
            if action is not None:
                action.set_enabled(has_document)

    def _on_zoom_changed(self, _canvas, zoom: float) -> None:
        self._zoom_label_button.set_label(f"{round(zoom * 100)}%")

    # -- actions ---------------------------------------------------------

    def _action_open(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Open Image")
        dialog.set_filters(self._open_filters())
        dialog.open(self, None, self._on_open_response)

    def _open_filters(self) -> Gio.ListStore:
        store = Gio.ListStore.new(Gtk.FileFilter)
        images = Gtk.FileFilter(name="Images")
        for mime in _OPENABLE_MIME:
            images.add_mime_type(mime)
        store.append(images)
        every = Gtk.FileFilter(name="All files")
        every.add_pattern("*")
        store.append(every)
        return store

    def _on_open_response(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self._show_error("Could not open image", error.message)
            return
        if file is not None and file.get_path():
            self.open_path(file.get_path())

    def _action_export(self, *_args) -> None:
        """Ctrl+S: export a flattened copy, never touching the original."""
        if self._document is None:
            return
        target = exporter.default_export_path(self._document.source_path)
        if target.exists():
            self._action_export_as()
            return
        self._write_export(target)

    def _action_export_as(self, *_args) -> None:
        if self._document is None:
            return
        suggested = exporter.default_export_path(self._document.source_path)
        dialog = Gtk.FileDialog(title="Export Image", initial_name=suggested.name)
        if self._document.source_path is not None:
            parent = Gio.File.new_for_path(str(suggested.parent))
            dialog.set_initial_folder(parent)
        dialog.set_filters(self._export_filters())
        dialog.save(self, None, self._on_export_response)

    def _export_filters(self) -> Gio.ListStore:
        store = Gio.ListStore.new(Gtk.FileFilter)
        for fmt in exporter.EXPORT_FORMATS:
            file_filter = Gtk.FileFilter(name=fmt.label)
            file_filter.add_mime_type(fmt.mime)
            for extension in fmt.extensions:
                file_filter.add_pattern(f"*{extension}")
            store.append(file_filter)
        return store

    def _on_export_response(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self._show_error("Could not export image", error.message)
            return
        if file is not None and file.get_path():
            self._write_export(Path(file.get_path()))

    def _write_export(self, target: Path) -> None:
        if self._document is None:
            return
        source = self._document.source_path
        if source is not None and target.resolve() == source.resolve():
            self._show_error(
                "Refusing to overwrite the original",
                "Ganot8 exports a copy so the original image stays intact.\n"
                "Choose a different filename.",
            )
            return
        try:
            written = exporter.export(self._document, target)
        except Exception as error:
            log.exception("export to %s failed", target)
            self._show_error("Could not export image", f"{target.name}: {error}")
            return

        toast = Adw.Toast(title=f"Exported {written.name}")
        toast.set_button_label("Show in Files")
        toast.connect("button-clicked", lambda *_: self._reveal(written))
        self._toasts.add_toast(toast)

    def _reveal(self, path: Path) -> None:
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(path)))
        launcher.open_containing_folder(self, None, None)

    # -- drag and drop ---------------------------------------------------

    def _on_drop(self, _target, value, _x: float, _y: float) -> bool:
        files = value.get_files() if isinstance(value, Gdk.FileList) else []
        paths = [f.get_path() for f in files if f.get_path()]
        if not paths:
            return False
        if len(paths) > 1:
            self._banner.set_title(
                f"{len(paths)} files dropped; opening {Path(paths[0]).name} only."
            )
            self._banner.set_revealed(True)
        return self.open_path(paths[0])

    # -- feedback --------------------------------------------------------

    def _show_error(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "Close")
        dialog.set_default_response("ok")
        dialog.present(self)
