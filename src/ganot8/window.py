"""The main window: header bar, tool strip, canvas, style sidebar."""

from __future__ import annotations

import logging
from pathlib import Path

from . import gi_init  # noqa: F401
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import APP_NAME
from .annotations import (
    STYLE_BACKGROUND,
    STYLE_COLOR,
    STYLE_FILLED,
    STYLE_FONT,
    STYLE_BACKGROUND_COLOR,
    STYLE_OPACITY,
    STYLE_PADDING,
    STYLE_REDACT_STYLE,
    STYLE_STRENGTH,
    STYLE_STROKE_WIDTH,
    STYLE_TEXT_COLOR,
    STYLE_WAVY,
)
from . import clipboard, portal, resources
from .canvas import Canvas
from .dialogs import ExportOptionsDialog
from .effects import REDACT_STYLES, STYLE_SOLID
from .document import Document
from .history import Reorder, StateChange
from .imageio import exporter, project
from .imageio.loader import LoadedImage, UnsupportedImageError, load
from .settings import Settings, restore_tool_styles
from .shortcuts import present_shortcuts

log = logging.getLogger(__name__)

#: Inset for content placed directly in an Adw.PreferencesRow, which - unlike
#: ActionRow and friends - supplies no padding of its own.
_ROW_PADDING = 12

#: Style attributes the sidebar has a widget for.
_REDACT_STYLE_LABELS = ("Solid block", "Blur", "Pixelate")

