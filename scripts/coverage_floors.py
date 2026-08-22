#!/usr/bin/env python3
"""Assert per-module coverage floors declared in ``pyproject.toml``.

``coverage.py`` and ``pytest-cov`` only offer a *global* ``fail_under``, which a
new module can hide under: three files landing at 40% barely move an aggregate.
This checker adds per-module floors for the modules worth guarding individually.

Deliberately no ``default`` key: the aggregate is guarded by
``--cov-fail-under`` in CI, and duplicating that number here would be the same
fact in two files, free to drift.

Usage
-----
::

    coverage json -o coverage.json
    python scripts/coverage_floors.py [--coverage coverage.json]

Floors are seeded at each module's measured coverage, rounded down, so a module
can hold or rise but never regress.  When you improve one, bump its number --
that maintenance is the cost of per-module guarding, which is why the list stays
short rather than pinning every module.

Exit status
-----------
0
    Every listed module meets its floor.
1
    A module is below its floor, is missing from the coverage report, or the
    configuration could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        print(
            "ERROR: need Python 3.11+ (tomllib) or `pip install tomli` to read "
            "pyproject.toml",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

#: A module this far above its floor is worth ratcheting up; reported, never failed.
BUMP_SUGGESTION_MARGIN = 2.0


def load_floors(pyproject: Path) -> dict[str, float]:
    """Read the ``[tool.coverage_floors]`` table.

    Parameters
    ----------
    pyproject : Path
        Path to ``pyproject.toml``.

    Returns
    -------
    dict of str to float
        Module path (as written in the table) to its minimum percentage.
    """
    with open(pyproject, "rb") as fh:
        data = tomllib.load(fh)
    floors = data.get("tool", {}).get("coverage_floors", {})
    return {str(k): float(v) for k, v in floors.items() if k != "default"}


def measured(coverage_json: Path) -> dict[str, float]:
    """Read per-file coverage percentages from a ``coverage json`` report.

    Parameters
    ----------
    coverage_json : Path
        Path to the JSON report.

    Returns
    -------
    dict of str to float
        File path to percentage covered, keyed as coverage.py recorded it.
    """
    with open(coverage_json) as fh:
        data = json.load(fh)
    return {
        path: float(info["summary"]["percent_covered"])
        for path, info in data.get("files", {}).items()
    }


def _match(module: str, seen: dict[str, float]) -> float | None:
    """Return the measured percentage for *module*, tolerating path prefixes.

    coverage.py may record absolute or relative paths depending on how it was
    invoked, so fall back to a suffix match rather than failing on a path shape.
    """
    if module in seen:
        return seen[module]
    target = Path(module).as_posix()
    hits = [v for k, v in seen.items() if Path(k).as_posix().endswith(target)]
    return hits[0] if len(hits) == 1 else None


def main(argv: list[str] | None = None) -> int:
    """Compare measured coverage against the declared floors."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage", type=Path, default=Path("coverage.json"))
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)

    for path in (args.coverage, args.pyproject):
        if not path.exists():
            print(f"ERROR: {path} not found", file=sys.stderr)
            return 1

    floors = load_floors(args.pyproject)
    if not floors:
        print("ERROR: [tool.coverage_floors] is empty or absent", file=sys.stderr)
        return 1

    seen = measured(args.coverage)
    failures: list[str] = []
    bumps: list[str] = []

    width = max(len(m) for m in floors)
    print("Per-module coverage floors")
    for module in sorted(floors):
        floor = floors[module]
        pct = _match(module, seen)
        if pct is None:
            # A module that vanished from the report is not passing -- it is
            # unguarded.  Renaming or deleting a file must be a deliberate edit
            # here, not a silent loss of its floor.
            failures.append(
                f"{module}: not in the coverage report. If it was renamed or "
                f"removed, update [tool.coverage_floors]; if it is simply never "
                f"imported by the suite, that is the finding."
            )
            print(f"  {module:<{width}}  MISSING  (floor {floor:.0f})")
            continue
        ok = pct >= floor - 1e-9
        print(
            f"  {module:<{width}}  {pct:6.2f}%  floor {floor:>3.0f}  {'ok' if ok else 'FAIL'}"
        )
        if not ok:
            failures.append(f"{module}: {pct:.2f}% is below its floor of {floor:.0f}%")
        elif pct >= floor + BUMP_SUGGESTION_MARGIN:
            bumps.append(f"{module}: {pct:.2f}% — floor could rise to {int(pct)}")

    if bumps:
        print("\nRatchet candidates (informational, not failures):")
        for line in bumps:
            print(f"  {line}")

    if failures:
        print("\nFAILED:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1

    print("\nAll module floors met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
