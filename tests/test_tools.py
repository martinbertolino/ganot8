"""Tool behaviour, driven through a real Canvas.

These use the actual Canvas rather than a stand-in, so the tool/canvas contract
is genuinely exercised. GTK needs a display to construct widgets, so the whole
module skips when there is none.
"""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8 import gi_init  # noqa: F401
from gi.repository import Gdk, Gtk

from ganot8.annotations import Box
from ganot8.document import Document
from ganot8.geometry import Handle, Point, Rect
from ganot8.imageio.loader import LoadedImage

if not Gtk.init_check():
    pytest.skip("no display available for GTK widgets", allow_module_level=True)

from ganot8.canvas import Canvas  # noqa: E402

NONE = Gdk.ModifierType(0)
SHIFT = Gdk.ModifierType.SHIFT_MASK


@pytest.fixture
def canvas() -> Canvas:
    widget = Canvas()
    widget.set_document(Document(LoadedImage(image=Image.new("RGBA", (400, 300)))))
    return widget


def add_box(canvas: Canvas, x=0, y=0, size=100, **kwargs) -> Box:
    annotation = Box(rect=Rect(x, y, size, size), **kwargs)
    canvas.document.annotations.append(annotation)
    return annotation


def click(canvas: Canvas, x: float, y: float, state=NONE) -> None:
    tool = canvas.tool
    tool.on_drag_begin(Point(x, y), state)
    tool.on_drag_end(Point(x, y), state)


def drag(canvas: Canvas, start: tuple, end: tuple, state=NONE, steps: int = 4) -> None:
    tool = canvas.tool
    x0, y0 = start
    x1, y1 = end
    tool.on_drag_begin(Point(x0, y0), state)
    for step in range(1, steps + 1):
        fraction = step / steps
        tool.on_drag_update(
            Point(x0 + (x1 - x0) * fraction, y0 + (y1 - y0) * fraction), state
        )
    tool.on_drag_end(Point(x1, y1), state)


# -- select tool ---------------------------------------------------------


def test_default_tool_is_select(canvas):
    assert canvas.tool_name == "select"


def test_click_on_an_annotation_selects_it(canvas):
    annotation = add_box(canvas, filled=True)
    click(canvas, 50, 50)
    assert canvas.selection == [annotation]


def test_click_on_empty_space_clears_the_selection(canvas):
    annotation = add_box(canvas, filled=True)
    canvas.set_selection([annotation])
    click(canvas, 350, 250)
    assert canvas.selection == []


def test_shift_click_extends_the_selection(canvas):
    first = add_box(canvas, 0, 0, 50, filled=True)
    second = add_box(canvas, 200, 0, 50, filled=True)
    click(canvas, 25, 25)
    click(canvas, 225, 25, state=SHIFT)
    assert set(canvas.selection) == {first, second}


def test_shift_click_on_a_selected_annotation_removes_it(canvas):
    first = add_box(canvas, 0, 0, 50, filled=True)
    second = add_box(canvas, 200, 0, 50, filled=True)
    canvas.set_selection([first, second])
    click(canvas, 25, 25, state=SHIFT)
    assert canvas.selection == [second]


def test_drag_moves_the_selection(canvas):
    annotation = add_box(canvas, 0, 0, 100, filled=True)
    drag(canvas, (50, 50), (90, 70))
    assert annotation.rect == Rect(40, 20, 100, 100)


def test_a_drag_records_exactly_one_undo_step(canvas):
    """Motion events must coalesce: a drag undoes in one go, not frame by frame."""
    annotation = add_box(canvas, 0, 0, 100, filled=True)
    drag(canvas, (50, 50), (120, 120), steps=25)
    assert canvas.document.history.depth == 1
    canvas.document.history.undo()
    assert annotation.rect == Rect(0, 0, 100, 100)


def test_tiny_drag_is_treated_as_a_click_and_moves_nothing(canvas):
    annotation = add_box(canvas, 0, 0, 100, filled=True)
    drag(canvas, (50, 50), (51, 51), steps=1)
    assert annotation.rect == Rect(0, 0, 100, 100)
    assert canvas.document.history.depth == 0


def test_dragging_a_handle_resizes(canvas):
    annotation = add_box(canvas, 0, 0, 100)
    canvas.set_selection([annotation])
    handle = annotation.handles()[Handle.SE]
    drag(canvas, (handle.x, handle.y), (60, 40))
    assert annotation.rect == Rect(0, 0, 60, 40)
    assert canvas.document.history.undo_label == "Resize"


def test_handles_only_respond_for_a_single_selection(canvas):
    """With several selected there is no unambiguous handle, so it must move."""
    first = add_box(canvas, 0, 0, 100)
    second = add_box(canvas, 200, 0, 100)
    canvas.set_selection([first, second])
    # Press on first's SE handle position; with two selected this is a move.
    drag(canvas, (100, 100), (60, 40))
    assert (first.rect.width, first.rect.height) == (100, 100)
    assert (second.rect.width, second.rect.height) == (100, 100)
    assert canvas.document.history.undo_label == "Move"


def test_marquee_selects_fully_enclosed_annotations(canvas):
    inside = add_box(canvas, 20, 20, 40)
    straddling = add_box(canvas, 150, 150, 200)
    drag(canvas, (5, 5), (140, 140))
    assert canvas.selection == [inside]
    assert straddling not in canvas.selection


