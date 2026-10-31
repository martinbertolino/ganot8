"""The Redact tool: cover something up for good."""

from __future__ import annotations

from typing import ClassVar

from ..annotations import Redact
from .shapes import RectangleTool


class RedactTool(RectangleTool):
    name: ClassVar[str] = "redact"
    label: ClassVar[str] = "Redact"
    icon_name: ClassVar[str] = "ganot8-redact-symbolic"
    accelerator: ClassVar[str] = "r"
    # Names the styles, because they live in the sidebar rather than in the
    # tool strip and are otherwise easy to miss entirely.
    tooltip: ClassVar[str] = "Hide a region \u2014 solid, blur or pixelate (R)"
    annotation_type: ClassVar[type] = Redact
    create_label: ClassVar[str] = "Add Redaction"
