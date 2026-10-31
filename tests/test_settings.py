"""Settings persistence, and the fallback when the schema is missing."""

from __future__ import annotations

import pytest

from ganot8.settings import DEFAULTS, Settings, restore_tool_styles


@pytest.fixture
def memory_settings() -> Settings:
    """A Settings that never touches the real dconf database."""
    return Settings(use_gsettings=False)


def test_fallback_reports_itself_as_not_persistent(memory_settings):
    assert not memory_settings.persistent


def test_fallback_serves_the_schema_defaults(memory_settings):
    assert memory_settings.get_int("window-width") == DEFAULTS["window-width"]
    assert memory_settings.get_string("export-format") == DEFAULTS["export-format"]
    assert memory_settings.get_boolean("sidebar-visible") is DEFAULTS["sidebar-visible"]


def test_fallback_round_trips_every_type(memory_settings):
    memory_settings.set_int("window-width", 1337)
    memory_settings.set_boolean("window-maximized", True)
    memory_settings.set_string("export-format", "WEBP")
    assert memory_settings.get_int("window-width") == 1337
    assert memory_settings.get_boolean("window-maximized") is True
    assert memory_settings.get_string("export-format") == "WEBP"


def test_tool_styles_round_trip(memory_settings):
    styles = {"box": {"color": (1.0, 0.0, 0.0, 1.0), "stroke_width": 9.0, "filled": True}}
    memory_settings.set_tool_styles(styles)
    loaded = memory_settings.get_tool_styles()
    assert loaded["box"]["stroke_width"] == 9.0
    assert loaded["box"]["filled"] is True
    # JSON has no tuples, so colours come back as lists.
    assert list(loaded["box"]["color"]) == [1.0, 0.0, 0.0, 1.0]


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null", '{"box": 3}', "12"])
def test_unreadable_tool_styles_are_discarded_not_fatal(memory_settings, raw):
    """A convenience must never stop the application starting."""
    memory_settings.set_string("tool-styles", raw)
    assert memory_settings.get_tool_styles() == {} or all(
        isinstance(v, dict) for v in memory_settings.get_tool_styles().values()
    )


def test_unstorable_styles_do_not_raise(memory_settings):
    memory_settings.set_tool_styles({"box": {"thing": object()}})
    # The unencodable value is dropped rather than taking the rest with it.
    assert "thing" not in memory_settings.get_tool_styles().get("box", {})


# -- restoring onto a canvas ---------------------------------------------


class FakeCanvas:
    """Only the part of Canvas that restore_tool_styles touches."""

    def __init__(self, styles):
        self._styles = styles

    def style_for(self, name):
        if name not in self._styles:
            raise KeyError(name)
        return self._styles[name]


def test_restore_applies_known_keys():
    canvas = FakeCanvas({"box": {"color": (0.0, 0.0, 0.0, 1.0), "stroke_width": 7.0}})
    settings = Settings(use_gsettings=False)
    settings.set_tool_styles({"box": {"color": [1.0, 0.5, 0.0, 1.0], "stroke_width": 12.0}})

    restore_tool_styles(canvas, settings)
    assert canvas._styles["box"]["color"] == (1.0, 0.5, 0.0, 1.0)
    assert canvas._styles["box"]["stroke_width"] == 12.0


def test_restore_ignores_keys_the_tool_does_not_have():
    """A style saved by a newer build must not inject unknown attributes."""
    canvas = FakeCanvas({"box": {"stroke_width": 7.0}})
    settings = Settings(use_gsettings=False)
    settings.set_tool_styles({"box": {"stroke_width": 3.0, "sparkle": True}})

    restore_tool_styles(canvas, settings)
    assert canvas._styles["box"] == {"stroke_width": 3.0}


def test_restore_ignores_unknown_tools():
    canvas = FakeCanvas({"box": {"stroke_width": 7.0}})
    settings = Settings(use_gsettings=False)
    settings.set_tool_styles({"hologram": {"stroke_width": 1.0}})

    restore_tool_styles(canvas, settings)
    assert canvas._styles["box"]["stroke_width"] == 7.0


def test_restore_ignores_values_of_the_wrong_type():
    canvas = FakeCanvas({"box": {"stroke_width": 7.0, "filled": True}})
    settings = Settings(use_gsettings=False)
    settings.set_tool_styles({"box": {"stroke_width": "thick", "filled": "yes"}})

    restore_tool_styles(canvas, settings)
    assert canvas._styles["box"] == {"stroke_width": 7.0, "filled": True}


def test_the_shipped_schema_matches_the_fallback_defaults():
    """Two sources of defaults that disagree would behave differently."""
    import xml.etree.ElementTree as ElementTree
    from pathlib import Path

    from ganot8.settings import SCHEMA_DIR

    xml = SCHEMA_DIR / "io.github.martinb.Ganot8.gschema.xml"
    assert xml.is_file(), "the schema must ship with the source"
    keys = {
        key.get("name")
        for key in ElementTree.parse(xml).getroot().iter("key")
    }
    assert keys == set(DEFAULTS), "schema keys and fallback defaults have diverged"


def test_the_suite_never_writes_real_settings():
    """conftest forces GSETTINGS_BACKEND=memory before Gio is imported.

    Without it, windows created by tests save their state on close into the
    developer's own dconf, and later tests read it back - which made an
    unrelated sidebar test fail depending on what had run before, and quietly
    changed the developer's settings as a side effect of running the suite.
    """
    import os

    from gi.repository import Gio

    assert os.environ.get("GSETTINGS_BACKEND") == "memory"
    backend = type(Gio.SettingsBackend.get_default()).__name__
    assert "Memory" in backend, f"settings would reach the real database via {backend}"


def test_settings_still_read_and_write_under_the_memory_backend():
    """The isolation must not make the GSettings path untested."""
    live = Settings()
    assert live.persistent, "the schema should still be found"
    live.set_string("export-format", "TIFF")
    assert live.get_string("export-format") == "TIFF"