def test_marquee_does_not_create_an_undo_step(canvas):
    add_box(canvas, 20, 20, 40)
    drag(canvas, (5, 5), (140, 140))
    assert canvas.document.history.depth == 0


def test_nudge_moves_by_one_pixel(canvas):
    annotation = add_box(canvas, 10, 10, 20)
    canvas.set_selection([annotation])
    assert canvas.tool.on_key(Gdk.KEY_Right, NONE)
    assert annotation.rect == Rect(11, 10, 20, 20)


def test_shift_nudge_moves_by_ten(canvas):
    annotation = add_box(canvas, 10, 10, 20)
    canvas.set_selection([annotation])
    canvas.tool.on_key(Gdk.KEY_Down, SHIFT)
    assert annotation.rect == Rect(10, 20, 20, 20)


def test_nudge_without_a_selection_is_ignored(canvas):
    assert not canvas.tool.on_key(Gdk.KEY_Right, NONE)


def test_delete_selection_is_undoable(canvas):
    annotation = add_box(canvas)
    canvas.set_selection([annotation])
    assert canvas.delete_selection()
    assert canvas.document.annotations == []
    assert canvas.selection == []
    canvas.document.history.undo()
    assert canvas.document.annotations == [annotation]


def test_undo_drops_deleted_annotations_from_the_selection(canvas):
    """After undoing an Add, the selection must not hold a dangling object."""
    annotation = add_box(canvas)
    canvas.set_selection([annotation])
    canvas.document.annotations.remove(annotation)
    canvas.document.mark_dirty()
    assert canvas.selection == []


def test_hit_tolerance_scales_with_zoom(canvas):
    canvas.zoom_to(1.0)
    loose = canvas.hit_tolerance
    canvas.zoom_to(4.0)
    assert canvas.hit_tolerance < loose


# -- box tool ------------------------------------------------------------


def test_box_tool_creates_an_annotation(canvas):
    canvas.activate_tool("box")
    drag(canvas, (10, 20), (110, 90))
    assert len(canvas.document.annotations) == 1
    assert canvas.document.annotations[0].rect == Rect(10, 20, 100, 70)


def test_box_tool_records_one_undo_step_and_selects_the_result(canvas):
    canvas.activate_tool("box")
    drag(canvas, (10, 10), (110, 110))
    created = canvas.document.annotations[0]
    assert canvas.document.history.depth == 1
    assert canvas.selection == [created]


def test_box_tool_hands_back_to_select(canvas):
    """So a freshly drawn shape can be adjusted without changing tool."""
    canvas.activate_tool("box")
    drag(canvas, (10, 10), (110, 110))
    assert canvas.tool_name == "select"


def test_box_tool_discards_a_stray_click(canvas):
    canvas.activate_tool("box")
    drag(canvas, (10, 10), (11, 11), steps=1)
    assert canvas.document.annotations == []
    assert canvas.document.history.depth == 0


def test_box_tool_normalises_an_upward_drag(canvas):
    canvas.activate_tool("box")
    drag(canvas, (100, 100), (20, 30))
    assert canvas.document.annotations[0].rect == Rect(20, 30, 80, 70)


def test_shift_constrains_the_box_to_a_square(canvas):
    canvas.activate_tool("box")
    drag(canvas, (0, 0), (100, 40), state=SHIFT)
    rect = canvas.document.annotations[0].rect
    assert rect.width == rect.height == 100


def test_new_annotations_take_the_current_tool_style(canvas):
    canvas.tool_style["color"] = (0.0, 0.0, 1.0, 1.0)
    canvas.tool_style["stroke_width"] = 8.0
    canvas.activate_tool("box")
    drag(canvas, (0, 0), (50, 50))
    created = canvas.document.annotations[0]
    assert created.color == (0.0, 0.0, 1.0, 1.0)
    assert created.stroke_width == 8.0


def test_switching_tools_abandons_an_in_progress_shape(canvas):
    canvas.activate_tool("box")
    canvas.tool.on_drag_begin(Point(0, 0), NONE)
    canvas.tool.on_drag_update(Point(50, 50), NONE)
    canvas.activate_tool("select")
    assert canvas.document.annotations == []


def test_identical_annotations_are_distinct_objects(canvas):
    """Two boxes with the same geometry must not be interchangeable.

    Dataclass value equality made list.index()/remove() match the first one,
    so deleting one of a pair deleted the wrong annotation.
    """
    first = add_box(canvas, 0, 0, 100, filled=True)
    second = add_box(canvas, 0, 0, 100, filled=True)
    assert first != second
    assert canvas.document.annotations.index(second) == 1

    canvas.set_selection([second])
    canvas.delete_selection()
    assert canvas.document.annotations == [first]
    assert canvas.document.annotations[0] is first

    canvas.document.history.undo()
    assert canvas.document.annotations[1] is second


def test_selection_chrome_never_reaches_an_export(tmp_path, canvas):
    """Handles and marquee are drawn by the canvas, outside render.draw_document.

    If selection chrome ever moved into the shared render path, an exported
    image would carry dashed outlines and handle squares.
    """
    from PIL import ImageChops

    from ganot8.imageio import exporter

    add_box(canvas, 10, 10, 80)
    canvas.clear_selection()
    unselected = exporter.flatten(canvas.document)

    canvas.select_all()
    assert canvas.selection, "precondition: something must be selected"
    selected = exporter.flatten(canvas.document)

    assert ImageChops.difference(unselected, selected).getbbox() is None
