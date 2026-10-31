"""The main window: header bar, tool strip, canvas, style sidebar."""

from __future__ import annotations

import logging
from pathlib import Path

from . import gi_init  # noqa: F401
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_NAME
from .annotations import STYLE_COLOR, STYLE_FILLED, STYLE_OPACITY, STYLE_STROKE_WIDTH
from .canvas import Canvas
from .document import Document
from .history import Reorder, StateChange
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
        self.set_default_size(1200, 800)
        self._document: Document | None = None
        self._history_handler = 0
        #: Guards against style widgets echoing their own programmatic updates.
        self._syncing = False

        self._build_ui()
        self._install_actions()
        self._install_drop_target()
        self._update_sensitivity()
        self._sync_style_controls()

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
        self._stack.add_named(self._build_editor(), "canvas")
        self._stack.set_visible_child_name("empty")
        content.append(self._stack)

        toolbar_view.set_content(content)

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()

        open_button = Gtk.Button(label="Open")
        open_button.set_tooltip_text("Open an image (Ctrl+O)")
        open_button.set_action_name("win.open")
        header.pack_start(open_button)

        history_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        history_box.add_css_class("linked")
        self._undo_button = Gtk.Button(icon_name="edit-undo-symbolic")
        self._undo_button.set_action_name("win.undo")
        self._redo_button = Gtk.Button(icon_name="edit-redo-symbolic")
        self._redo_button.set_action_name("win.redo")
        history_box.append(self._undo_button)
        history_box.append(self._redo_button)
        header.pack_start(history_box)

        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
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
        edit_section = Gio.Menu()
        edit_section.append("Select All", "win.select-all")
        edit_section.append("Delete Selection", "win.delete")
        edit_section.append("Raise", "win.raise-annotation")
        edit_section.append("Lower", "win.lower-annotation")
        menu.append_section(None, edit_section)
        view_section = Gio.Menu()
        view_section.append("Zoom to Fit", "win.zoom-fit")
        view_section.append("Actual Size", "win.zoom-100")
        view_section.append("Style Sidebar", "win.toggle-sidebar")
        menu.append_section(None, view_section)
        app_section = Gio.Menu()
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

    def _build_editor(self) -> Gtk.Widget:
        self._canvas = Canvas()
        self._canvas.connect("zoom-changed", self._on_zoom_changed)
        self._canvas.connect("selection-changed", self._on_selection_changed)
        self._canvas.connect("tool-changed", self._on_tool_changed)

        self._scroller = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._scroller.add_css_class("ganot8-canvas-area")
        self._scroller.set_child(self._canvas)
        self._canvas.set_scroller(self._scroller)

        middle = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        middle.append(self._build_tool_strip())
        middle.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        middle.append(self._scroller)

        self._split = Adw.OverlaySplitView(
            sidebar_position=Gtk.PackType.END,
            show_sidebar=True,
            min_sidebar_width=260,
            max_sidebar_width=320,
        )
        self._split.set_content(middle)
        self._split.set_sidebar(self._build_style_sidebar())
        return self._split

    def _build_tool_strip(self) -> Gtk.Widget:
        strip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        strip.add_css_class("ganot8-tool-strip")
        strip.set_margin_top(8)
        strip.set_margin_bottom(8)
        strip.set_margin_start(6)
        strip.set_margin_end(6)

        self._tool_buttons: dict[str, Gtk.ToggleButton] = {}
        group: Gtk.ToggleButton | None = None
        for tool in self._canvas.available_tools():
            button = Gtk.ToggleButton(icon_name=tool.icon_name)
            button.set_tooltip_text(tool.tooltip or tool.label)
            button.add_css_class("flat")
            if group is None:
                group = button
            else:
                button.set_group(group)
            button.connect("toggled", self._on_tool_button_toggled, tool.name)
            self._tool_buttons[tool.name] = button
            strip.append(button)

        active = self._tool_buttons.get(self._canvas.tool_name)
        if active is not None:
            active.set_active(True)
        return strip

    def _build_style_sidebar(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        self._style_group = Adw.PreferencesGroup(title="Style")
        page.add(self._style_group)

        self._colour_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self._colour_button.set_valign(Gtk.Align.CENTER)
        self._colour_button.connect("notify::rgba", self._on_colour_changed)
        self._colour_row = Adw.ActionRow(title="Colour")
        self._colour_row.add_suffix(self._colour_button)
        self._colour_row.set_activatable_widget(self._colour_button)
        self._style_group.add(self._colour_row)

        self._width_row = Adw.SpinRow(
            title="Line Width",
            adjustment=Gtk.Adjustment(value=3, lower=1, upper=40, step_increment=1),
        )
        self._width_row.connect("notify::value", self._on_width_changed)
        self._style_group.add(self._width_row)

        self._opacity_row = Adw.SpinRow(
            title="Opacity",
            subtitle="Percent",
            adjustment=Gtk.Adjustment(value=100, lower=5, upper=100, step_increment=5),
        )
        self._opacity_row.connect("notify::value", self._on_opacity_changed)
        self._style_group.add(self._opacity_row)

        self._filled_row = Adw.SwitchRow(title="Filled")
        self._filled_row.connect("notify::active", self._on_filled_changed)
        self._style_group.add(self._filled_row)

        arrange = Adw.PreferencesGroup(title="Arrange")
        page.add(arrange)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        buttons.set_margin_top(6)
        for label, action in (
            ("Raise", "win.raise-annotation"),
            ("Lower", "win.lower-annotation"),
            ("Delete", "win.delete"),
        ):
            button = Gtk.Button(label=label)
            button.set_action_name(action)
            if label == "Delete":
                button.add_css_class("destructive-action")
            buttons.append(button)
        row = Adw.PreferencesRow(activatable=False)
        row.set_child(buttons)
        arrange.add(row)

        self._selection_label = Gtk.Label(xalign=0)
        self._selection_label.add_css_class("dim-label")
        self._selection_label.add_css_class("caption")
        self._selection_label.set_margin_top(10)
        self._selection_label.set_wrap(True)
        info = Adw.PreferencesRow(activatable=False)
        info.set_child(self._selection_label)
        arrange.add(info)
        return page

    def _install_actions(self) -> None:
        for name, callback in (
            ("open", self._action_open),
            ("export", self._action_export),
            ("export-as", self._action_export_as),
            ("zoom-in", lambda *_: self._canvas.zoom_in()),
            ("zoom-out", lambda *_: self._canvas.zoom_out()),
            ("zoom-fit", lambda *_: self._canvas.zoom_fit()),
            ("zoom-100", lambda *_: self._canvas.zoom_actual()),
            ("undo", self._action_undo),
            ("redo", self._action_redo),
            ("delete", lambda *_: self._canvas.delete_selection()),
            ("select-all", lambda *_: self._canvas.select_all()),
            ("deselect", lambda *_: self._canvas.clear_selection()),
            ("raise-annotation", lambda *_: self._reorder(+1)),
            ("lower-annotation", lambda *_: self._reorder(-1)),
            ("toggle-sidebar", self._action_toggle_sidebar),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        tool_action = Gio.SimpleAction.new_stateful(
            "tool", GLib.VariantType.new("s"), GLib.Variant.new_string("select")
        )
        tool_action.connect("activate", self._action_set_tool)
        self.add_action(tool_action)

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
        if self._document is not None and self._history_handler:
            self._document.history.disconnect(self._history_handler)
        self._document = document
        self._history_handler = document.history.connect(
            "changed", lambda *_: self._update_sensitivity()
        )
        self._canvas.set_document(document)
        self._stack.set_visible_child_name("canvas")
        self._update_title()
        self._update_sensitivity()

    @property
    def document(self) -> Document | None:
        return self._document

    @property
    def canvas(self) -> Canvas:
        return self._canvas

    def _update_title(self) -> None:
        if self._document is None:
            self._title.set_title(APP_NAME)
            self._title.set_subtitle("")
            self.set_title(APP_NAME)
            return
        name = self._document.display_name
        width, height = self._document.size
        detail = f"{width} × {height}"
        if self._document.loaded.loader == "gdkpixbuf":
            detail += "  ·  via GdkPixbuf"
        self._title.set_title(name)
        self._title.set_subtitle(detail)
        self.set_title(f"{name} — {APP_NAME}")

    def _update_sensitivity(self) -> None:
        has_document = self._document is not None
        for name in (
            "export",
            "export-as",
            "zoom-in",
            "zoom-out",
            "zoom-fit",
            "zoom-100",
            "select-all",
            "toggle-sidebar",
        ):
            action = self.lookup_action(name)
            if action is not None:
                action.set_enabled(has_document)

        has_selection = bool(self._canvas.selection) if has_document else False
        single = len(self._canvas.selection) == 1 if has_document else False
        for name, enabled in (
            ("delete", has_selection),
            ("deselect", has_selection),
            ("raise-annotation", single),
            ("lower-annotation", single),
        ):
            action = self.lookup_action(name)
            if action is not None:
                action.set_enabled(enabled)

        history = self._document.history if has_document else None
        can_undo = bool(history and history.can_undo)
        can_redo = bool(history and history.can_redo)
        for name, enabled in (("undo", can_undo), ("redo", can_redo)):
            action = self.lookup_action(name)
            if action is not None:
                action.set_enabled(enabled)
        self._undo_button.set_tooltip_text(
            f"Undo {history.undo_label} (Ctrl+Z)" if can_undo else "Nothing to undo"
        )
        self._redo_button.set_tooltip_text(
            f"Redo {history.redo_label} (Ctrl+Shift+Z)" if can_redo else "Nothing to redo"
        )

    # -- style sidebar ---------------------------------------------------

    def _on_selection_changed(self, *_args) -> None:
        self._update_sensitivity()
        self._sync_style_controls()

    def _on_tool_changed(self, _canvas, name: str) -> None:
        button = self._tool_buttons.get(name)
        if button is not None and not button.get_active():
            button.set_active(True)
        action = self.lookup_action("tool")
        if action is not None:
            action.set_state(GLib.Variant.new_string(name))
        self._sync_style_controls()

    def _on_tool_button_toggled(self, button: Gtk.ToggleButton, name: str) -> None:
        if button.get_active():
            self._canvas.activate_tool(name)

    def _style_subjects(self) -> list:
        """Annotations the style controls act on, or [] to edit the defaults."""
        return list(self._canvas.selection)

    def _sync_style_controls(self) -> None:
        """Push current values into the widgets without triggering handlers."""
        self._syncing = True
        try:
            subjects = self._style_subjects()
            if subjects:
                reference = subjects[0]
                colour = reference.color
                width = reference.stroke_width
                opacity = reference.opacity
                filled = bool(getattr(reference, "filled", False))
                properties = reference.style_properties
                count = len(subjects)
                self._selection_label.set_text(
                    f"{count} annotation{'s' if count != 1 else ''} selected."
                )
            else:
                style = self._canvas.tool_style
                colour = style["color"]
                width = style["stroke_width"]
                opacity = style["opacity"]
                filled = bool(style["filled"])
                tool = self._canvas.tool
                properties = (STYLE_COLOR, STYLE_STROKE_WIDTH, STYLE_OPACITY, STYLE_FILLED)
                label = tool.label if tool is not None else ""
                self._selection_label.set_text(
                    f"No selection. Changes apply to new {label} annotations."
                )

            red, green, blue, alpha = colour
            self._colour_button.set_rgba(Gdk.RGBA(red=red, green=green, blue=blue, alpha=alpha))
            self._width_row.set_value(float(width))
            self._opacity_row.set_value(round(float(opacity) * 100))
            self._filled_row.set_active(filled)

            self._colour_row.set_visible(STYLE_COLOR in properties)
            self._width_row.set_visible(STYLE_STROKE_WIDTH in properties)
            self._opacity_row.set_visible(STYLE_OPACITY in properties)
            self._filled_row.set_visible(STYLE_FILLED in properties)
        finally:
            self._syncing = False

    def _apply_style(self, attribute: str, value, label: str) -> None:
        """Apply a style change to the selection, or to the tool defaults."""
        if self._syncing:
            return
        subjects = [s for s in self._style_subjects() if hasattr(s, attribute)]
        if not subjects:
            self._canvas.tool_style[attribute] = value
            return
        before = [s.state() for s in subjects]
        for subject in subjects:
            setattr(subject, attribute, value)
        # Keep the defaults in step, so the next annotation matches.
        self._canvas.tool_style[attribute] = value
        self._document.history.push(
            StateChange(self._document, subjects, before, label=label)
        )

    def _on_colour_changed(self, button: Gtk.ColorDialogButton, _param) -> None:
        rgba = button.get_rgba()
        self._apply_style(
            "color", (rgba.red, rgba.green, rgba.blue, rgba.alpha), "Change Colour"
        )

    def _on_width_changed(self, row: Adw.SpinRow, _param) -> None:
        self._apply_style("stroke_width", float(row.get_value()), "Change Width")

    def _on_opacity_changed(self, row: Adw.SpinRow, _param) -> None:
        self._apply_style("opacity", float(row.get_value()) / 100.0, "Change Opacity")

    def _on_filled_changed(self, row: Adw.SwitchRow, _param) -> None:
        self._apply_style("filled", bool(row.get_active()), "Change Fill")

    # -- actions ---------------------------------------------------------

    def _action_set_tool(self, action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        self._canvas.activate_tool(parameter.get_string())

    def _action_undo(self, *_args) -> None:
        if self._document is not None and self._document.history.undo():
            self._canvas.queue_draw()

    def _action_redo(self, *_args) -> None:
        if self._document is not None and self._document.history.redo():
            self._canvas.queue_draw()

    def _action_toggle_sidebar(self, *_args) -> None:
        self._split.set_show_sidebar(not self._split.get_show_sidebar())

    def _reorder(self, direction: int) -> None:
        if self._document is None or len(self._canvas.selection) != 1:
            return
        annotation = self._canvas.selection[0]
        index = self._document.annotations.index(annotation)
        label = "Raise" if direction > 0 else "Lower"
        self._document.history.push(
            Reorder(self._document, annotation, index + direction, label=label)
        )

    def _on_zoom_changed(self, _canvas, zoom: float) -> None:
        self._zoom_label_button.set_label(f"{round(zoom * 100)}%")

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
            dialog.set_initial_folder(Gio.File.new_for_path(str(suggested.parent)))
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
