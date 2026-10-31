"""The Highlight tool."""

from __future__ import annotations

from typing import ClassVar

from ..annotations import Highlight
from .shapes import RectangleTool


class HighlightTool(RectangleTool):
    name: ClassVar[str] = "highlight"
    label: ClassVar[str] = "Highlight"
    icon_name: ClassVar[str] = "ganot8-highlight-symbolic"
    accelerator: ClassVar[str] = "h"
    tooltip: ClassVar[str] = "Highlight a region (H)"
    annotation_type: ClassVar[type] = Highlight
    create_label: ClassVar[str] = "Add Highlight"
