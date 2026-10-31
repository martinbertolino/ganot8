"""The Underline tool."""

from __future__ import annotations

from typing import ClassVar

from ..annotations import Underline
from .shapes import LineTool


class UnderlineTool(LineTool):
    name: ClassVar[str] = "underline"
    label: ClassVar[str] = "Underline"
    icon_name: ClassVar[str] = "format-text-underline-symbolic"
    accelerator: ClassVar[str] = "u"
    tooltip: ClassVar[str] = "Underline a line of text (U)"
    annotation_type: ClassVar[type] = Underline
    create_label: ClassVar[str] = "Add Underline"
    #: Underlines are always level; sloping ones are never intended.
    horizontal: ClassVar[bool] = True
