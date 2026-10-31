"""Guard docs/SPEC.md against drifting away from the code.

The spec is meant to be a living document, which only works if its
machine-checkable claims are actually checked. Twice now it has quietly fallen
out of step - listing kinds that did not exist, shortcuts that were never bound,
a module tree missing real files - and each time it was caught by hand.

Only unambiguous claims are asserted here. Modifier accelerators are left out on
purpose: the spec writes `Ctrl+-` where GTK says `<Control>minus`, and a
normaliser for that would produce false failures rather than catch real drift.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parent.parent / "docs" / "SPEC.md"
ROOT = SPEC.parent.parent


@pytest.fixture(scope="module")
def spec() -> str:
    return SPEC.read_text()


def test_spec_exists():
    assert SPEC.is_file(), "docs/SPEC.md is the living spec; it must exist"


def test_annotation_table_matches_the_registry(spec):
    """Section 4's 'built' rows must be exactly the registered kinds."""
    from ganot8.annotations import registered_kinds

    built, planned = set(), set()
    for line in spec.splitlines():
        match = re.match(r"\|\s*`(\w+)`\s*\|.*\|\s*(built|phase \d)\s*\|", line)
        if match:
            name = match.group(1).lower().replace("textlabel", "text")
            (built if match.group(2) == "built" else planned).add(name)

    actual = set(registered_kinds())
    assert built == actual, f"spec says built={sorted(built)}, registry has {sorted(actual)}"
    assert not (planned & actual), f"marked planned but registered: {sorted(planned & actual)}"


def test_tool_keys_match_the_accelerators(spec):
    """Section 8's tool key table must match what the app binds."""
    from ganot8.app import _TOOL_ACCELERATORS

    block = spec.split("**Tool keys:**")[1].split("**Planned")[0]
    documented = {tool: key.lower() for key, tool in re.findall(r"`(\w)` (\w+)", block)}
    assert documented == _TOOL_ACCELERATORS


def test_every_registered_tool_has_a_documented_key(spec):
    from ganot8.app import _TOOL_ACCELERATORS
    from ganot8.tools import registered_tools

    for tool in registered_tools():
        assert tool.name in _TOOL_ACCELERATORS, f"{tool.name} has no documented shortcut"
        assert tool.accelerator == _TOOL_ACCELERATORS[tool.name]


def test_module_tree_matches_the_filesystem(spec):
    """Files listed in section 3 must exist; those tagged with a phase must not."""
    tree = spec.split("```\nganot8/")[1].split("```")[0]
    search_dirs = ("src/ganot8", "src/ganot8/tools", "src/ganot8/imageio", "devtools", ".")

    wrong = []
    for line in tree.splitlines():
        match = re.search(r"([\w.-]+\.py)\s+#\s*(.*)$", line)
        if not match:
            continue
        name, comment = match.group(1), match.group(2).strip()
        found = next(
            (ROOT / d / name for d in search_dirs if (ROOT / d / name).is_file()), None
        )
        planned = comment.startswith("(phase")
        if planned and found is not None:
            wrong.append(f"{name} tagged '{comment}' but exists")
        elif not planned and found is None:
            wrong.append(f"{name} listed as present but missing")
    assert wrong == [], "; ".join(wrong)


def test_display_split_is_accurate(spec):
    """Section 11 must name exactly the modules that skip without a display.

    Getting this wrong is costly: those modules skip silently, so a CI run can
    be green while testing none of the widget code.
    """
    section = spec.split("## 11. Verification")[1]
    free_block = section.split("**Display-free")[1].split("**Needs a display")[0]
    needs_block = section.split("**Needs a display")[1].split("- **What the")[0]

    documented_free = set(re.findall(r"`(test_\w+)`", free_block))
    documented_needs = set(re.findall(r"`(test_\w+)`", needs_block))

    actual_needs, actual_free = set(), set()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        (actual_needs if _skips_without_display(path) else actual_free).add(path.stem)

    assert documented_needs == actual_needs, (
        f"spec says these need a display: {sorted(documented_needs)}, "
        f"but these do: {sorted(actual_needs)}"
    )
    assert documented_free == actual_free, (
        f"spec lists display-free: {sorted(documented_free)}, actual: {sorted(actual_free)}"
    )


def _skips_without_display(path: Path) -> bool:
    """True if the module calls pytest.skip(..., allow_module_level=True).

    Parsed rather than grepped: this very module mentions both `init_check` and
    the keyword in its own source, and a text search would misclassify it.
    """
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "skip":
            continue
        if any(keyword.arg == "allow_module_level" for keyword in node.keywords):
            return True
    return False


def test_open_issues_section_exists(spec):
    """Unresolved findings need somewhere to live, or they get lost."""
    assert "## 13. Open issues" in spec
