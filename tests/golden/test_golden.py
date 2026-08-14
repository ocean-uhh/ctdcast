"""Local golden-image gate for the report-primitives refactor.

The primitives refactor is meant to change **no pixels**: it moves figure-drawing
into ``ax``-taking primitives without altering output.  The rest of the suite checks
PNG *validity and geometry*, not pixels, so it cannot catch a spine/colorbar/colour
drift.  This gate can: it renders every panel of the full report from the fixture
casts, hashes each embedded PNG, and compares against a baseline.

matplotlib PNG bytes are **not** reproducible across platforms (font backends differ
between macOS/Linux/Windows), so this is a *local before/after gate*, not a CI test:

    # on pre-refactor main (or the tip before you start), snapshot the baseline:
    GOLDEN_WRITE=1 venv/bin/python -m pytest tests/golden/ -q

    # after the refactor, on the SAME machine, confirm nothing moved:
    venv/bin/python -m pytest tests/golden/ -q

``baseline.json`` is machine-specific and git-ignored; when it is absent the test
skips, so CI and other checkouts are unaffected.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from ctdcast.processors.profiles import build_profiles
from ctdcast.reports._index import report

_HERE = Path(__file__).resolve().parent
_FIXTURES = _HERE.parent / "fixtures"
_NC = _FIXTURES / "nc"
_LADCP = _FIXTURES / "ladcp"
_BASELINE = _HERE / "baseline.json"

_SECTION_YAML = """\
sections:
  KO:
    description: Kangerlussuaq Outer (fixture)
    cast_numbers: [[11, 12]]
    color: "#1f77b4"

timeseries:
  Triangle:
    description: Triangle repeat station (fixture)
    cast_numbers: [[128, 129]]
    color: "#d62728"
"""

_PNG_RE = re.compile(r"data:image/png;base64,([A-Za-z0-9+/=]+)")


def _render_full_report(out_dir: Path) -> None:
    """Generate every page type from the fixture casts into *out_dir*."""
    yaml_path = out_dir / "ctd_sections.yaml"
    yaml_path.write_text(_SECTION_YAML, encoding="utf-8")
    profiles = out_dir / "profiles.nc"
    build_profiles(_NC, profiles, force=True)
    report(
        _NC,
        out_dir,
        profiles_path=profiles,
        section_yaml=yaml_path,
        ladcp_dir=_LADCP,
        force=True,
    )


def _png_manifest(html_root: Path) -> dict[str, str]:
    """Map ``<page>.html#<n>`` to the sha256 of each embedded PNG, in document order."""
    manifest: dict[str, str] = {}
    for html in sorted(html_root.rglob("*.html")):
        rel = html.relative_to(html_root).as_posix()
        text = html.read_text(encoding="utf-8")
        for i, b64 in enumerate(_PNG_RE.findall(text)):
            raw = base64.b64decode(b64)
            manifest[f"{rel}#{i}"] = hashlib.sha256(raw).hexdigest()
    return manifest


@pytest.mark.slow
def test_panel_pngs_match_baseline(tmp_path: Path) -> None:
    """Every embedded panel PNG is byte-identical to the committed-locally baseline."""
    write = bool(os.environ.get("GOLDEN_WRITE"))
    # Skip *before* the expensive full-report render when there is nothing to compare
    # against and we are not writing a baseline (the usual case in CI / fresh checkouts).
    if not write and not _BASELINE.exists():
        pytest.skip(
            "no tests/golden/baseline.json — snapshot it first with "
            "GOLDEN_WRITE=1 pytest tests/golden/ (on the pre-refactor tree)"
        )

    _render_full_report(tmp_path)
    current = _png_manifest(tmp_path)
    assert current, "no PNGs found in the generated report"

    if write:
        _BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True))
        pytest.skip(f"wrote baseline: {len(current)} panel PNGs")

    baseline = json.loads(_BASELINE.read_text())
    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    changed = sorted(
        k for k in current.keys() & baseline.keys() if current[k] != baseline[k]
    )
    assert not (added or removed or changed), (
        f"panel PNGs drifted from baseline: "
        f"{len(changed)} changed, {len(added)} added, {len(removed)} removed. "
        f"changed={changed[:12]} added={added[:6]} removed={removed[:6]}"
    )
