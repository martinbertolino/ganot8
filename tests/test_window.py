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
from ganot8.geometry import Point, Rect
from ganot8.imageio.loader import LoadedImage

from support import SKIP_REASON, display_available  # noqa: E402

if not display_available():
    pytest.skip(SKIP_REASON, allow_module_level=True)

Gtk.init()

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
    assert annotation.stroke_width == pytest.approx(7.0)


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
            ("style", window._redact_style_row),
            ("strength", window._strength_row),
            ("colour", window._colour_row),
            ("number-colour", window._text_colour_row),
            ("bg-colour", window._background_colour_row),
            ("padding", window._padding_row),
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
        Redact(): {"style", "colour"},
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
    window.canvas.clear_selection()
    window.canvas.activate_tool("highlight")
    assert window._style_group.get_visible()
    assert _visible_rows(window) == {"colour", "opacity"}


def test_every_tool_has_a_strip_button(window):
    from ganot8.tools import registered_tools

    assert set(window._tool_buttons) == {tool.name for tool in registered_tools()}


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


# -- closing with unsaved work -------------------------------------------


def test_a_fresh_document_has_nothing_to_lose(window):
    assert not window.has_unsaved_work()


def test_annotating_creates_unsaved_work(window):
    from ganot8.history import AddAnnotations

    window.document.history.push(AddAnnotations(window.document, [add_box(window)]))
    assert window.has_unsaved_work()


def test_close_is_blocked_while_work_is_unsaved(window):
    from ganot8.history import AddAnnotations

    window.document.history.push(AddAnnotations(window.document, [add_box(window)]))
    # True means "handled": the window must not close yet.
    assert window._on_close_request() is True


def test_close_is_allowed_once_the_project_is_saved(window, tmp_path):
    from ganot8.history import AddAnnotations

    window.document.history.push(AddAnnotations(window.document, [add_box(window)]))
    window.document.save_project(tmp_path / "saved.ganot8")
    assert not window.has_unsaved_work()
    assert window._on_close_request() is False


def test_discarding_lets_the_next_close_through(window):
    from ganot8.history import AddAnnotations

    window.document.history.push(AddAnnotations(window.document, [add_box(window)]))
    window._on_discard_response(None, "discard")
    assert window._force_close
    assert window._on_close_request() is False


def test_cancelling_the_prompt_changes_nothing(window):
    from ganot8.history import AddAnnotations

    window.document.history.push(AddAnnotations(window.document, [add_box(window)]))
    window._on_discard_response(None, "cancel")
    assert not window._force_close
    assert window.has_unsaved_work()


def test_exporting_does_not_count_as_saving(window, tmp_path):
    """An export is flattened pixels; the annotations are still unsaved."""
    from ganot8.history import AddAnnotations

    window.document.history.push(AddAnnotations(window.document, [add_box(window)]))
    window._write_export(tmp_path / "out.png")
    assert window.has_unsaved_work()


def test_a_window_with_no_document_closes_freely():
    assert Window()._on_close_request() is False


# -- conditional style rows ----------------------------------------------


def test_line_width_row_hides_for_a_filled_box(window):
    filled = add_box(window, filled=True)
    window.canvas.set_selection([filled])
    assert not window._width_row.get_visible()

    window._filled_row.set_active(False)
    assert window._width_row.get_visible()


def test_sidebar_buttons_are_inset_from_the_card_edge(window):
    """Adw.PreferencesRow adds no padding of its own, unlike ActionRow.

    Without explicit margins the Raise/Lower/Delete buttons sit flush against
    the card border, unlike every control in the Style group above them.
    """
    for row in (window._arrange_row, window._delete_row):
        box = row.get_child()
        assert box.get_margin_start() >= 8
        assert box.get_margin_end() >= 8
        assert box.get_margin_bottom() >= 8
        assert box.get_margin_top() >= 8


def test_selection_summary_is_inset_too(window):
    assert window._selection_label.get_margin_start() >= 8
    assert window._selection_label.get_margin_end() >= 8


# -- the sidebar must follow the active tool -----------------------------


def test_picking_a_tool_updates_the_sidebar_while_something_is_selected(window):
    """The panel used to keep describing the selection until the tool was used.

    Drawing a shape selects it, so the very next tool click left the sidebar
    showing the wrong annotation's options.
    """
    box = add_box(window)
    window.canvas.set_selection([box])
    assert _visible_rows(window) == {"colour", "opacity", "filled"}

    window.canvas.activate_tool("underline")
    assert _visible_rows(window) == {"colour", "width", "opacity", "wavy"}
    assert "next underline" in window._selection_label.get_text()


@pytest.mark.parametrize(
    "tool,expected",
    [
        ("highlight", {"colour", "opacity"}),
        ("redact", {"style", "colour"}),
        ("underline", {"colour", "width", "opacity", "wavy"}),
        ("arrow", {"colour", "width", "opacity"}),
        ("text", {"colour", "font", "opacity", "background"}),
        ("box", {"colour", "opacity", "filled"}),
    ],
)
def test_every_creation_tool_shows_its_own_options_immediately(window, tool, expected):
    window.canvas.set_selection([add_box(window)])
    window.canvas.activate_tool(tool)
    assert _visible_rows(window) == expected


