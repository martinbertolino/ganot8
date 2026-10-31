"""The five core tools, driven through a real Canvas."""

from __future__ import annotations

import pytest
from PIL import Image

from ganot8 import gi_init  # noqa: F401
from gi.repository import Gdk, Gtk

from ganot8.annotations import Arrow, Highlight, Redact, TextLabel, Underline
from ganot8.document import Document
from ganot8.geometry import Point, Rect
from ganot8.imageio.loader import LoadedImage

from support import SKIP_REASON, display_available  # noqa: E402

if not display_available():
    pytest.skip(SKIP_REASON, allow_module_level=True)

Gtk.init()

from ganot8.canvas import Canvas  # noqa: E402

NONE = Gdk.ModifierType(0)
SHIFT = Gdk.ModifierType.SHIFT_MASK


@pytest.fixture
def canvas() -> Canvas:
    widget = Canvas()
    widget.set_document(Document(LoadedImage(image=Image.new("RGBA", (400, 300)))))
    return widget


def drag(canvas: Canvas, start, end, state=NONE, steps: int = 4) -> None:
    tool = canvas.tool
    x0, y0 = start
    x1, y1 = end
    tool.on_drag_begin(Point(x0, y0), state)
    for step in range(1, steps + 1):
        fraction = step / steps
        tool.on_drag_update(Point(x0 + (x1 - x0) * fraction, y0 + (y1 - y0) * fraction), state)
    tool.on_drag_end(Point(x1, y1), state)


# -- the tool strip ------------------------------------------------------


def test_every_core_tool_is_available(canvas):
    names = [tool.name for tool in canvas.available_tools()]
    assert names == ["select", "highlight", "redact", "underline", "arrow", "text", "box"]


@pytest.mark.parametrize(
    "tool_name,expected",
    [
        ("highlight", Highlight),
        ("redact", Redact),
        ("underline", Underline),
        ("arrow", Arrow),
        ("box", type(None)),
    ],
)
def test_each_tool_creates_its_own_kind(canvas, tool_name, expected):
    canvas.activate_tool(tool_name)
    drag(canvas, (20, 20), (120, 80))
    created = canvas.document.annotations[0]
    if expected is not type(None):
        assert isinstance(created, expected)
    assert canvas.document.history.depth == 1
    assert canvas.selection == [created]
    # Every creation tool hands back to Select so the result can be adjusted.
    assert canvas.tool_name == "select"


# -- highlight and redact ------------------------------------------------


def test_highlight_tool_uses_the_kind_defaults_not_the_global_ones(canvas):
    """Each tool remembers its own style; Highlight must start yellow."""
    canvas.activate_tool("highlight")
    drag(canvas, (0, 0), (100, 50))
    created = canvas.document.annotations[0]
    assert created.opacity == pytest.approx(0.35)
    assert created.color[0] > 0.9 and created.color[2] < 0.4


def test_redact_tool_starts_opaque_black(canvas):
    canvas.activate_tool("redact")
    drag(canvas, (0, 0), (100, 50))
    created = canvas.document.annotations[0]
    assert created.color[:3] == (0.0, 0.0, 0.0)
    assert created.opacity == pytest.approx(1.0)


def test_tool_styles_are_remembered_separately(canvas):
    canvas.style_for("highlight")["color"] = (0.0, 1.0, 0.0, 1.0)
    canvas.style_for("redact")["color"] = (0.0, 0.0, 0.0, 1.0)

    canvas.activate_tool("highlight")
    drag(canvas, (0, 0), (50, 20))
    canvas.activate_tool("redact")
    drag(canvas, (0, 100), (50, 120))

    highlight, redact = canvas.document.annotations
    assert highlight.color == (0.0, 1.0, 0.0, 1.0)
    assert redact.color[:3] == (0.0, 0.0, 0.0)


def test_redaction_marks_the_document(canvas):
    canvas.activate_tool("redact")
    drag(canvas, (0, 0), (50, 20))
    assert canvas.document.has_redactions


# -- underline and arrow -------------------------------------------------