_STYLE_WIDGET_KEYS = (
    STYLE_REDACT_STYLE,
    STYLE_STRENGTH,
    STYLE_COLOR,
    STYLE_FONT,
    STYLE_STROKE_WIDTH,
    STYLE_OPACITY,
    STYLE_FILLED,
    STYLE_WAVY,
    STYLE_BACKGROUND,
    STYLE_BACKGROUND_COLOR,
    STYLE_PADDING,
    STYLE_TEXT_COLOR,
)

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

    def __init__(self, *, settings: Settings | None = None, **kwargs):
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.settings = settings if settings is not None else Settings()
        self.set_default_size(
            self.settings.get_int("window-width"),
            self.settings.get_int("window-height"),
        )
        if self.settings.get_boolean("window-maximized"):
            self.maximize()
        self._document: Document | None = None
        self._history_handler = 0
        #: Guards against style widgets echoing their own programmatic updates.
        self._syncing = False
        self._text_popover: Gtk.Popover | None = None
        self._text_cancelled = False
        self._export_format = self.settings.get_string("export-format")
        self._export_quality = self.settings.get_int("export-quality")
        #: Set once the user has agreed to lose unsaved work, so the second
        #: close attempt is not intercepted again.
        self._force_close = False
        self._after_save = None

        resources.install_icons()
        self._build_ui()
        self._install_actions()
        self._install_drop_target()
        restore_tool_styles(self._canvas, self.settings)
        self._split.set_show_sidebar(self.settings.get_boolean("sidebar-visible"))
        self.connect("close-request", self._on_close_request)
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
        edit_section.append("Copy to Clipboard", "win.copy")
        edit_section.append("Select All", "win.select-all")
        edit_section.append("Delete Selection", "win.delete")
        edit_section.append("Raise", "win.raise-annotation")
        edit_section.append("Lower", "win.lower-annotation")
        menu.append_section(None, edit_section)
        image_section = Gio.Menu()
        image_section.append("Rotate Left", "win.rotate-left")
        image_section.append("Rotate Right", "win.rotate-right")
        menu.append_section(None, image_section)
        view_section = Gio.Menu()
        view_section.append("Zoom to Fit", "win.zoom-fit")
        view_section.append("Actual Size", "win.zoom-100")
        view_section.append("Style Sidebar", "win.toggle-sidebar")
        menu.append_section(None, view_section)
        app_section = Gio.Menu()
        app_section.append("Keyboard Shortcuts", "win.shortcuts")
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
        self._canvas.connect("text-edit-requested", self._on_text_edit_requested)

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

        redact_styles = Gtk.StringList()
        for label in _REDACT_STYLE_LABELS:
            redact_styles.append(label)
        self._redact_style_row = Adw.ComboRow(
            title="Style",
            subtitle="A solid block is the safe choice for anything sensitive",
            model=redact_styles,
        )
        self._redact_style_row.connect("notify::selected", self._on_redact_style_changed)
        self._style_group.add(self._redact_style_row)

        self._strength_row = Adw.SpinRow(
            title="Strength",
            subtitle="Below a floor the content stays readable, so it cannot go weaker",
            adjustment=Gtk.Adjustment(value=50, lower=1, upper=100, step_increment=5),
        )
        self._strength_row.connect("notify::value", self._on_strength_changed)
        self._style_group.add(self._strength_row)

        self._colour_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self._colour_button.set_valign(Gtk.Align.CENTER)
        self._colour_button.connect("notify::rgba", self._on_colour_changed)
        self._colour_row = Adw.ActionRow(title="Colour")
        self._colour_row.add_suffix(self._colour_button)
        self._colour_row.set_activatable_widget(self._colour_button)
        self._style_group.add(self._colour_row)

        self._font_button = Gtk.FontDialogButton(dialog=Gtk.FontDialog())
        self._font_button.set_valign(Gtk.Align.CENTER)
        self._font_button.connect("notify::font-desc", self._on_font_changed)
        self._font_row = Adw.ActionRow(title="Font")
        self._font_row.add_suffix(self._font_button)
        self._font_row.set_activatable_widget(self._font_button)
        self._style_group.add(self._font_row)

        self._text_colour_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self._text_colour_button.set_valign(Gtk.Align.CENTER)
        self._text_colour_button.connect("notify::rgba", self._on_text_colour_changed)
        self._text_colour_row = Adw.ActionRow(title="Number Colour")
        self._text_colour_row.add_suffix(self._text_colour_button)
        self._text_colour_row.set_activatable_widget(self._text_colour_button)
        self._style_group.add(self._text_colour_row)

        self._background_colour_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self._background_colour_button.set_valign(Gtk.Align.CENTER)
        self._background_colour_button.connect(
            "notify::rgba", self._on_background_colour_changed
        )
        self._background_colour_row = Adw.ActionRow(title="Background Colour")
        self._background_colour_row.add_suffix(self._background_colour_button)
        self._background_colour_row.set_activatable_widget(self._background_colour_button)
        self._style_group.add(self._background_colour_row)

        self._padding_row = Adw.SpinRow(
            title="Padding",
            adjustment=Gtk.Adjustment(value=6, lower=0, upper=40, step_increment=1),
        )
        self._padding_row.connect("notify::value", self._on_padding_changed)
        self._style_group.add(self._padding_row)

        self._width_row = Adw.SpinRow(
            title="Line Width",
            adjustment=Gtk.Adjustment(value=7, lower=1, upper=40, step_increment=1),
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

        self._wavy_row = Adw.SwitchRow(title="Wavy")
        self._wavy_row.connect("notify::active", self._on_wavy_changed)
        self._style_group.add(self._wavy_row)

        self._background_row = Adw.SwitchRow(
            title="Background", subtitle="Draw a plate behind the text"
        )
        self._background_row.connect("notify::active", self._on_background_changed)
        self._style_group.add(self._background_row)

        # "Arrange" alone said nothing about what it arranges, and Delete had
        # no business sitting under a stacking-order heading.
        arrange = Adw.PreferencesGroup(
            title="Arrange z-order",
            description="Which annotation is drawn on top where they overlap",
        )
        page.add(arrange)
        self._arrange_row = self._button_row(
            (
                (
                    "Raise",
                    "win.raise-annotation",
                    "Move one step towards the front (Ctrl+Page Up)",
                    None,
                ),
                (
                    "Lower",
                    "win.lower-annotation",
                    "Move one step towards the back (Ctrl+Page Down)",
                    None,
                ),
            )
        )
        arrange.add(self._arrange_row)

        selection = Adw.PreferencesGroup(title="Selection")
        page.add(selection)
        self._delete_row = self._button_row(
            (
                (
                    "Delete",
                    "win.delete",
                    "Remove the selected annotations (Delete)",
                    "destructive-action",
                ),
            )
        )
        selection.add(self._delete_row)

        self._selection_label = Gtk.Label(xalign=0)
        self._selection_label.add_css_class("dim-label")
        self._selection_label.add_css_class("caption")
        self._selection_label.set_margin_top(2)
        self._selection_label.set_margin_bottom(_ROW_PADDING)
        self._selection_label.set_margin_start(_ROW_PADDING)
        self._selection_label.set_margin_end(_ROW_PADDING)
        self._selection_label.set_wrap(True)
        info = Adw.PreferencesRow(activatable=False)
        info.set_child(self._selection_label)
        selection.add(info)
        return page

    @staticmethod
    def _button_row(entries) -> Adw.PreferencesRow:
        """A row of equal-width buttons, each wired to an action.

        The margins are not decoration. ``Adw.PreferencesRow`` is a plain list
        row and adds no padding of its own, unlike the ActionRow/SpinRow/
        SwitchRow used in the Style group, so without them the buttons sit
        flush against the card border. 12px matches the padding Adwaita gives
        those rows, so these line up with the controls above rather than
        running wider than them.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, homogeneous=True)
        box.set_margin_top(_ROW_PADDING)
        box.set_margin_bottom(_ROW_PADDING)
        box.set_margin_start(_ROW_PADDING)
        box.set_margin_end(_ROW_PADDING)
        for label, action, tooltip, css_class in entries:
            button = Gtk.Button(label=label)
            button.set_action_name(action)
            button.set_tooltip_text(tooltip)
            if css_class:
                button.add_css_class(css_class)
            box.append(button)
        row = Adw.PreferencesRow(activatable=False)
        row.set_child(box)
        return row

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
            ("save-project", self._action_save_project),
            ("overwrite-original", self._action_overwrite_original),
            ("burn-in", self._action_burn_in),
            ("paste", self._action_paste),
            ("copy", self._action_copy),
            ("screenshot", self._action_screenshot),
            ("shortcuts", lambda *_: present_shortcuts(self)),
            ("rotate-left", lambda *_: self._rotate(-90)),
            ("rotate-right", lambda *_: self._rotate(90)),
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
        """Load ``path`` into this window, as a project or a plain image."""
        path = Path(path)
        if project.looks_like_project(path):
            return self._open_project(path)
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
        self._show_warnings(loaded.warnings)
        return True

    def _open_project(self, path: Path) -> bool:
        try:
            document = Document.from_project(path)
        except project.ProjectError as error:
            self._show_error("Could not open project", str(error))
            return False
        except Exception as error:  # defensive
            log.exception("unexpected failure loading project %s", path)
            self._show_error("Could not open project", f"{path.name}: {error}")
            return False

        self.set_document(document)
        self._show_warnings(document.loaded.warnings)
        return True

    def _show_warnings(self, warnings) -> None:
        for warning in warnings:
            self._banner.set_title(warning)
            self._banner.set_revealed(True)

    def set_document(self, document: Document) -> None:
        if self._document is not None and self._history_handler:
            self._document.history.disconnect(self._history_handler)
        self._document = document
        self._history_handler = document.history.connect(
            "changed", lambda *_: self._update_sensitivity()
        )
        self._canvas.set_document(document)
        self._stack.set_visible_child_name("canvas")
        # Burn-in availability and the banner both depend on document content,
        # not just on history, so track the document itself.
        document.connect("changed", lambda *_: self._on_document_changed())
        self._update_title()
        self._update_sensitivity()
        self._update_redaction_banner()

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
            "save-project",
            "overwrite-original",
            "rotate-left",
            "rotate-right",
            "copy",
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

        burn_in = self.lookup_action("burn-in")
        if burn_in is not None:
            burn_in.set_enabled(has_document and self._document.has_redactions)

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

    def _on_document_changed(self) -> None:
        self._update_sensitivity()
        self._update_redaction_banner()

    def _update_redaction_banner(self) -> None:
        """Warn while a project holding redactions is open.

        The project keeps the unredacted original so the redaction stays
        editable; that is exactly why the file must not be passed around in
        place of an export (docs/SPEC.md section 6.3).
        """
        document = self._document
        show = bool(document is not None and document.is_project and document.has_redactions)
        if show:
            self._banner.set_title(
                "This project still contains the original, unredacted image. "
                "Share an export, not this file."
            )
            self._banner.set_revealed(True)
        elif self._banner.get_revealed() and self._banner.get_title().startswith(
            "This project still contains"
        ):
            self._banner.set_revealed(False)

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
                values = {key: getattr(reference, key, None) for key in _STYLE_WIDGET_KEYS}
                properties = reference.visible_style_properties()
                count = len(subjects)
                kinds = {s.label for s in subjects}
                what = next(iter(kinds)) if len(kinds) == 1 else "annotation"
                self._selection_label.set_text(
                    f"{count} {what.lower()}{'s' if count != 1 else ''} selected."
                )
            else:
                style = self._canvas.current_style()
                values = {key: style.get(key) for key in _STYLE_WIDGET_KEYS}
                properties = self._canvas.current_style_properties()
                tool = self._canvas.tool
                if properties:
                    self._selection_label.set_text(
                        f"No selection. Changes apply to the next {tool.label.lower()}."
                    )
                else:
                    self._selection_label.set_text(
                        "Pick a tool and drag on the image to add an annotation."
                    )

            colour = values.get(STYLE_COLOR) or (0, 0, 0, 1)
            redact_style = values.get(STYLE_REDACT_STYLE) or STYLE_SOLID
            if redact_style in REDACT_STYLES:
                self._redact_style_row.set_selected(REDACT_STYLES.index(redact_style))
            self._strength_row.set_value(float(values.get(STYLE_STRENGTH) or 50.0))

            red, green, blue, alpha = colour
            self._colour_button.set_rgba(Gdk.RGBA(red=red, green=green, blue=blue, alpha=alpha))
            self._set_colour_button(self._text_colour_button, values.get(STYLE_TEXT_COLOR))
            self._set_colour_button(
                self._background_colour_button, values.get(STYLE_BACKGROUND_COLOR)
            )
            self._padding_row.set_value(float(values.get(STYLE_PADDING) or 6.0))
            font = values.get(STYLE_FONT)
            if font:
                self._font_button.set_font_desc(Pango.FontDescription.from_string(font))
            self._width_row.set_value(float(values.get(STYLE_STROKE_WIDTH) or 3.0))
            self._opacity_row.set_value(round(float(values.get(STYLE_OPACITY) or 1.0) * 100))
            self._filled_row.set_active(bool(values.get(STYLE_FILLED)))
            self._wavy_row.set_active(bool(values.get(STYLE_WAVY)))
            self._background_row.set_active(bool(values.get(STYLE_BACKGROUND)))

            for key, row in (
                (STYLE_REDACT_STYLE, self._redact_style_row),
                (STYLE_STRENGTH, self._strength_row),
                (STYLE_COLOR, self._colour_row),
                (STYLE_TEXT_COLOR, self._text_colour_row),
                (STYLE_BACKGROUND_COLOR, self._background_colour_row),
                (STYLE_PADDING, self._padding_row),
                (STYLE_FONT, self._font_row),
                (STYLE_STROKE_WIDTH, self._width_row),
                (STYLE_OPACITY, self._opacity_row),
                (STYLE_FILLED, self._filled_row),
                (STYLE_WAVY, self._wavy_row),
                (STYLE_BACKGROUND, self._background_row),
            ):
                row.set_visible(key in properties)
            self._style_group.set_visible(bool(properties))
        finally:
            self._syncing = False

    def _apply_style(self, attribute: str, value, label: str) -> None:
        """Apply a style change to the selection, or to the tool defaults."""
        if self._syncing:
            return
        subjects = [s for s in self._style_subjects() if hasattr(s, attribute)]
        if not subjects:
            self._canvas.current_style()[attribute] = value
            return
        before = [s.state() for s in subjects]
        for subject in subjects:
            setattr(subject, attribute, value)
        # Keep the active tool's memory in step, so the next one matches.
        self._canvas.current_style()[attribute] = value
        self._document.history.push(
            StateChange(self._document, subjects, before, label=label)
        )

    def _on_colour_changed(self, button: Gtk.ColorDialogButton, _param) -> None:
        rgba = button.get_rgba()
        self._apply_style(
            "color", (rgba.red, rgba.green, rgba.blue, rgba.alpha), "Change Colour"
        )

    @staticmethod
    def _set_colour_button(button: Gtk.ColorDialogButton, colour) -> None:
        if not colour:
            return
        red, green, blue, alpha = colour
        button.set_rgba(Gdk.RGBA(red=red, green=green, blue=blue, alpha=alpha))

    def _on_text_colour_changed(self, button: Gtk.ColorDialogButton, _param) -> None:
        rgba = button.get_rgba()
        self._apply_style(
            "text_color",
            (rgba.red, rgba.green, rgba.blue, rgba.alpha),
            "Change Number Colour",
        )

    def _on_background_colour_changed(self, button: Gtk.ColorDialogButton, _param) -> None:
        rgba = button.get_rgba()
        self._apply_style(
            "background_color",
            (rgba.red, rgba.green, rgba.blue, rgba.alpha),
            "Change Background Colour",
        )

    def _on_padding_changed(self, row: Adw.SpinRow, _param) -> None:
        self._apply_style("padding", float(row.get_value()), "Change Padding")

    def _on_width_changed(self, row: Adw.SpinRow, _param) -> None:
        self._apply_style("stroke_width", float(row.get_value()), "Change Width")

    def _on_opacity_changed(self, row: Adw.SpinRow, _param) -> None:
        self._apply_style("opacity", float(row.get_value()) / 100.0, "Change Opacity")

    def _on_filled_changed(self, row: Adw.SwitchRow, _param) -> None:
        self._apply_style("filled", bool(row.get_active()), "Change Fill")
        # Filling hides Line Width, so the rows have to be re-evaluated.
        self._sync_style_controls()

    def _on_redact_style_changed(self, row: Adw.ComboRow, _param) -> None:
        index = row.get_selected()
        if 0 <= index < len(REDACT_STYLES):
            self._apply_style("style", REDACT_STYLES[index], "Change Redaction Style")
            # Solid shows Colour; blur and pixelate show Strength instead.
            self._sync_style_controls()

    def _on_strength_changed(self, row: Adw.SpinRow, _param) -> None:
        self._apply_style("strength", float(row.get_value()), "Change Strength")

    def _on_wavy_changed(self, row: Adw.SwitchRow, _param) -> None:
        self._apply_style("wavy", bool(row.get_active()), "Change Underline")

    def _on_background_changed(self, row: Adw.SwitchRow, _param) -> None:
        self._apply_style("background", bool(row.get_active()), "Change Background")
        # The plate's colour and padding only apply when the plate is drawn.
        self._sync_style_controls()

    def _on_font_changed(self, button: Gtk.FontDialogButton, _param) -> None:
        description = button.get_font_desc()
        if description is not None:
            self._apply_style("font", description.to_string(), "Change Font")

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

    def _rotate(self, degrees: int) -> None:
        if self._document is None:
            return
        self._canvas.clear_selection()
        if self._document.rotate_by(degrees):
            self._canvas.zoom_fit()
            self._update_title()

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
        everything = Gtk.FileFilter(name="Images and projects")
        for mime in _OPENABLE_MIME:
            everything.add_mime_type(mime)
        everything.add_pattern(f"*{project.SUFFIX}")
        store.append(everything)
        projects = Gtk.FileFilter(name="Ganot8 projects")
        projects.add_pattern(f"*{project.SUFFIX}")
        store.append(projects)
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
        target = exporter.default_export_path(self._document.export_basis)
        if target.exists():
            self._action_export_as()
            return
        self._write_export(target)

    def _action_export_as(self, *_args) -> None:
        """Choose format and quality, then where to put it."""
        if self._document is None:
            return
        options = ExportOptionsDialog(
            initial_format=self._export_format, initial_quality=self._export_quality
        )
        options.choose(self, self._on_export_options_chosen)

    def _on_export_options_chosen(self, export_format, quality: int) -> None:
        self._export_format = export_format.name
        self._export_quality = quality

        suggested = exporter.default_export_path(self._document.export_basis)
        suggested = suggested.with_suffix(export_format.extensions[0])
        dialog = Gtk.FileDialog(title="Export Image", initial_name=suggested.name)
        if suggested.parent.is_dir():
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

    def _write_export(self, target: Path, *, allow_source: bool = False) -> None:
        if self._document is None:
            return
        source = self._document.export_basis
        if not allow_source and source is not None and source.exists() and (
            target.resolve() == source.resolve()
        ):
            self._show_error(
                "Refusing to overwrite the original",
                "Ganot8 exports a copy so the original image stays intact.\n"
                "Choose a different filename, or use Overwrite Original from the menu.",
            )
            return
        try:
            written = exporter.export(
                self._document, target, jpeg_quality=self._export_quality
            )
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

    # -- clipboard and screenshots ---------------------------------------

    def _target_window(self) -> "Window":
        """Where a newly acquired image should go.

        A window that already holds something opens a new one rather than
        replacing it, so pasting can never discard work.
        """
        if self._document is None:
            return self
        application = self.get_application()
        if application is None:
            return self
        fresh = Window(application=application, settings=self.settings)
        fresh.present()
        return fresh

    def adopt_image(self, image, *, name: str, loader: str) -> None:
        """Show an image that came from somewhere other than a file."""
        self.set_document(Document(LoadedImage(image=image, path=None, format=name, loader=loader)))
        self._update_title()

    def _action_paste(self, *_args) -> None:
        board = Gdk.Display.get_default().get_clipboard()

        def arrived(image) -> None:
            self._target_window().adopt_image(image, name="Pasted", loader="clipboard")

        clipboard.paste_image(
            board, arrived, lambda message: self._show_error("Nothing to paste", message)
        )

    def _action_copy(self, *_args) -> None:
        if self._document is None:
            return
        try:
            flattened = exporter.flatten(self._document)
        except Exception as error:
            log.exception("could not flatten for the clipboard")
            self._show_error("Could not copy image", str(error))
            return
        clipboard.copy_image(Gdk.Display.get_default().get_clipboard(), flattened)
        self._toasts.add_toast(Adw.Toast(title="Copied to clipboard"))

    def _action_screenshot(self, *_args) -> None:
        if not portal.is_available():
            self._show_error(
                "Screenshots are unavailable",
                "No desktop portal is running, so Ganot8 cannot capture the screen.\n"
                "Take a screenshot another way and paste it with Ctrl+V.",
            )
            return

        def captured(uri: str) -> None:
            path = Path(Gio.File.new_for_uri(uri).get_path() or "")
            if not path.is_file():
                self._show_error("Could not read the screenshot", uri)
                return
            try:
                loaded = load(path)
            except UnsupportedImageError as error:
                self._show_error("Could not read the screenshot", str(error))
                return
            # Deliberately untitled: the portal writes to a temporary location,
            # so exporting beside it would scatter files somewhere unhelpful.
            self._target_window().adopt_image(
                loaded.image, name="Screenshot", loader="portal"
            )

        portal.take_screenshot(
            captured, lambda message: self._show_error("Screenshot failed", message)
        )

    # -- projects --------------------------------------------------------

    def _action_save_project(self, *_args) -> None:
        self._save_project_then(None)

    def _save_project_then(self, on_saved) -> None:
        """Save, then run ``on_saved`` if (and only if) it actually succeeded."""
        self._after_save = on_saved
        if self._document is None:
            return
        suggested = self._document.project_path or project.default_project_path(
            self._document.export_basis
        )
        dialog = Gtk.FileDialog(title="Save Project", initial_name=suggested.name)
        if suggested.parent.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(suggested.parent)))
        dialog.set_filters(self._project_filters())
        dialog.save(self, None, self._on_save_project_response)

    def _project_filters(self) -> Gio.ListStore:
        store = Gio.ListStore.new(Gtk.FileFilter)
        projects = Gtk.FileFilter(name="Ganot8 projects")
        projects.add_pattern(f"*{project.SUFFIX}")
        projects.add_mime_type(project.MIME_TYPE)
        store.append(projects)
        return store

    def _on_save_project_response(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error as error:
            self._after_save = None
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self._show_error("Could not save project", error.message)
            return
        if file is None or not file.get_path():
            self._after_save = None
            return

        target = Path(file.get_path())
        if target.suffix.lower() != project.SUFFIX:
            target = target.with_name(target.name + project.SUFFIX)

        if self._document.has_redactions:
            # Saying this at the moment of saving is the only point where it
            # can actually change what the user does with the file.
            self._confirm(
                heading="Save project with redactions?",
                body=(
                    f"{target.name} will contain the original, unredacted image so "
                    "the redactions stay editable.\n\n"
                    "Do not share this file. Use Export for anything you send on, "
                    "or Burn In Redactions first."
                ),
                confirm_label="Save Project",
                on_confirm=lambda: self._write_project(target),
            )
        else:
            self._write_project(target)

    def _write_project(self, target: Path) -> None:
        try:
            written = self._document.save_project(target)
        except Exception as error:
            self._after_save = None
            log.exception("saving project to %s failed", target)
            self._show_error("Could not save project", f"{target.name}: {error}")
            return
        self._update_title()
        self._update_redaction_banner()
        toast = Adw.Toast(title=f"Saved {written.name}")
        toast.set_button_label("Show in Files")
        toast.connect("button-clicked", lambda *_: self._reveal(written))
        self._toasts.add_toast(toast)

        callback, self._after_save = self._after_save, None
        if callback is not None:
            callback()

    # -- destructive actions ---------------------------------------------

    def _action_overwrite_original(self, *_args) -> None:
        """Flatten onto the source file, which Ctrl+S deliberately refuses to do."""
        if self._document is None:
            return
        source = self._document.export_basis
        if source is None or not source.exists():
            self._show_error(
                "No original to overwrite",
                "This image has not been saved anywhere yet. Use Export As instead.",
            )
            return

        self._confirm(
            heading=f"Overwrite {source.name}?",
            body=(
                "The annotations will be flattened onto the original file and the "
                "unmarked image will be lost.\n\n"
                "Export writes a separate copy instead."
            ),
            confirm_label="Overwrite",
            destructive=True,
            on_confirm=lambda: self._write_export(source, allow_source=True),
        )

    def _action_burn_in(self, *_args) -> None:
        if self._document is None or not self._document.has_redactions:
            return
        count = len(self._document.redactions)
        self._confirm(
            heading=f"Burn in {count} redaction{'s' if count != 1 else ''}?",
            body=(
                "The hidden areas will be merged into the image itself, so a saved "
                "project no longer contains them.\n\n"
                "You can still undo this while the image stays open."
            ),
            confirm_label="Burn In",
            destructive=True,
            on_confirm=self._burn_in,
        )

    def _burn_in(self) -> None:
        self._canvas.clear_selection()
        if self._document.burn_in_redactions():
            self._update_redaction_banner()
            self._toasts.add_toast(Adw.Toast(title="Redactions burnt in"))

    def _confirm(
        self,
        *,
        heading: str,
        body: str,
        confirm_label: str,
        on_confirm,
        destructive: bool = False,
    ) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", confirm_label)
        dialog.set_response_appearance(
            "confirm",
            Adw.ResponseAppearance.DESTRUCTIVE
            if destructive
            else Adw.ResponseAppearance.SUGGESTED,
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _d, response: on_confirm() if response == "confirm" else None,
        )
        dialog.present(self)

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

    # -- text editing ----------------------------------------------------

    def _on_text_edit_requested(self, _canvas, annotation) -> None:
        """Open an editor over the label.

        A popover anchored to the label is used rather than a text widget
        embedded in the canvas: it keeps working at any zoom or scroll offset,
        handles multi-line input, and is the familiar GNOME idiom.
        """
        popover = Gtk.Popover(autohide=True, has_arrow=True)
        popover.set_parent(self._canvas)
        popover.set_pointing_to(self._editor_anchor(annotation))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        scroller = Gtk.ScrolledWindow(min_content_width=280, min_content_height=90)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add_css_class("card")
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.set_top_margin(6)
        view.set_bottom_margin(6)
        view.set_left_margin(6)
        view.set_right_margin(6)
        view.get_buffer().set_text(annotation.text)
        scroller.set_child(view)
        box.append(scroller)

        hint = Gtk.Label(label="Escape cancels", xalign=0)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        box.append(hint)

        apply_button = Gtk.Button(label="Apply")
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", lambda *_: popover.popdown())
        box.append(apply_button)

        popover.set_child(box)
        self._text_popover = popover
        self._text_cancelled = False

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_text_editor_key, popover)
        view.add_controller(keys)
        popover.connect("closed", self._on_text_editor_closed, view)

        popover.popup()
        view.grab_focus()

    def _editor_anchor(self, annotation) -> Gdk.Rectangle:
        bounds = annotation.bounds().normalized()
        x, y = self._canvas.image_to_widget(bounds.x, bounds.y)
        rectangle = Gdk.Rectangle()
        rectangle.x = int(x)
        rectangle.y = int(y)
        rectangle.width = max(1, int(bounds.width * self._canvas.zoom))
        rectangle.height = max(1, int(bounds.height * self._canvas.zoom))
        return rectangle

    def _on_text_editor_key(self, _controller, keyval, _keycode, _state, popover) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._text_cancelled = True
            popover.popdown()
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _on_text_editor_closed(self, popover: Gtk.Popover, view: Gtk.TextView) -> None:
        if self._text_cancelled:
            self._canvas.cancel_text_edit()
        else:
            buffer = view.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
            self._canvas.commit_text_edit(text)
        popover.unparent()
        self._text_popover = None

    # -- closing ---------------------------------------------------------

    def has_unsaved_work(self) -> bool:
        """True if closing now would lose annotations.

        Exporting deliberately does not count as saving: an exported image is
        flattened pixels and cannot be reopened for editing, so the annotations
        really are still unsaved.
        """
        return self._document is not None and self._document.dirty

    def save_state(self) -> None:
        """Remember window geometry and the styles chosen, for next time."""
        if not self.is_maximized():
            self.settings.set_int("window-width", self.get_width() or 1200)
            self.settings.set_int("window-height", self.get_height() or 800)
        self.settings.set_boolean("window-maximized", self.is_maximized())
        self.settings.set_boolean("sidebar-visible", self._split.get_show_sidebar())
        self.settings.set_string("export-format", self._export_format)
        self.settings.set_int("export-quality", self._export_quality)
        self.settings.set_tool_styles(self._canvas.all_tool_styles())

    def _on_close_request(self, *_args) -> bool:
        if self._force_close or not self.has_unsaved_work():
            self.save_state()
            return Gdk.EVENT_PROPAGATE  # let the window close
        self._confirm_discard()
        return Gdk.EVENT_STOP

    def _confirm_discard(self) -> None:
        name = self._document.display_name
        dialog = Adw.AlertDialog(
            heading=f"Save changes to {name}?",
            body=(
                "Your annotations have not been saved to a project.\n\n"
                "Exported images are flattened and cannot be edited again, so "
                "exporting does not preserve them."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("discard", "Discard")
        dialog.add_response("save", "Save Project\u2026")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_discard_response)
        dialog.present(self)

    def _on_discard_response(self, _dialog, response: str) -> None:
        if response == "discard":
            self.close_without_prompting()
        elif response == "save":
            self._save_project_then(self.close_without_prompting)

    def close_without_prompting(self) -> None:
        self._force_close = True
        self.close()

    # -- feedback --------------------------------------------------------

    def _show_error(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "Close")
        dialog.set_default_response("ok")
        dialog.present(self)
