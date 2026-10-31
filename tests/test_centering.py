"""An opened image must appear centred straight away.

Regression test for a timing bug: fit-to-window was computed inside the
``notify::page-size`` handler, i.e. during the viewport's own size allocation.
Setting the content size at that moment is ignored for the cycle and leaves the
adjustments' ``upper`` at the previous value. With ``upper > page_size`` the
ScrolledWindow still thinks it can scroll, so it pins the child at 0 and
``halign=CENTER`` never applies - the image sat in the top-left until some
unrelated event forced a fresh layout.

These need a real toplevel, because the bug only exists in a genuine allocation
cycle; a stubbed scroller size would not reproduce it.
"""

from __future__ import annotations

import time

import pytest
from PIL import Image

from ganot8 import gi_init  # noqa: F401
from gi.repository import Adw, GLib, Gtk

if not Gtk.init_check():
    pytest.skip("no display available for GTK widgets", allow_module_level=True)

Adw.init()

from ganot8.window import Window  # noqa: E402

WINDOW_SIZE = (900, 600)


def pump(predicate, timeout: float = 5.0) -> bool:
    """Run the main loop until ``predicate`` holds, or time runs out."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


@pytest.fixture
def shown_window():
    window = Window()
    window.set_default_size(*WINDOW_SIZE)
    window.present()
    # The canvas lives in a Gtk.Stack page that stays unallocated until a
    # document is opened, so only wait for the toplevel here.
    assert pump(window.get_mapped), "window never mapped"
    yield window
    window.destroy()


def make_image(tmp_path, name: str, size: tuple[int, int]):
    path = tmp_path / name
    Image.new("RGB", size, (200, 120, 60)).save(path)
    return path


def settle(window) -> None:
    """Wait for the canvas to be allocated, then let the deferred passes run."""
    assert pump(lambda: window._scroller.get_width() > 1), "canvas never allocated"
    pump(lambda: False, timeout=0.3)


def axes(window):
    return (window._scroller.get_hadjustment(), window._scroller.get_vadjustment())


@pytest.mark.parametrize(
    "size",
    [
        (900, 560),    # wider than the viewport
        (2400, 1600),  # much larger
        (120, 90),     # smaller than the viewport
        (1800, 200),   # wide and short
        (200, 1400),   # tall and narrow
    ],
)
def test_opened_image_is_not_falsely_scrollable(shown_window, tmp_path, size):
    """After fitting, the content must not exceed the viewport.

    A stale ``upper`` shows up exactly here: it stays at the image's natural
    width while the content has already been scaled down to fit.
    """
    shown_window.open_path(make_image(tmp_path, "pic.png", size))
    settle(shown_window)

    for adjustment in axes(shown_window):
        assert adjustment.get_upper() <= adjustment.get_page_size() + 1, (
            f"content still reports as scrollable for {size}: "
            f"upper={adjustment.get_upper()} page={adjustment.get_page_size()}"
        )


def test_fit_zoom_is_applied_rather_than_left_at_100_percent(shown_window, tmp_path):
    shown_window.open_path(make_image(tmp_path, "big.png", (2400, 1600)))
    settle(shown_window)
    assert shown_window.canvas.zoom < 1.0
    assert shown_window.canvas.fit_mode


def test_a_second_image_is_also_centred(shown_window, tmp_path):
    """Opening another image must re-fit, not inherit the previous zoom."""
    shown_window.open_path(make_image(tmp_path, "first.png", (300, 200)))
    settle(shown_window)
    first_zoom = shown_window.canvas.zoom

    shown_window.open_path(make_image(tmp_path, "second.png", (3000, 2000)))
    settle(shown_window)

    assert shown_window.canvas.zoom < first_zoom
    for adjustment in axes(shown_window):
        assert adjustment.get_upper() <= adjustment.get_page_size() + 1


def test_image_too_large_to_fit_opens_centred(shown_window, tmp_path):
    """Below ZOOM_MIN the image stays scrollable, so it must start centred."""
    shown_window.open_path(make_image(tmp_path, "panorama.png", (20000, 400)))
    settle(shown_window)

    horizontal, _ = axes(shown_window)
    slack = horizontal.get_upper() - horizontal.get_page_size()
    assert slack > 0, "precondition: this image should not fit"
    assert horizontal.get_value() == pytest.approx(slack / 2, abs=2.0)


def test_a_small_image_is_not_scaled_up(shown_window, tmp_path):
    shown_window.open_path(make_image(tmp_path, "small.png", (120, 90)))
    settle(shown_window)
    assert shown_window.canvas.zoom == pytest.approx(1.0)


def test_manual_zoom_leaves_fit_mode_and_survives_a_resize(shown_window, tmp_path):
    """A deferred fit must not fight a zoom the user asked for."""
    shown_window.open_path(make_image(tmp_path, "pic.png", (900, 560)))
    settle(shown_window)

    shown_window.canvas.zoom_to(2.0)
    settle(shown_window)
    assert not shown_window.canvas.fit_mode
    assert shown_window.canvas.zoom == pytest.approx(2.0)


def test_dropped_image_is_centred_too(shown_window, tmp_path):
    """Drag-and-drop goes through the same path as Open, so it must centre."""
    from gi.repository import Gdk, Gio

    path = make_image(tmp_path, "dropped.png", (2400, 1600))
    file_list = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(path))])
    assert shown_window._on_drop(None, file_list, 0.0, 0.0)
    settle(shown_window)

    assert shown_window.document.display_name == "dropped.png"
    assert shown_window.canvas.zoom < 1.0
    for adjustment in axes(shown_window):
        assert adjustment.get_upper() <= adjustment.get_page_size() + 1
