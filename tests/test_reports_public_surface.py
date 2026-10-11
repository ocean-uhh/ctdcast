"""No production module outside ``reports/`` imports a private reports submodule.

A module under ``reports/`` is public (no leading underscore) iff something
outside ``reports/`` imports it; the page builders (``index``, ``cast``,
``section``, ``timeseries``, ``dataset``, ``cruise_map``, ``qc_tables``) and
``design`` are public, and private helpers (``_plots``, ``_navs``, ``_figdebug``,
``_sensors``, ``_anchors``, ``_format``, ``_env``) stay internal to the package.

This test guards that *production* code — ``ctdcast/`` outside ``reports/`` —
reaches ``reports/`` only through its public surface.  Two deliberate exemptions:
the vendored layer (``reports._vendored``) is the shared substrate, imported
widely by design; and tests may import private helpers (white-box), so only
``ctdcast/`` is scanned, not ``tests/``.

Imports are parsed with :mod:`ast`, not a line regex, so a multiline
``from ctdcast.reports import (\n    _private,\n)`` is caught too.
"""

import ast
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "ctdcast"


def _is_private_reports(module: str) -> bool:
    """Return whether *module* names a private ``reports`` submodule (not ``_vendored``)."""
    return module.startswith("ctdcast.reports._") and not module.startswith(
        "ctdcast.reports._vendored"
    )


def _private_reports_imports(tree: ast.AST) -> list[str]:
    """Return every private-``reports``-submodule import in *tree*."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if _is_private_reports(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if _is_private_reports(module):
                # from ctdcast.reports._x import ...
                hits.append(module)
            elif module == "ctdcast.reports":
                # from ctdcast.reports import _x (x not _vendored)
                hits += [
                    f"{module}.{a.name}"
                    for a in node.names
                    if a.name.startswith("_") and a.name != "_vendored"
                ]
    return hits


def test_production_reaches_reports_only_through_its_public_surface():
    """No file under ctdcast/ (outside reports/) imports a private reports module."""
    offenders: list[str] = []
    for py in _PKG.rglob("*.py"):
        rel = py.relative_to(_PKG)
        if rel.parts[0] == "reports":
            continue  # internal cross-imports within reports/ are allowed
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        offenders += [f"{rel}: {name}" for name in _private_reports_imports(tree)]
    assert not offenders, (
        "production code imports a private reports submodule (use the public name):\n"
        + "\n".join(offenders)
    )
