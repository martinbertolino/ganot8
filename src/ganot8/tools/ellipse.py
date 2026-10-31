"""The Ellipse tool."""

from __future__ import annotations

from typing import ClassVar

from ..annotations import Ellipse
from .shapes import RectangleTool


class EllipseTool(RectangleTool):
    name: ClassVar[str] = "ellipse"
    label: ClassVar[str] = "Ellipse"
    icon_name: ClassVar[str] = "ganot8-ellipse-symbolic"
    accelerator: ClassVar[str] = "e"
    tooltip: ClassVar[str] = "Draw an ellipse (E)"
    annotation_type: ClassVar[type] = Ellipse
    create_label: ClassVar[str] = "Add Ellipse"