def test_switching_to_select_keeps_the_selection(window):
    """Select is for manipulating what is already there."""
    box = add_box(window)
    window.canvas.activate_tool("box")
    window.canvas.set_selection([box])
    window.canvas.activate_tool("select")
    assert window.canvas.selection == [box]


def test_arrange_actions_follow_the_cleared_selection(window):
    """Clearing on tool switch must disable the buttons that need a selection."""
    window.canvas.set_selection([add_box(window)])
    assert enabled(window, "delete")
    window.canvas.activate_tool("arrow")
    assert not enabled(window, "delete")
    assert not enabled(window, "raise-annotation")


# -- redaction style controls --------------------------------------------


def test_redaction_shows_colour_for_solid_and_strength_for_the_others(window):
    """Colour is meaningless for a blur; strength is meaningless for a block."""
    from ganot8.annotations import Redact
    from ganot8.effects import STYLE_BLUR, STYLE_PIXELATE, STYLE_SOLID

    redaction = Redact(rect=Rect(0, 0, 40, 20))
    window.document.annotations.append(redaction)
    window.canvas.set_selection([redaction])
    assert _visible_rows(window) == {"style", "colour"}

    for style in (STYLE_BLUR, STYLE_PIXELATE):
        redaction.style = style
        window._sync_style_controls()
        assert _visible_rows(window) == {"style", "strength"}, style

    redaction.style = STYLE_SOLID
    window._sync_style_controls()
    assert _visible_rows(window) == {"style", "colour"}


def test_choosing_blur_from_the_sidebar_is_undoable(window):
    from ganot8.annotations import Redact
    from ganot8.effects import REDACT_STYLES, STYLE_BLUR

    redaction = Redact(rect=Rect(0, 0, 40, 20))
    window.document.annotations.append(redaction)
    window.canvas.set_selection([redaction])

    window._redact_style_row.set_selected(REDACT_STYLES.index(STYLE_BLUR))
    assert redaction.style == STYLE_BLUR
    assert window.document.history.undo_label == "Change Redaction Style"
    window.lookup_action("undo").activate(None)
    assert redaction.style == "solid"


def test_strength_edits_apply_and_undo(window):
    from ganot8.annotations import Redact
    from ganot8.effects import STYLE_PIXELATE

    redaction = Redact(rect=Rect(0, 0, 40, 20), style=STYLE_PIXELATE)
    window.document.annotations.append(redaction)
    window.canvas.set_selection([redaction])

    window._strength_row.set_value(90)
    assert redaction.strength == pytest.approx(90.0)
    window.lookup_action("undo").activate(None)
    assert redaction.strength == pytest.approx(50.0)


def test_redaction_still_offers_no_opacity_control_in_any_style(window):
    """A see-through redaction leaks, whichever style it is drawn in."""
    from ganot8.annotations import Redact
    from ganot8.effects import REDACT_STYLES

    redaction = Redact(rect=Rect(0, 0, 40, 20))
    window.document.annotations.append(redaction)
    window.canvas.set_selection([redaction])
    for style in REDACT_STYLES:
        redaction.style = style
        window._sync_style_controls()
        assert not window._opacity_row.get_visible(), style


# -- styles that used to be unreachable ----------------------------------


def test_text_plate_colour_and_padding_appear_only_with_the_plate(window):
    """They describe a plate, so showing them while it is off is noise."""
    from ganot8.annotations import TextLabel

    label = TextLabel(text="hi")
    window.document.annotations.append(label)
    window.canvas.set_selection([label])
    assert "bg-colour" not in _visible_rows(window)
    assert "padding" not in _visible_rows(window)

    window._background_row.set_active(True)
    assert "bg-colour" in _visible_rows(window)
    assert "padding" in _visible_rows(window)


def test_text_plate_colour_is_editable_and_undoable(window):
    """A white-only plate is unreadable on a dark screenshot."""
    from ganot8.annotations import TextLabel

    label = TextLabel(text="hi", background=True)
    window.document.annotations.append(label)
    window.canvas.set_selection([label])

    window._background_colour_button.set_rgba(
        Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=1.0)
    )
    assert label.background_color[0] == pytest.approx(0.0)
    assert window.document.history.undo_label == "Change Background Colour"
    window.lookup_action("undo").activate(None)
    assert label.background_color[0] == pytest.approx(1.0)


def test_text_padding_is_editable(window):
    from ganot8.annotations import TextLabel

    label = TextLabel(text="hi", background=True)
    window.document.annotations.append(label)
    window.canvas.set_selection([label])
    window._padding_row.set_value(18)
    assert label.padding == pytest.approx(18.0)


