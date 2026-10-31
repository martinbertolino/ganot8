"""Window wiring: tool strip, style sidebar, action sensitivity.

Needs a display, like test_tools.py.
"""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8 import gi_init  # noqa: F401
from gi.repository import Adw, Gdk, Gtk, Pango

from ganot8.annotations import Box
from ganot8.document import Document
from ganot8.geometry import Rect
from ganot8.imageio.loader import LoadedImage

if not Gtk.init_check():
    pytest.skip("no display available for GTK widgets", allow_module_level=True)

Adw.init()

from ganot8.window import Window  # noqa: E402


@pytest.fixture
def window() -> Window:
    widget = Window()
    widget.set_document(Document(LoadedImage(image=Image.new("RGBA", (300, 200)))))
    return widget


def add_box(window: Window, **kwargs) -> Box:
    annotation = Box(rect=Rect(10, 10, 50, 50), **kwargs)
    window.document.annotations.append(annotation)
    return annotation


def enabled(window: Window, name: str) -> bool:
    return window.lookup_action(name).get_enabled()


# -- actions -------------------------------------------------------------


def test_editing_actions_are_disabled_without_a_document():
    empty = Window()
    assert not enabled(empty, "export")
    assert not enabled(empty, "undo")
    assert not enabled(empty, "delete")


def test_opening_a_document_enables_export(window):
    assert enabled(window, "export")
    assert enabled(window, "select-all")


def test_undo_becomes_available_after_an_edit(window):
    from ganot8.history import AddAnnotations

    assert not enabled(window, "undo")
    window.document.history.push(AddAnnotations(window.document, [add_box(window)]))
    assert enabled(window, "undo")
    assert not enabled(window, "redo")
    window.lookup_action("undo").activate(None)
    assert enabled(window, "redo")


def test_delete_requires_a_selection(window):
    annotation = add_box(window)
    assert not enabled(window, "delete")
    window.canvas.set_selection([annotation])
    assert enabled(window, "delete")


def test_reorder_requires_exactly_one_selected(window):
    first, second = add_box(window), add_box(window)
    window.canvas.set_selection([first])
    assert enabled(window, "raise-annotation")
    window.canvas.set_selection([first, second])
    assert not enabled(window, "raise-annotation")


def test_raise_moves_the_annotation_up_the_z_order(window):
    first, second = add_box(window), add_box(window)
    window.canvas.set_selection([first])
    window.lookup_action("raise-annotation").activate(None)
    assert window.document.annotations[1] is first
    assert window.document.annotations[0] is second


# -- tool strip ----------------------------------------------------------


def test_every_registered_tool_has_a_button(window):
    from ganot8.tools import registered_tools

    assert set(window._tool_buttons) == {tool.name for tool in registered_tools()}


def test_tool_button_reflects_the_active_tool(window):
    window.canvas.activate_tool("box")
    assert window._tool_buttons["box"].get_active()
    assert not window._tool_buttons["select"].get_active()


def test_clicking_a_tool_button_activates_that_tool(window):
    window._tool_buttons["box"].set_active(True)
    assert window.canvas.tool_name == "box"


# -- style sidebar -------------------------------------------------------


def test_sidebar_shows_the_selected_annotation_style(window):
    annotation = add_box(window, color=(0.0, 0.5, 1.0, 1.0), stroke_width=9.0)
    window.canvas.set_selection([annotation])
    rgba = window._colour_button.get_rgba()
    assert (round(rgba.green, 2), round(rgba.blue, 2)) == (0.5, 1.0)
    assert window._width_row.get_value() == pytest.approx(9.0)


def test_changing_style_with_a_selection_edits_it_undoably(window):
    annotation = add_box(window)
    window.canvas.set_selection([annotation])
    window._width_row.set_value(12.0)

    assert annotation.stroke_width == pytest.approx(12.0)
    assert window.document.history.undo_label == "Change Width"
    window.lookup_action("undo").activate(None)
    assert annotation.stroke_width == pytest.approx(3.0)


def test_changing_style_without_a_selection_sets_the_default(window):
    window.canvas.activate_tool("box")
    window.canvas.clear_selection()
    window._width_row.set_value(7.0)
    assert window.canvas.style_for("box")["stroke_width"] == pytest.approx(7.0)
    # Nothing to edit, so nothing to undo.
    assert not window.document.history.can_undo


