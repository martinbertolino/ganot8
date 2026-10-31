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
    tooltip: ClassVar[str] = "Block out a region (R)"
    annotation_type: ClassVar[type] = Redact
    create_label: ClassVar[str] = "Add Redaction"