def test_underline_is_forced_horizontal(canvas):
    """A sloping underline is never what was meant."""
    canvas.activate_tool("underline")
    drag(canvas, (10, 50), (150, 95))
    underline = canvas.document.annotations[0]
    assert underline.start.y == underline.end.y == 50


def test_arrow_keeps_the_dragged_direction(canvas):
    canvas.activate_tool("arrow")
    drag(canvas, (10, 10), (100, 80))
    arrow = canvas.document.annotations[0]
    assert arrow.start == Point(10, 10)
    assert arrow.end == Point(100, 80)


def test_arrow_points_away_from_where_the_drag_started(canvas):
    """The head belongs at the end, so you drag from label to subject."""
    canvas.activate_tool("arrow")
    drag(canvas, (10, 10), (100, 10))
    arrow = canvas.document.annotations[0]
    assert arrow.end.x > arrow.start.x


def test_shift_constrains_an_arrow_to_45_degrees(canvas):
    canvas.activate_tool("arrow")
    drag(canvas, (0, 0), (100, 90), state=SHIFT)
    arrow = canvas.document.annotations[0]
    dx = arrow.end.x - arrow.start.x
    dy = arrow.end.y - arrow.start.y
    assert dx == pytest.approx(dy, rel=1e-6)


def test_a_click_creates_no_line(canvas):
    canvas.activate_tool("arrow")
    drag(canvas, (50, 50), (51, 50), steps=1)
    assert canvas.document.annotations == []


# -- text ----------------------------------------------------------------


def test_text_tool_requests_an_editor_without_adding_anything_yet(canvas):
    requested = []
    canvas.connect("text-edit-requested", lambda _c, a: requested.append(a))
    canvas.activate_tool("text")
    drag(canvas, (40, 40), (40, 40), steps=1)

    assert len(requested) == 1
    assert isinstance(requested[0], TextLabel)
    # Nothing is committed until the editor returns some text.
    assert canvas.document.annotations == []
    assert canvas.editing_text is requested[0]


def test_committing_text_adds_it_as_one_undo_step(canvas):
    canvas.activate_tool("text")
    drag(canvas, (40, 40), (40, 40), steps=1)
    canvas.commit_text_edit("Look here")

    assert len(canvas.document.annotations) == 1
    label = canvas.document.annotations[0]
    assert label.text == "Look here"
    assert label.anchor == Point(40, 40)
    assert canvas.document.history.depth == 1
    assert canvas.selection == [label]
    assert canvas.tool_name == "select"


def test_committing_empty_text_adds_nothing(canvas):
    canvas.activate_tool("text")
    drag(canvas, (40, 40), (40, 40), steps=1)
    canvas.commit_text_edit("   \n  ")
    assert canvas.document.annotations == []
    assert canvas.document.history.depth == 0


def test_cancelling_a_new_label_adds_nothing(canvas):
    canvas.activate_tool("text")
    drag(canvas, (40, 40), (40, 40), steps=1)
    canvas.cancel_text_edit()
    assert canvas.document.annotations == []
    assert canvas.editing_text is None


def test_dragging_the_text_tool_sets_a_wrap_width(canvas):
    canvas.activate_tool("text")
    drag(canvas, (20, 20), (220, 20))
    canvas.commit_text_edit("a reasonably long sentence that should wrap")
    assert canvas.document.annotations[0].wrap_width == pytest.approx(200)


def test_a_short_text_drag_leaves_the_label_unwrapped(canvas):
    canvas.activate_tool("text")
    drag(canvas, (20, 20), (30, 20))
    canvas.commit_text_edit("short")
    assert canvas.document.annotations[0].wrap_width is None


def test_double_click_reopens_an_existing_label(canvas):
    label = TextLabel(text="before", anchor=Point(10, 10), font="Sans 18")
    canvas.document.annotations.append(label)
    requested = []
    canvas.connect("text-edit-requested", lambda _c, a: requested.append(a))

    canvas.tool.on_double_click(Point(12, 12), NONE)
    assert requested == [label]
    assert canvas.selection == [label]