def test_style_change_applies_to_every_selected_annotation(window):
    first, second = add_box(window), add_box(window)
    window.canvas.set_selection([first, second])
    window._width_row.set_value(5.0)
    assert first.stroke_width == second.stroke_width == pytest.approx(5.0)
    assert window.document.history.depth == 1


def test_syncing_the_sidebar_does_not_record_an_undo_step(window):
    """Selecting must not look like an edit: the _syncing guard covers this."""
    annotation = add_box(window, stroke_width=11.0)
    window.canvas.set_selection([annotation])
    window.canvas.clear_selection()
    window.canvas.set_selection([annotation])
    assert not window.document.history.can_undo
    assert annotation.stroke_width == pytest.approx(11.0)


def test_colour_change_round_trips_through_the_button(window):
    annotation = add_box(window)
    window.canvas.set_selection([annotation])
    window._colour_button.set_rgba(Gdk.RGBA(red=1.0, green=0.0, blue=0.0, alpha=1.0))
    assert annotation.color[0] == pytest.approx(1.0)
    assert annotation.color[1] == pytest.approx(0.0)


def test_filled_switch_applies(window):
    """Boxes are filled by default, so the switch is exercised by clearing it."""
    annotation = add_box(window)
    assert annotation.filled is True
    window.canvas.set_selection([annotation])
    window._filled_row.set_active(False)
    assert annotation.filled is False
    assert window.document.history.undo_label == "Change Fill"
    window.lookup_action("undo").activate(None)
    assert annotation.filled is True


def test_unsupported_style_rows_are_hidden(window):
    """An annotation that exposes no style properties shows no style rows."""
    from ganot8.annotations import annotation_from_dict

    unknown = annotation_from_dict({"kind": "hologram"})
    window.document.annotations.append(unknown)
    # Unknown kinds are unselectable, so force the sidebar to describe one.
    window.canvas._selection = [unknown]
    window._sync_style_controls()
    assert not window._colour_row.get_visible()
    assert not window._width_row.get_visible()


# -- phase 3 sidebar rows ------------------------------------------------


def _visible_rows(window) -> set[str]:
    return {
        name
        for name, row in (
            ("colour", window._colour_row),
            ("font", window._font_row),
            ("width", window._width_row),
            ("opacity", window._opacity_row),
            ("filled", window._filled_row),
            ("wavy", window._wavy_row),
            ("background", window._background_row),
        )
        if row.get_visible()
    }


def test_sidebar_shows_only_the_rows_a_kind_supports(window):
    from ganot8.annotations import Highlight, Redact, TextLabel, Underline

    cases = {
        Highlight(): {"colour", "opacity"},
        Redact(): {"colour"},
        Underline(): {"colour", "width", "opacity", "wavy"},
        TextLabel(text="x"): {"colour", "font", "opacity", "background"},
    }
    for annotation, expected in cases.items():
        window.document.annotations.append(annotation)
        window.canvas.set_selection([annotation])
        assert _visible_rows(window) == expected, type(annotation).__name__


def test_redaction_offers_no_opacity_control(window):
    """A translucent redaction leaks, so the control must not exist."""
    from ganot8.annotations import Redact

    redaction = Redact(rect=Rect(0, 0, 10, 10))
    window.document.annotations.append(redaction)
    window.canvas.set_selection([redaction])
    assert not window._opacity_row.get_visible()


def test_wavy_switch_edits_an_underline(window):
    from ganot8.annotations import Underline
    from ganot8.geometry import Point

    underline = Underline(start=Point(0, 0), end=Point(50, 0))
    window.document.annotations.append(underline)
    window.canvas.set_selection([underline])
    window._wavy_row.set_active(True)
    assert underline.wavy is True
    assert window.document.history.undo_label == "Change Underline"


def test_font_change_applies_to_a_text_label(window):
    from ganot8.annotations import TextLabel

    label = TextLabel(text="hello", font="Sans 18")
    window.document.annotations.append(label)
    window.canvas.set_selection([label])
    window._font_button.set_font_desc(Pango.FontDescription.from_string("Serif Bold 30"))
    assert "Serif" in label.font and "30" in label.font


def test_background_switch_edits_a_label(window):
    from ganot8.annotations import TextLabel

    label = TextLabel(text="hello")
    window.document.annotations.append(label)
    window.canvas.set_selection([label])
    window._background_row.set_active(True)
    assert label.background is True


