"""Settings, persisted through GSettings when the schema can be found.

Running from a source tree the schema is not installed system-wide, so
``run.sh`` compiles it into ``data/schemas`` and this module looks there first.
If it cannot be found at all - someone running the package straight from a
checkout with no GLib tooling - everything still works, just without
remembering anything between runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import APP_ID, gi_init  # noqa: F401
from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "data" / "schemas"

#: Mirrors the gschema defaults, so the in-memory fallback behaves identically.
DEFAULTS: dict[str, object] = {
    "window-width": 1200,
    "window-height": 800,
    "window-maximized": False,
    "sidebar-visible": True,
    "export-format": "PNG",
    "export-quality": 92,
    "tool-styles": "{}",
}


def _load_schema() -> Gio.SettingsSchema | None:
    """Find the compiled schema, preferring the one beside the source."""
    sources: list[Gio.SettingsSchemaSource] = []
    default_source = Gio.SettingsSchemaSource.get_default()
    if (SCHEMA_DIR / "gschemas.compiled").is_file():
        try:
            sources.append(
                Gio.SettingsSchemaSource.new_from_directory(
                    str(SCHEMA_DIR), default_source, False
                )
            )
        except GLib.Error as error:
            log.warning("could not read %s: %s", SCHEMA_DIR, error.message)
    if default_source is not None:
        sources.append(default_source)

    for source in sources:
        schema = source.lookup(APP_ID, True)
        if schema is not None:
            return schema
    return None


class Settings:
    """A small typed wrapper, with an in-memory fallback.

    Deliberately not a thin pass-through to ``Gio.Settings``: the fallback has
    to behave the same way, so every access goes through here.
    """

    def __init__(self, *, use_gsettings: bool = True):
        self._values = dict(DEFAULTS)
        self._gsettings: Gio.Settings | None = None
        if not use_gsettings:
            return
        schema = _load_schema()
        if schema is None:
            log.info("no GSettings schema for %s; settings will not persist", APP_ID)
            return
        self._gsettings = Gio.Settings.new_full(schema, None, None)

    @property
    def persistent(self) -> bool:
        """False when nothing will survive the application closing."""
        return self._gsettings is not None

    # -- scalars ---------------------------------------------------------

    def get_int(self, key: str) -> int:
        if self._gsettings is not None:
            return self._gsettings.get_int(key)
        return int(self._values[key])

    def set_int(self, key: str, value: int) -> None:
        if self._gsettings is not None:
            self._gsettings.set_int(key, int(value))
        else:
            self._values[key] = int(value)

    def get_boolean(self, key: str) -> bool:
        if self._gsettings is not None:
            return self._gsettings.get_boolean(key)
        return bool(self._values[key])

    def set_boolean(self, key: str, value: bool) -> None:
        if self._gsettings is not None:
            self._gsettings.set_boolean(key, bool(value))
        else:
            self._values[key] = bool(value)

    def get_string(self, key: str) -> str:
        if self._gsettings is not None:
            return self._gsettings.get_string(key)
        return str(self._values[key])

    def set_string(self, key: str, value: str) -> None:
        if self._gsettings is not None:
            self._gsettings.set_string(key, str(value))
        else:
            self._values[key] = str(value)

    # -- tool styles -----------------------------------------------------

    def get_tool_styles(self) -> dict:
        """The remembered per-tool styles.

        Stored as JSON, so a corrupt or outdated value must never stop the
        application starting - it is a convenience, not data the user created.
        """
        raw = self.get_string("tool-styles")
        try:
            loaded = json.loads(raw)
        except (TypeError, ValueError):
            log.info("discarding unreadable tool-styles")
            return {}
        if not isinstance(loaded, dict):
            return {}
        return {
            name: style
            for name, style in loaded.items()
            if isinstance(name, str) and isinstance(style, dict)
        }

    def set_tool_styles(self, styles: dict) -> None:
        try:
            encoded = json.dumps(_encodable(styles), sort_keys=True)
        except (TypeError, ValueError):
            log.warning("tool styles could not be stored")
            return
        self.set_string("tool-styles", encoded)


def _encodable(styles: dict) -> dict:
    """Make styles JSON-safe: colours are tuples, which JSON turns into lists."""
    out: dict[str, dict] = {}
    for name, style in styles.items():
        entry: dict[str, object] = {}
        for key, value in style.items():
            if isinstance(value, (tuple, list)):
                entry[key] = [float(v) for v in value]
            elif isinstance(value, (int, float, str, bool)) or value is None:
                entry[key] = value
        out[name] = entry
    return out


def restore_tool_styles(canvas, settings: Settings) -> None:
    """Apply remembered styles to a canvas, keeping each tool's own defaults.

    Only keys the tool already has are restored, so a style saved by a newer
    build - or one belonging to a kind that has since changed - cannot
    introduce an attribute the annotation does not understand.
    """
    for name, stored in settings.get_tool_styles().items():
        try:
            style = canvas.style_for(name)
        except Exception:  # unknown tool name from an older or newer build
            continue
        for key, value in stored.items():
            if key not in style:
                continue
            current = style[key]
            if isinstance(current, tuple) and isinstance(value, list):
                style[key] = tuple(value)
            elif isinstance(current, bool) and isinstance(value, bool):
                style[key] = value
            elif isinstance(current, (int, float)) and isinstance(value, (int, float)):
                style[key] = type(current)(value)
            elif isinstance(current, str) and isinstance(value, str):
                style[key] = value
