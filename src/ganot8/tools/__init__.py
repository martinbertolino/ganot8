"""Annotation tools.

Import order here is the order of the tool strip, so Select comes first and
the creation tools follow in the order they are listed in docs/SPEC.md.
"""

from .base import Tool, register, registered_tools
from .select import SelectTool
from .highlight import HighlightTool
from .redact import RedactTool
from .underline import UnderlineTool
from .arrow import ArrowTool
from .text import TextTool
from .shapes import BoxTool, LineTool, RectangleTool
from .ellipse import EllipseTool
from .freehand import FreehandTool
from .badge import BadgeTool

# Registration order drives the tool strip; Select is registered by its own
# decorator, the rest are listed explicitly so the order is visible here.
for _tool in (
    HighlightTool,
    RedactTool,
    UnderlineTool,
    ArrowTool,
    TextTool,
    BoxTool,
    EllipseTool,
    FreehandTool,
    BadgeTool,
):
    register(_tool)
del _tool

__all__ = [
    "ArrowTool",
    "BadgeTool",
    "BoxTool",
    "EllipseTool",
    "FreehandTool",
    "HighlightTool",
    "LineTool",
    "RectangleTool",
    "RedactTool",
    "SelectTool",
    "TextTool",
    "Tool",
    "UnderlineTool",
    "register",
    "registered_tools",
]
