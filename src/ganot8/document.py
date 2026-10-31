"""The document model: one source image plus the annotations drawn over it.

The source pixels are never mutated by a tool. Annotations are separate objects
holding geometry in *source-image pixel coordinates*, so zoom, pan and window
size can never affect what gets exported.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import gi_init  # noqa: F401
from gi.repository import GObject

from .annotations import Annotation, Redact, annotation_from_dict
from .history import BurnInRedactions, History
from .imageio.loader import LoadedImage
from .surfaces import CairoImage, new_surface, pil_to_surface, surface_to_pil


class Document(GObject.Object):
    """A loaded image and its annotation list."""

    __gsignals__ = {
        # Something changed that requires a redraw.
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, loaded: LoadedImage):
        super().__init__()
        self._source: Image.Image = loaded.image
        self._loaded = loaded
        self.source_path: Path | None = loaded.path
        self.project_path: Path | None = None
        self.annotations: list[Annotation] = []
        self.history = History()
        self.rotation: int = 0
        self.crop = None
        self._dirty = False
        self._cairo_image: CairoImage | None = None
        #: Original filename remembered from a project, for export naming.
        self.source_name_hint: str | None = None

    # -- construction ----------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> Document:
        from .imageio.loader import load

        return cls(load(path))

    @classmethod
    def from_project(cls, path: str | Path) -> Document:
        """Open a ``.ganot8`` project, restoring its annotations."""
        from .imageio import project
        from .imageio.loader import LoadedImage

        loaded = project.load(path)
        source_name = loaded.data.get("source_name")
        document = cls(
            LoadedImage(
                image=loaded.image,
                path=None,
                format="ganot8",
                loader="project",
                warnings=loaded.warnings,
            )
        )
        document.project_path = Path(loaded.path)
        if isinstance(source_name, str) and source_name:
            document.source_name_hint = source_name
        document.annotations = [
            annotation_from_dict(entry) for entry in loaded.annotations
        ]
        rotation = loaded.data.get("rotation", 0)
        if isinstance(rotation, int):
            document.rotation = rotation
        document.mark_clean()
        return document

    def save_project(self, path: str | Path) -> Path:
        """Write this document to a ``.ganot8`` project file."""
        from .imageio import project

        written = project.save(self, path)
        self.project_path = Path(written)
        self.mark_clean()
        return written

    # -- source image ----------------------------------------------------

    @property
    def source(self) -> Image.Image:
        return self._source

    @property
    def width(self) -> int:
        return self._source.width

    @property
    def height(self) -> int:
        return self._source.height

    @property
    def size(self) -> tuple[int, int]:
        return self._source.size

    @property
    def cairo_image(self) -> CairoImage:
        """The source image as a Cairo surface, built on first use and cached."""
        if self._cairo_image is None:
            self._cairo_image = pil_to_surface(self._source)
        return self._cairo_image

    def replace_source(self, image: Image.Image) -> None:
        """Swap the source pixels (crop, rotate, burn-in) and drop the cache."""
        self._source = image if image.mode == "RGBA" else image.convert("RGBA")
        self._cairo_image = None
        self.mark_dirty()

    # -- metadata --------------------------------------------------------

    @property
    def loaded(self) -> LoadedImage:
        return self._loaded

    @property
    def display_name(self) -> str:
        if self.project_path is not None:
            return self.project_path.name
        if self.source_path is not None:
            return self.source_path.name
        return "Untitled"

    @property
    def is_project(self) -> bool:
        return self.project_path is not None

    @property
    def export_basis(self) -> Path | None:
        """The path export filenames should be derived from."""
        if self.source_path is not None:
            return self.source_path
        if self.project_path is not None:
            if self.source_name_hint:
                return self.project_path.with_name(self.source_name_hint)
            return self.project_path
        return None

    @property
    def is_untitled(self) -> bool:
        return self.source_path is None and self.project_path is None

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def has_redactions(self) -> bool:
        return any(getattr(a, "kind", None) == "redact" for a in self.annotations)

    @property
    def redactions(self) -> list[Annotation]:
        return [a for a in self.annotations if isinstance(a, Redact)]

    def burn_in_redactions(self) -> bool:
        """Merge every redaction into the source pixels, as one undo step.

        Returns False when there is nothing to burn in.
        """
        redactions = self.redactions
        if not redactions:
            return False

        import cairo

        surface = new_surface(self.width, self.height)
        cr = cairo.Context(surface)
        cr.set_source_surface(self.cairo_image.surface, 0, 0)
        cr.paint()
        for redaction in redactions:
            cr.save()
            try:
                redaction.draw(cr)
            finally:
                cr.restore()
        surface.flush()

        burnt = surface_to_pil(surface)
        burnt.info.clear()
        return self.history.push(BurnInRedactions(self, burnt, redactions))

    def mark_dirty(self) -> None:
        self._dirty = True
        self.emit("changed")

    def mark_clean(self) -> None:
        self._dirty = False

    # -- annotations -----------------------------------------------------

    def annotations_to_list(self) -> list[dict]:
        """Serialise the annotation list, preserving unknown kinds verbatim."""
        return [annotation.to_dict() for annotation in self.annotations]

    def annotations_from_list(self, data) -> None:
        self.annotations = [annotation_from_dict(entry) for entry in data]
        self.mark_dirty()

    def annotation_at(self, point, tolerance: float = 0.0) -> Annotation | None:
        """Topmost selectable annotation under ``point``.

        Iterates in reverse because the end of the list is drawn last and so
        sits on top.
        """
        for annotation in reversed(self.annotations):
            if annotation.selectable and annotation.hit_test(point, tolerance):
                return annotation
        return None

    def annotations_in(self, rect) -> list[Annotation]:
        """Selectable annotations fully enclosed by ``rect``."""
        return [
            annotation
            for annotation in self.annotations
            if annotation.selectable and rect.contains_rect(annotation.bounds())
        ]
