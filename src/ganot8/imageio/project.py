"""The ``.ganot8`` project container.

A zip, like OpenRaster: one file, inspectable with standard tools, and easy to
extend without breaking older builds.

    document.json     metadata + the annotation list
    source.png        the pristine original, lossless
    thumbnail.png     a small flattened preview

A project keeps the **unredacted** original by design, which is what makes
annotations editable later. That is also why it must not be shared in place of
an export; see docs/SPEC.md section 6.
"""

from __future__ import annotations

import json
import logging
import os
import zipfile
from io import BytesIO
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

log = logging.getLogger(__name__)

SUFFIX = ".ganot8"
MIME_TYPE = "application/x-ganot8"
#: Bumped only for changes older builds could not read safely.
FORMAT_VERSION = 1

DOCUMENT_ENTRY = "document.json"
SOURCE_ENTRY = "source.png"
THUMBNAIL_ENTRY = "thumbnail.png"
THUMBNAIL_SIZE = (256, 256)


class ProjectError(Exception):
    """Raised when a file is not a readable Ganot8 project."""


@dataclass(frozen=True)
class LoadedProject:
    """What came out of a project file."""

    image: Image.Image
    data: dict[str, Any]
    path: Path
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def annotations(self) -> list[dict[str, Any]]:
        entries = self.data.get("annotations", [])
        return entries if isinstance(entries, list) else []

    @property
    def version(self) -> int:
        try:
            return int(self.data.get("version", FORMAT_VERSION))
        except (TypeError, ValueError):
            return FORMAT_VERSION


def looks_like_project(path: str | Path) -> bool:
    """True if ``path`` is a Ganot8 project, by extension or by content."""
    path = Path(path)
    if path.suffix.lower() == SUFFIX:
        return True
    if not path.is_file():
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return DOCUMENT_ENTRY in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def default_project_path(source: Path | None) -> Path:
    if source is None:
        return Path.home() / f"Untitled{SUFFIX}"
    return source.with_suffix(SUFFIX)


def save(document, path: str | Path) -> Path:
    """Write ``document`` to a project file, replacing it atomically.

    The archive is built beside the target and renamed into place, so an
    interrupted save cannot leave a half-written project where a good one was.
    """
    from . import exporter  # local import: exporter pulls in the renderer

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": FORMAT_VERSION,
        "application": "Ganot8",
        "image": {
            "width": document.width,
            "height": document.height,
            "source": SOURCE_ENTRY,
        },
        "source_name": document.source_path.name if document.source_path else None,
        "rotation": document.rotation,
        "crop": document.crop.to_list() if document.crop is not None else None,
        "annotations": document.annotations_to_list(),
    }

    temporary = path.with_name(path.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                DOCUMENT_ENTRY, json.dumps(payload, indent=2, ensure_ascii=False)
            )
            archive.writestr(SOURCE_ENTRY, _encode_png(document.source))
            archive.writestr(THUMBNAIL_ENTRY, _encode_png(_thumbnail(exporter, document)))
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def load(path: str | Path) -> LoadedProject:
    """Read a project file."""
    path = Path(path)
    if not path.exists():
        raise ProjectError(f"{path.name}: file does not exist")

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if DOCUMENT_ENTRY not in names:
                raise ProjectError(f"{path.name}: not a Ganot8 project (no {DOCUMENT_ENTRY})")
            if SOURCE_ENTRY not in names:
                raise ProjectError(f"{path.name}: project is missing {SOURCE_ENTRY}")
            data = json.loads(archive.read(DOCUMENT_ENTRY).decode("utf-8"))
            with Image.open(BytesIO(archive.read(SOURCE_ENTRY))) as opened:
                image = opened.convert("RGBA")
                image.load()
    except ProjectError:
        raise
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as error:
        raise ProjectError(f"{path.name}: damaged project file ({error})") from error
    except json.JSONDecodeError as error:
        raise ProjectError(f"{path.name}: {DOCUMENT_ENTRY} is not valid JSON ({error})") from error
    except OSError as error:
        raise ProjectError(f"{path.name}: could not be read ({error})") from error

    if not isinstance(data, dict):
        raise ProjectError(f"{path.name}: {DOCUMENT_ENTRY} is not an object")

    image.info.clear()

    warnings: list[str] = []
    version = data.get("version", FORMAT_VERSION)
    if isinstance(version, int) and version > FORMAT_VERSION:
        # Unknown annotation kinds round-trip verbatim, so this is safe to open;
        # the user just should not expect to edit what this build cannot draw.
        warnings.append(
            f"This project was written by a newer version of Ganot8 "
            f"(format {version}, this build reads {FORMAT_VERSION}). "
            "Anything unrecognised is preserved but not shown."
        )

    return LoadedProject(image=image, data=data, path=path, warnings=tuple(warnings))


def _thumbnail(exporter, document) -> Image.Image:
    flattened = exporter.flatten(document)
    flattened.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
    return flattened


def _encode_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    # No metadata is passed, matching the export rules in SPEC section 6.
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
