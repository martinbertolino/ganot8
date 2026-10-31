"""Window wiring: tool strip, style sidebar, action sensitivity.

Needs a display, like test_tools.py.
"""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8 import gi_init  # noqa: F401
from gi.repository import Adw, Gdk, Gtk

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
    window.canvas.clear_selection()
    window._width_row.set_value(7.0)
    assert window.canvas.tool_style["stroke_width"] == pytest.approx(7.0)
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
    annotation = add_box(window)
    window.canvas.set_selection([annotation])
    window._filled_row.set_active(True)
    assert annotation.filled is True
    assert window.document.history.undo_label == "Change Fill"


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
