"""The files that make Ganot8 a desktop application rather than a script.

These are easy to get subtly wrong and give no feedback when you do: a bad
.desktop entry simply does not appear, and a MIME rule that loses to the
generic zip rule just means projects open in an archive manager.
"""

from __future__ import annotations

import configparser
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

from ganot8 import APP_ID

DATA = Path(__file__).resolve().parent.parent / "data"
DESKTOP = DATA / f"{APP_ID}.desktop"
MIME = DATA / f"{APP_ID}.mime.xml"
ICON = DATA / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
SCHEMA = DATA / "schemas" / f"{APP_ID}.gschema.xml"


@pytest.fixture(scope="module")
def entry() -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(DESKTOP)
    return parser["Desktop Entry"]


def test_every_desktop_file_is_present():
    for path in (DESKTOP, MIME, ICON, SCHEMA):
        assert path.is_file(), f"{path.name} is missing"


def test_desktop_entry_has_the_required_keys(entry):
    for key in ("Type", "Name", "Exec", "Icon"):
        assert entry.get(key), f"{key} is required"
    assert entry["Type"] == "Application"


def test_desktop_entry_accepts_a_file_argument(entry):
    """Without %f, "Open With" would launch the app but not the image."""
    assert "%f" in entry["Exec"] or "%F" in entry["Exec"]


def test_desktop_icon_matches_the_shipped_icon(entry):
    assert entry["Icon"] == APP_ID
    assert ICON.stem == APP_ID


def test_desktop_entry_advertises_the_project_type(entry):
    assert "application/x-ganot8" in entry["MimeType"]


def test_desktop_entry_advertises_the_formats_the_loader_handles(entry):
    advertised = set(filter(None, entry["MimeType"].split(";")))
    for mime in ("image/png", "image/jpeg", "image/webp", "image/avif", "image/svg+xml"):
        assert mime in advertised, mime


def test_mime_rule_claims_the_project_extension():
    root = ElementTree.parse(MIME).getroot()
    namespace = "{http://www.freedesktop.org/standards/shared-mime-info}"
    mime_type = root.find(f"{namespace}mime-type")
    assert mime_type.get("type") == "application/x-ganot8"
    globs = [g.get("pattern") for g in mime_type.iter(f"{namespace}glob")]
    assert "*.ganot8" in globs


def test_mime_rule_outranks_the_generic_zip_rule():
    """A project is a zip; without a higher priority it would open as one."""
    root = ElementTree.parse(MIME).getroot()
    namespace = "{http://www.freedesktop.org/standards/shared-mime-info}"
    magic = root.find(f".//{namespace}magic")
    assert magic is not None, "no magic rule"
    assert int(magic.get("priority", "50")) > 50


def test_project_suffix_agrees_with_the_mime_rule():
    from ganot8.imageio import project

    root = ElementTree.parse(MIME).getroot()
    namespace = "{http://www.freedesktop.org/standards/shared-mime-info}"
    globs = [g.get("pattern") for g in root.iter(f"{namespace}glob")]
    assert f"*{project.SUFFIX}" in globs
    mime_type = root.find(f"{namespace}mime-type")
    assert mime_type.get("type") == project.MIME_TYPE


def test_app_icon_is_valid_svg_with_a_viewbox():
    root = ElementTree.parse(ICON).getroot()
    assert root.tag.endswith("svg")
    assert root.get("viewBox")


def test_install_script_offers_an_uninstall():
    """Anything that writes into a home directory should take itself back out."""
    script = (DATA.parent / "install-user.sh").read_text()
    assert "--uninstall" in script