def test_style_group_hides_entirely_for_the_select_tool(window):
    window.canvas.activate_tool("select")
    window.canvas.clear_selection()
    assert not window._style_group.get_visible()


def test_style_group_appears_for_a_creation_tool(window):
    window.canvas.activate_tool("highlight")
    window.canvas.clear_selection()
    assert window._style_group.get_visible()
    assert _visible_rows(window) == {"colour", "opacity"}


def test_every_tool_has_a_strip_button(window):
    assert len(window._tool_buttons) == 7


def test_every_tool_icon_exists_in_the_theme(window):
    """A missing icon renders as a broken image with no warning at all."""
    from gi.repository import Gdk as _Gdk

    from ganot8.tools import registered_tools

    theme = Gtk.IconTheme.get_for_display(_Gdk.Display.get_default())
    missing = [tool.name for tool in registered_tools() if not theme.has_icon(tool.icon_name)]
    assert missing == []


# -- phase 4: projects, overwrite, burn-in -------------------------------


def _png(tmp_path, name="shot.png", size=(60, 40)):
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", size, (120, 180, 220)).save(path)
    return path


def test_opening_a_project_restores_its_annotations(window, tmp_path):
    from ganot8.annotations import Redact
    from ganot8.imageio import project

    source = window.document
    source.annotations.append(Redact(rect=Rect(0, 0, 10, 10)))
    path = source.save_project(tmp_path / "saved.ganot8")

    fresh = Window()
    assert fresh.open_path(path)
    assert fresh.document.is_project
    assert [a.kind for a in fresh.document.annotations] == ["redact"]
    assert project.looks_like_project(path)


def test_opening_a_damaged_project_reports_an_error_and_keeps_the_document(window, tmp_path):
    bad = tmp_path / "broken.ganot8"
    bad.write_bytes(b"not a zip at all")
    previous = window.document
    assert not window.open_path(bad)
    assert window.document is previous


def test_burn_in_is_disabled_without_redactions(window):
    assert not enabled(window, "burn-in")


def test_burn_in_is_enabled_once_a_redaction_exists(window):
    from ganot8.annotations import Redact

    window.document.annotations.append(Redact(rect=Rect(0, 0, 10, 10)))
    window.document.mark_dirty()
    assert enabled(window, "burn-in")


def test_redaction_banner_appears_only_for_a_project(window, tmp_path):
    from ganot8.annotations import Redact

    window.document.annotations.append(Redact(rect=Rect(0, 0, 10, 10)))
    window.document.mark_dirty()
    # Not a project yet: nothing on disk retains the original.
    assert not window._banner.get_revealed()

    window.document.save_project(tmp_path / "p.ganot8")
    window._update_redaction_banner()
    assert window._banner.get_revealed()
    assert "unredacted" in window._banner.get_title()


def test_banner_clears_after_burning_in(window, tmp_path):
    from ganot8.annotations import Redact

    window.document.annotations.append(Redact(rect=Rect(0, 0, 10, 10)))
    window.document.save_project(tmp_path / "p.ganot8")
    window._update_redaction_banner()
    assert window._banner.get_revealed()

    window._burn_in()
    assert not window._banner.get_revealed()


def test_export_refuses_to_write_over_the_source(window, tmp_path):
    source = _png(tmp_path)
    assert window.open_path(source)
    before = source.read_bytes()
    window._write_export(source)
    assert source.read_bytes() == before, "Ctrl+S must never touch the original"


def test_overwrite_original_does_write_over_the_source(window, tmp_path):
    """The explicit, confirmed action is the one allowed to do it."""
    source = _png(tmp_path)
    assert window.open_path(source)
    before = source.read_bytes()

    window._write_export(source, allow_source=True)
    assert source.read_bytes() != before


def test_overwrite_original_is_refused_when_there_is_no_file(window):
    window.lookup_action("overwrite-original").activate(None)
    # The in-memory document has no source file; nothing should have happened.
    assert window.document.source_path is None


def test_export_uses_the_chosen_quality(window, tmp_path):
    source = _png(tmp_path, size=(200, 160))
    assert window.open_path(source)

    window._export_quality = 10
    low = tmp_path / "low.jpg"
    window._write_export(low)

    window._export_quality = 95
    high = tmp_path / "high.jpg"
    window._write_export(high)

    assert low.stat().st_size < high.stat().st_size


def test_save_project_action_is_available_with_a_document(window):
    assert enabled(window, "save-project")
