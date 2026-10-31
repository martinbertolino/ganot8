"""The packaging definitions.

A build file that has never been run is worth less than none, so the Meson
build is exercised for real in development. What is checked here is the part
that can rot silently: that the build installs everything the application
needs, and that the declarations agree with the code.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
import yaml

from ganot8 import APP_ID, __version__

ROOT = Path(__file__).resolve().parent.parent
MESON = ROOT / "meson.build"
MANIFEST = ROOT / f"{APP_ID}.yml"
METAINFO = ROOT / "data" / f"{APP_ID}.metainfo.xml"
GRESOURCE_XML = ROOT / "data" / f"{APP_ID}.gresource.xml"


@pytest.fixture(scope="module")
def meson_text() -> str:
    return MESON.read_text()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text())


# -- meson -----------------------------------------------------------------


def test_the_build_files_exist():
    for path in (MESON, ROOT / "src" / "meson.build", ROOT / "data" / "meson.build"):
        assert path.is_file(), f"{path} is missing"


def test_project_version_matches_the_package(meson_text):
    """Two version numbers that disagree ship a package claiming the wrong one."""
    assert f"version: '{__version__}'" in meson_text


def test_the_launcher_template_is_installed(meson_text):
    assert (ROOT / "src" / "ganot8.in").is_file()
    assert "configure_file(" in (ROOT / "src" / "meson.build").read_text()


def test_the_launcher_carries_the_configured_paths():
    """A launcher with hard-coded paths is wrong for every prefix but one."""
    template = (ROOT / "src" / "ganot8.in").read_text()
    for placeholder in ("@PYTHON@", "@PKGLIBDIR@", "@PKGDATADIR@"):
        assert placeholder in template, placeholder


def test_data_build_installs_everything_the_app_needs():
    data_build = (ROOT / "data" / "meson.build").read_text()
    for needed in ("applications", "mime", "glib-2.0", "icons", "metainfo"):
        assert needed in data_build, f"{needed} is never installed"


def test_post_install_refreshes_the_desktop_caches():
    script = (ROOT / "meson" / "post-install.py").read_text()
    for tool in (
        "glib-compile-schemas",
        "update-desktop-database",
        "update-mime-database",
        "gtk4-update-icon-cache",
    ):
        assert tool in script, tool


def test_post_install_respects_destdir():
    """A staged build must leave the caches to the package manager."""
    assert "DESTDIR" in (ROOT / "meson" / "post-install.py").read_text()


# -- gresource -------------------------------------------------------------


def test_gresource_bundles_every_icon_the_tools_use():
    from ganot8.tools import registered_tools

    listed = {
        Path(node.text).name
        for node in ElementTree.parse(GRESOURCE_XML).getroot().iter("file")
    }
    bundled = {t.icon_name for t in registered_tools() if t.icon_name.startswith("ganot8-")}
    for icon in bundled:
        assert f"{icon}.svg" in listed, f"{icon} is used but not bundled"


def test_gresource_prefix_matches_the_code():
    from ganot8 import resources

    root = ElementTree.parse(GRESOURCE_XML).getroot()
    prefixes = {node.get("prefix") for node in root.iter("gresource")}
    assert resources.RESOURCE_PATH in prefixes


def test_every_bundled_file_exists():
    base = ROOT / "data" / "icons" / "hicolor"
    for node in ElementTree.parse(GRESOURCE_XML).getroot().iter("file"):
        assert (base / node.text).is_file(), node.text


# -- appstream -------------------------------------------------------------


def test_metainfo_identifies_the_application():
    root = ElementTree.parse(METAINFO).getroot()
    assert root.findtext("id") == APP_ID
    assert root.findtext("name")
    assert root.findtext("summary")


def test_metainfo_version_matches_the_package():
    root = ElementTree.parse(METAINFO).getroot()
    versions = [r.get("version") for r in root.iter("release")]
    assert __version__ in versions, f"{__version__} has no release entry"


def test_metainfo_points_at_the_desktop_entry():
    root = ElementTree.parse(METAINFO).getroot()
    assert root.findtext("launchable") == f"{APP_ID}.desktop"


def test_metainfo_declares_a_content_rating():
    """Software centres refuse an application without one."""
    assert ElementTree.parse(METAINFO).getroot().find("content_rating") is not None


# -- flatpak ---------------------------------------------------------------


def test_manifest_is_valid_yaml_and_names_the_application(manifest):
    assert manifest["id"] == APP_ID
    assert manifest["command"] == "ganot8"


def test_manifest_builds_the_application_with_meson(manifest):
    ganot8 = next(m for m in manifest["modules"] if m["name"] == "ganot8")
    assert ganot8["buildsystem"] == "meson"


def test_manifest_ships_the_python_dependencies(manifest):
    names = {module["name"] for module in manifest["modules"]}
    for dependency in ("pygobject", "pycairo", "pillow"):
        assert dependency in names, dependency


def test_manifest_pins_every_source_by_checksum(manifest):
    """An unpinned source makes the build neither reproducible nor safe."""
    for module in manifest["modules"]:
        for source in module.get("sources", []):
            if source["type"] == "archive":
                assert len(source.get("sha256", "")) == 64, module["name"]


def test_manifest_versions_match_requirements(manifest):
    """The sandbox must not build against different versions than the tests."""
    pinned = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, version = line.split("==")
            pinned[name.strip().lower()] = version.strip()

    for module in manifest["modules"]:
        name = module["name"].lower()
        if name not in pinned:
            continue
        urls = " ".join(
            s.get("url", "") for s in module.get("sources", []) if s["type"] == "archive"
        )
        assert pinned[name] in urls, f"{name} should be {pinned[name]}"


def test_manifest_requests_no_blanket_filesystem_access(manifest):
    """Images are chosen through the portal, so host-wide access is not needed."""
    for argument in manifest["finish-args"]:
        assert argument not in ("--filesystem=host", "--filesystem=home")


def test_manifest_says_it_is_unverified():
    """It has never been built; the file must not imply otherwise."""
    assert "NOT VERIFIED" in MANIFEST.read_text()
