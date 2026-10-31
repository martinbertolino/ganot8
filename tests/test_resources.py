"""The icons shipped with the application."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

import pytest

from ganot8 import resources
from ganot8.tools import registered_tools

BUNDLED = (
    "ganot8-select-symbolic",
    "ganot8-highlight-symbolic",
    "ganot8-redact-symbolic",
    "ganot8-ellipse-symbolic",
    "ganot8-badge-symbolic",
    "ganot8-crop-symbolic",
)


def test_icon_directory_follows_the_theme_layout():
    """GTK only finds icons under <search path>/<theme>/<size>/<context>/."""
    assert (resources.ICON_PATH / "hicolor" / "scalable" / "actions").is_dir()


@pytest.mark.parametrize("name", BUNDLED)
def test_bundled_icon_exists_and_is_valid_svg(name):
    path = resources.ICON_PATH / "hicolor" / "scalable" / "actions" / f"{name}.svg"
    assert path.is_file(), f"{name} is referenced by a tool but not shipped"
    root = ElementTree.parse(path).getroot()
    assert root.tag.endswith("svg")
    assert root.get("viewBox"), "a symbolic icon needs a viewBox to scale cleanly"


@pytest.mark.parametrize("name", BUNDLED)
def test_bundled_icon_is_named_symbolic(name):
    """GTK only recolours an icon for the current theme if it ends -symbolic."""
    assert name.endswith("-symbolic")


def test_tools_that_use_bundled_icons_match_the_shipped_files():
    used = {t.icon_name for t in registered_tools() if t.icon_name.startswith("ganot8-")}
    assert used == set(BUNDLED)


def test_install_icons_is_idempotent():
    first = resources.install_icons()
    assert resources.install_icons() == first