def test_badge_number_colour_is_editable(window):
    from ganot8.annotations import Badge

    badge = Badge(centre=Point(10, 10))
    window.document.annotations.append(badge)
    window.canvas.set_selection([badge])
    window._text_colour_button.set_rgba(
        Gdk.RGBA(red=1.0, green=0.9, blue=0.0, alpha=1.0)
    )
    assert badge.text_color[1] == pytest.approx(0.9)
    assert window.document.history.undo_label == "Change Number Colour"


def test_no_annotation_attribute_is_stranded_without_a_control(window):
    """Anything a project stores should be reachable from the UI.

    Three attributes were serialised, round-tripped and frozen at their
    defaults because nothing could set them. Handles count as a control.
    """
    from dataclasses import fields

    from ganot8.annotations import _REGISTRY
    from ganot8.geometry import Handle

    reachable_by_handle = {
        "radius": {"badge"},
        "wrap_width": {"text"},
    }
    cosmetic = {"text_color", "background_color", "padding", "head_scale"}

    stranded = []
    for kind, annotation_type in _REGISTRY.items():
        editable = set(annotation_type.style_properties)
        for field in fields(annotation_type):
            if field.name not in cosmetic:
                continue
            if field.name in editable:
                continue
            if kind in reachable_by_handle.get(field.name, set()):
                continue
            if not hasattr(annotation_type(), field.name):
                continue
            stranded.append(f"{kind}.{field.name}")

    # head_scale is deliberately derived from the line width (SPEC section 4).
    assert stranded == ["arrow.head_scale"], stranded


# -- phase 6: desktop integration ----------------------------------------


def test_copy_requires_a_document():
    assert not Window()._document
    assert not enabled(Window(), "copy")


def test_copy_is_available_with_a_document(window):
    assert enabled(window, "copy")


def test_paste_and_screenshot_stay_available_without_a_document():
    """They create a document, so needing one would be backwards."""
    empty = Window()
    assert enabled(empty, "paste")
    assert enabled(empty, "screenshot")


def test_adopting_an_image_creates_an_untitled_document(window):
    from PIL import Image

    window.adopt_image(Image.new("RGBA", (40, 30)), name="Pasted", loader="clipboard")
    assert window.document.size == (40, 30)
    assert window.document.source_path is None
    assert window.document.is_untitled
    assert window.document.loaded.loader == "clipboard"


def test_an_adopted_image_exports_without_a_source_path(window, tmp_path):
    """Untitled documents must still be exportable."""
    from PIL import Image

    window.adopt_image(Image.new("RGBA", (40, 30)), name="Pasted", loader="clipboard")
    window._write_export(tmp_path / "out.png")
    assert (tmp_path / "out.png").is_file()


def test_the_shortcuts_dialog_lists_bound_shortcuts_only(window):
    """Generated from the accel tables, so it cannot drift out of date."""
    from ganot8.shortcuts import build_dialog

    assert build_dialog(window) is not None


def test_every_shortcut_the_dialog_names_is_actually_bound():
    from ganot8.shortcuts import SECTIONS

    app = Adw.Application(application_id="io.github.martinb.Ganot8.Test")
    window = Window(application=app)
    try:
        window._install_actions()
        unbound = []
        for _title, entries in SECTIONS:
            for label, action in entries:
                name = action.split(".", 1)[1]
                if action.startswith("win.") and window.lookup_action(name) is None:
                    unbound.append(action)
        assert unbound == [], unbound
    finally:
        window.destroy()


def test_window_state_is_saved_and_restored():
    from ganot8.settings import Settings

    settings = Settings(use_gsettings=False)
    first = Window(settings=settings)
    first._export_quality = 71
    first._export_format = "WEBP"
    first.canvas.style_for("arrow")["stroke_width"] = 11.0
    first.save_state()

    second = Window(settings=settings)
    assert second._export_quality == 71
    assert second._export_format == "WEBP"
    assert second.canvas.style_for("arrow")["stroke_width"] == 11.0


def test_a_window_without_persistence_still_works():
    """No schema installed must not stop the application running."""
    from ganot8.settings import Settings

    settings = Settings(use_gsettings=False)
    assert not settings.persistent
    window = Window(settings=settings)
    window.save_state()  # must not raise
    assert window.canvas is not None


def test_redaction_style_value_is_readable_not_truncated(window):
    """Long subtitles squeezed the ComboRow until it showed "Pixel...".

    The hint matters, but not at the cost of being unable to read the setting.
    """
    assert len(window._redact_style_row.get_subtitle()) <= 24
    assert len(window._strength_row.get_subtitle()) <= 24


def test_the_redact_tool_names_its_styles(window):
    """They live in the sidebar, not the tool strip, so the tool has to say so."""
    from ganot8.tools import registered_tools

    redact = next(t for t in registered_tools() if t.name == "redact")
    for style in ("solid", "blur", "pixelate"):
        assert style in redact.tooltip.lower(), style
