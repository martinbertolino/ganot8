"""Annotation tools.

Importing this package registers the tools, in the order they appear in the
tool strip. See docs/SPEC.md section 10 for the phased plan.
"""

from .base import Tool, register, registered_tools
from .select import SelectTool
from .shapes import BoxTool, RectangleTool

__all__ = [
    "BoxTool",
    "RectangleTool",
    "SelectTool",
    "Tool",
    "register",
    "registered_tools",
]