def test_editing_an_existing_label_is_one_undoable_change(canvas):
    label = TextLabel(text="before", anchor=Point(10, 10), font="Sans 18")
    canvas.document.annotations.append(label)
    canvas.begin_text_edit(label, is_new=False)
    canvas.commit_text_edit("after")

    assert label.text == "after"
    assert canvas.document.history.undo_label == "Edit Text"
    canvas.document.history.undo()
    assert label.text == "before"


def test_cancelling_an_edit_restores_the_previous_text(canvas):
    label = TextLabel(text="before", anchor=Point(10, 10), font="Sans 18")
    canvas.document.annotations.append(label)
    canvas.begin_text_edit(label, is_new=False)
    label.text = "half typed"
    canvas.cancel_text_edit()
    assert label.text == "before"
    assert not canvas.document.history.can_undo


def test_emptying_an_existing_label_deletes_it(canvas):
    """Rather than leaving an invisible annotation behind."""
    label = TextLabel(text="before", anchor=Point(10, 10), font="Sans 18")
    canvas.document.annotations.append(label)
    canvas.begin_text_edit(label, is_new=False)
    canvas.commit_text_edit("")

    assert canvas.document.annotations == []
    assert canvas.document.history.undo_label == "Delete Text"
    canvas.document.history.undo()
    assert canvas.document.annotations == [label]


def test_unchanged_text_records_no_undo_step(canvas):
    label = TextLabel(text="same", anchor=Point(10, 10), font="Sans 18")
    canvas.document.annotations.append(label)
    canvas.begin_text_edit(label, is_new=False)
    canvas.commit_text_edit("same")
    assert not canvas.document.history.can_undo


def test_double_click_on_a_non_text_annotation_does_nothing(canvas):
    canvas.activate_tool("redact")
    drag(canvas, (0, 0), (100, 50))
    requested = []
    canvas.connect("text-edit-requested", lambda _c, a: requested.append(a))
    canvas.tool.on_double_click(Point(50, 25), NONE)
    assert requested == []


# -- shared behaviour ----------------------------------------------------


@pytest.mark.parametrize("tool_name", ["highlight", "redact", "underline", "arrow", "box"])
def test_switching_tools_abandons_an_in_progress_shape(canvas, tool_name):
    canvas.activate_tool(tool_name)
    canvas.tool.on_drag_begin(Point(0, 0), NONE)
    canvas.tool.on_drag_update(Point(80, 60), NONE)
    canvas.activate_tool("select")
    assert canvas.document.annotations == []


@pytest.mark.parametrize("tool_name", ["highlight", "redact", "underline", "arrow"])
def test_created_annotations_are_selectable_and_movable(canvas, tool_name):
    canvas.activate_tool(tool_name)
    drag(canvas, (20, 40), (160, 90))
    created = canvas.document.annotations[0]
    before = created.bounds()

    canvas.activate_tool("select")
    canvas.set_selection([created])
    assert canvas.tool.on_key(Gdk.KEY_Right, SHIFT)
    assert created.bounds().x == pytest.approx(before.x + 10)


def test_box_tool_creates_a_filled_rectangle_by_default(canvas):
    canvas.activate_tool("box")
    drag(canvas, (20, 20), (120, 80))
    created = canvas.document.annotations[0]
    assert created.filled is True
    # Filled means the whole shape is the click target, not just its outline.
    assert created.hit_test(Point(70, 50), 1)


def test_choosing_a_creation_tool_clears_the_selection(canvas):
    """So the style sidebar describes what the tool will make, not the past."""
    canvas.activate_tool("box")
    drag(canvas, (10, 10), (110, 90))
    created = canvas.document.annotations[0]
    assert canvas.selection == [created]

    canvas.activate_tool("highlight")
    assert canvas.selection == []
    # The annotation itself is untouched; only the selection changed.
    assert canvas.document.annotations == [created]


def test_switching_to_select_does_not_clear_the_selection(canvas):
    canvas.activate_tool("box")
    drag(canvas, (10, 10), (110, 90))
    created = canvas.document.annotations[0]
    canvas.activate_tool("select")
    assert canvas.selection == [created]
