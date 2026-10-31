"""The .ganot8 project container."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from ganot8.annotations import Box, Redact, TextLabel
from ganot8.document import Document
from ganot8.geometry import Point, Rect
from ganot8.imageio import project
from ganot8.imageio.loader import LoadedImage


@pytest.fixture
def document(rgba_image, tmp_path) -> Document:
    source = tmp_path / "shot.png"
    rgba_image.save(source, format="PNG")
    doc = Document(LoadedImage(image=rgba_image, path=source, format="PNG"))
    doc.annotations.extend(
        [
            Box(rect=Rect(1, 1, 3, 2), color=(0.2, 0.4, 0.6, 1.0)),
            Redact(rect=Rect(0, 0, 2, 2)),
            TextLabel(text="note", anchor=Point(1, 1), font="Sans 12"),
        ]
    )
    return doc


# -- structure -----------------------------------------------------------


def test_saved_project_is_a_zip_with_the_expected_entries(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "document.json",
            "source.png",
            "thumbnail.png",
        }


def test_document_json_records_the_format_version(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("document.json"))
    assert data["version"] == project.FORMAT_VERSION
    assert data["image"]["width"] == document.width
    assert len(data["annotations"]) == 3


def test_thumbnail_is_small_and_flattened(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    with zipfile.ZipFile(path) as archive, archive.open("thumbnail.png") as handle:
        with Image.open(handle) as thumb:
            assert max(thumb.size) <= max(project.THUMBNAIL_SIZE)


def test_source_is_stored_losslessly(document, tmp_path):
    """The whole point of a project is that the original survives intact."""
    path = project.save(document, tmp_path / "out.ganot8")
    restored = project.load(path)
    assert list(restored.image.get_flattened_data()) == list(
        document.source.get_flattened_data()
    )


# -- round trip ----------------------------------------------------------


def test_round_trip_preserves_annotations(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    reopened = Document.from_project(path)

    assert [a.kind for a in reopened.annotations] == ["box", "redact", "text"]
    assert reopened.annotations[0].rect == Rect(1, 1, 3, 2)
    assert reopened.annotations[2].text == "note"
    assert reopened.size == document.size


def test_round_trip_is_stable_across_two_saves(document, tmp_path):
    first = project.save(document, tmp_path / "a.ganot8")
    reopened = Document.from_project(first)
    second = reopened.save_project(tmp_path / "b.ganot8")

    assert project.load(first).annotations == project.load(second).annotations


def test_reopened_project_knows_its_own_path(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    reopened = Document.from_project(path)
    assert reopened.project_path == path
    assert reopened.is_project
    assert reopened.display_name == "out.ganot8"


def test_reopened_project_is_not_dirty(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    assert not Document.from_project(path).dirty


def test_saving_marks_the_document_clean(document, tmp_path):
    document.mark_dirty()
    document.save_project(tmp_path / "out.ganot8")
    assert not document.dirty
    assert document.project_path == tmp_path / "out.ganot8"


def test_export_name_falls_back_to_the_original_filename(document, tmp_path):
    """A project remembers what the image was called, for export naming."""
    path = project.save(document, tmp_path / "renamed.ganot8")
    reopened = Document.from_project(path)
    assert reopened.export_basis.name == "shot.png"


# -- forward compatibility -----------------------------------------------


def test_unknown_annotation_kinds_survive_a_round_trip(document, tmp_path):
    document.annotations_from_list(
        [{"kind": "hologram", "shimmer": True, "nested": {"a": 1}}]
    )
    path = project.save(document, tmp_path / "future.ganot8")
    assert project.load(path).annotations == [
        {"kind": "hologram", "shimmer": True, "nested": {"a": 1}}
    ]


def test_a_newer_format_version_loads_with_a_warning(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    _rewrite_document_json(path, lambda data: data.update(version=project.FORMAT_VERSION + 5))

    loaded = project.load(path)
    assert loaded.warnings and "newer version" in loaded.warnings[0]
    assert len(loaded.annotations) == 3


# -- failure modes -------------------------------------------------------


def test_missing_file_raises():
    with pytest.raises(project.ProjectError, match="does not exist"):
        project.load("/nonexistent/none.ganot8")


def test_a_plain_image_is_not_a_project(tmp_path, rgba_image):
    path = tmp_path / "plain.png"
    rgba_image.save(path)
    assert not project.looks_like_project(path)
    with pytest.raises(project.ProjectError):
        project.load(path)


def test_a_zip_without_document_json_is_rejected(tmp_path):
    path = tmp_path / "bogus.ganot8"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "not a project")
    with pytest.raises(project.ProjectError, match="not a Ganot8 project"):
        project.load(path)


def test_a_project_missing_its_source_is_rejected(tmp_path):
    path = tmp_path / "nosource.ganot8"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("document.json", json.dumps({"version": 1, "annotations": []}))
    with pytest.raises(project.ProjectError, match="missing source.png"):
        project.load(path)


def test_corrupt_json_is_reported_clearly(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    _replace_entry(path, "document.json", b"{ this is not json")
    with pytest.raises(project.ProjectError, match="not valid JSON"):
        project.load(path)


def test_truncated_file_is_reported_clearly(document, tmp_path):
    path = project.save(document, tmp_path / "out.ganot8")
    path.write_bytes(path.read_bytes()[:40])
    with pytest.raises(project.ProjectError):
        project.load(path)


def test_a_failed_save_leaves_the_previous_project_intact(document, tmp_path, monkeypatch):
    """Saving writes beside the target and renames, so a crash cannot shred it."""
    path = project.save(document, tmp_path / "out.ganot8")
    original = path.read_bytes()

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(project, "_encode_png", explode)
    with pytest.raises(OSError):
        project.save(document, path)

    assert path.read_bytes() == original
    assert not (tmp_path / "out.ganot8.tmp").exists()


# -- detection -----------------------------------------------------------


def test_looks_like_project_accepts_the_extension(tmp_path, document):
    path = project.save(document, tmp_path / "out.ganot8")
    assert project.looks_like_project(path)


def test_looks_like_project_accepts_a_renamed_project(tmp_path, document):
    """Content wins over extension, so a renamed project still opens."""
    path = project.save(document, tmp_path / "out.ganot8")
    renamed = path.with_suffix(".zip")
    path.rename(renamed)
    assert project.looks_like_project(renamed)


def test_default_project_path_sits_beside_the_image():
    assert project.default_project_path(Path("/tmp/a.png")) == Path("/tmp/a.ganot8")


# -- helpers -------------------------------------------------------------


def _replace_entry(path: Path, name: str, payload: bytes) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = {item: archive.read(item) for item in archive.namelist()}
    entries[name] = payload
    with zipfile.ZipFile(path, "w") as archive:
        for item, data in entries.items():
            archive.writestr(item, data)


def _rewrite_document_json(path: Path, mutate) -> None:
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("document.json"))
    mutate(data)
    _replace_entry(path, "document.json", json.dumps(data).encode())
