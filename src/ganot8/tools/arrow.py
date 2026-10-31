"""The Arrow tool."""

from __future__ import annotations

from typing import ClassVar

from ..annotations import Arrow
from .shapes import LineTool


class ArrowTool(LineTool):
    name: ClassVar[str] = "arrow"
    label: ClassVar[str] = "Arrow"
    icon_name: ClassVar[str] = "mail-forward-symbolic"
    accelerator: ClassVar[str] = "a"
    tooltip: ClassVar[str] = "Point at something (A)"
    annotation_type: ClassVar[type] = Arrow
    create_label: ClassVar[str] = "Add Arrow"
