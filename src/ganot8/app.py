"""The Adw.Application: command-line handling, actions, accelerators."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import gi_init  # noqa: F401
from gi.repository import Adw, Gdk, Gio, Gtk

from . import APP_ID, APP_NAME, __version__
from .window import Window

log = logging.getLogger(__name__)

_ACCELERATORS = {
    "win.open": ("<Control>o",),
    "win.export": ("<Control>s",),
    "win.export-as": ("<Control><Shift>e",),
    "win.zoom-in": ("<Control>plus", "<Control>equal", "<Control>KP_Add"),
    "win.zoom-out": ("<Control>minus", "<Control>KP_Subtract"),
    "win.zoom-fit": ("<Control>0",),
    "win.zoom-100": ("<Control>1",),
    "win.undo": ("<Control>z",),
    "win.redo": ("<Control><Shift>z", "<Control>y"),
    "win.select-all": ("<Control>a",),
    "win.deselect": ("<Control><Shift>a",),
    "win.raise-annotation": ("<Control>Page_Up",),
    "win.lower-annotation": ("<Control>Page_Down",),
    "win.toggle-sidebar": ("F9",),
    "app.quit": ("<Control>q",),
}

#: Single-key tool shortcuts, bound to the stateful "win.tool" action.
_TOOL_ACCELERATORS = {
    "select": "s",
    "highlight": "h",
    "redact": "r",
    "underline": "u",
    "arrow": "a",
    "text": "t",
    "box": "b",
}

_STYLESHEET = b"""
.ganot8-canvas-area {
    background-color: shade(@window_bg_color, 0.82);
}
.ganot8-tool-strip button {
    min-width: 34px;
    min-height: 34px;
}
"""


class Application(Adw.Application):
    """Opens one window per file given, reusing the first if it is empty."""

    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.connect("open", self._on_open)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._install_actions()
        self._install_stylesheet()

    def do_activate(self) -> None:
        self._present_window()

    def _on_open(self, _app, files, _n_files: int, _hint: str) -> None:
        opened_any = False
        for file in files:
            path = file.get_path()
            if path is None:
                log.warning("ignoring non-local file: %s", file.get_uri())
                continue
            window = self._window_for_new_document()
            if window.open_path(path):
                opened_any = True
                window.present()
        if not opened_any:
            self._present_window()

    # -- helpers ---------------------------------------------------------

    def _present_window(self) -> Window:
        window = self.get_active_window() or Window(application=self)
        window.present()
        return window

    def _window_for_new_document(self) -> Window:
        """Reuse an empty window; otherwise open a new one."""
        active = self.get_active_window()
        if isinstance(active, Window) and active.document is None:
            return active
        return Window(application=self)

    def _install_actions(self) -> None:
        for name, callback in (
            ("quit", lambda *_: self.quit()),
            ("about", self._action_about),
            ("new-window", lambda *_: Window(application=self).present()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        for detailed_name, accels in _ACCELERATORS.items():
            self.set_accels_for_action(detailed_name, list(accels))

        # Tool shortcuts target the stateful action with a string parameter,
        # so the detailed name carries the tool it selects.
        for tool_name, key in _TOOL_ACCELERATORS.items():
            self.set_accels_for_action(f"win.tool::{tool_name}", [key])

    def _install_stylesheet(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(_STYLESHEET)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _action_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon="image-x-generic-symbolic",
            version=__version__,
            developer_name="Martin Bertolino",
            comments="Annotate, highlight and redact images.",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(self.get_active_window())


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    argv = list(sys.argv if argv is None else argv)
    # Reject paths that do not exist up front, so GIO does not create windows
    # for them and the user gets a clear message on the terminal instead.
    program, rest = argv[0], argv[1:]
    missing = [a for a in rest if not a.startswith("-") and not Path(a).exists()]
    for path in missing:
        print(f"{APP_NAME}: no such file: {path}", file=sys.stderr)
    kept = [a for a in rest if a not in missing]
    return Application().run([program, *kept])
