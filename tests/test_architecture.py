"""Structural invariants.

These guard the boundaries the package is organised around. They're cheap, and
they fail at the moment someone reaches across a seam rather than months later
when the reach has spread.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "nutrition_toolkit"


def _imported_modules(package_dir: pathlib.Path) -> set[str]:
    """Every module name imported anywhere under `package_dir`.

    Relative imports are resolved against the package's position under
    nutrition_toolkit, so `from ..labels import x` inside recipe_deformulation
    comes back as "nutrition_toolkit.labels".
    """
    found: set[str] = set()
    for path in package_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parts = path.relative_to(SRC).parts[:-1]  # package path of this module
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    found.add(node.module or "")
                else:
                    # level 1 == current package, 2 == parent, ...
                    base = ("nutrition_toolkit", *parts)[: len(parts) + 2 - node.level]
                    found.add(".".join((*base, node.module) if node.module else base))
    return found


def test_deformulation_does_not_import_labels():
    """The solver takes intervals, not labels.

    This is the seam that lets a second labelling regime -- or a non-label
    source of constraints entirely -- drop in without touching the solver.
    """
    imported = _imported_modules(SRC / "recipe_deformulation")

    assert not any("labels" in m for m in imported), (
        f"recipe_deformulation must not depend on labels; found {sorted(imported)}"
    )


def test_nutrients_is_the_base_layer():
    """nutrients/ is what everything else keys off, so it depends on nothing
    above it. If it ever needs a label or a solver, the dependency is upside
    down."""
    imported = _imported_modules(SRC / "nutrients")

    for forbidden in ("labels", "recipe_deformulation", "adapters"):
        assert not any(forbidden in m for m in imported), (
            f"nutrients must not depend on {forbidden}; found {sorted(imported)}"
        )


def test_labels_does_not_import_deformulation():
    """...and the dependency doesn't run the other way either."""
    imported = _imported_modules(SRC / "labels")

    assert not any("recipe_deformulation" in m for m in imported), (
        f"labels must not depend on recipe_deformulation; found {sorted(imported)}"
    )


# The packages that hold the nutrient maths. These must stay app-neutral so
# supporting another tracker is a new file in adapters/ and nothing else.
# `mcp/`, `cli.py` and the package root are composition layers: they exist to
# wire things together and may legitimately know a tracker exists.
CORE_PACKAGES = ("nutrients", "labels", "recipe_deformulation")


def _imports_naming(path: pathlib.Path, needle: str) -> bool:
    """Whether this module imports anything whose name mentions `needle`.

    Docstrings may name a tracker freely; imports are what create coupling.
    """
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names]
            if isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
            if any(needle in (n or "").lower() for n in names):
                return True
    return False


def test_core_packages_name_no_tracker():
    """The maths knows nothing about any nutrition app."""
    offenders = [
        str(path.relative_to(SRC))
        for package in CORE_PACKAGES
        for path in (SRC / package).rglob("*.py")
        if _imports_naming(path, "cronometer")
    ]

    assert not offenders, f"tracker named inside the core packages: {offenders}"


def test_only_adapters_import_the_vendor_client():
    """The third-party client is reachable through adapters/ and nowhere else.

    Composition layers may name Cronometer -- the MCP server has to, since it
    resolves food ids -- but they go through the adapter rather than importing
    the vendor SDK, so the conversion of ids and units happens in exactly one
    place and swapping the client is a one-file change.
    """
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "adapters" not in path.relative_to(SRC).parts
        and _imports_naming(path, "cronometer_api_mcp")
    ]

    assert not offenders, f"vendor client imported outside adapters/: {offenders}"
