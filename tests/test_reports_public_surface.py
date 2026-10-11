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
"""

import re
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1] / "ctdcast"

#: An import line pulling a private ``reports`` submodule other than ``_vendored``.
_PRIVATE_IMPORT = re.compile(
    r"^\s*(?:from\s+ctdcast\.reports\._(?!vendored)"
    r"|import\s+ctdcast\.reports\._(?!vendored)"
    r"|from\s+ctdcast\.reports\s+import\s+_(?!vendored))"
)


def test_production_reaches_reports_only_through_its_public_surface():
    """No file under ctdcast/ (outside reports/) imports a private reports module."""
    offenders: list[str] = []
    for py in _PKG.rglob("*.py"):
        rel = py.relative_to(_PKG)
        if rel.parts[0] == "reports":
            continue  # internal cross-imports within reports/ are allowed
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if _PRIVATE_IMPORT.match(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "production code imports a private reports submodule (use the public name):\n"
        + "\n".join(offenders)
    )
