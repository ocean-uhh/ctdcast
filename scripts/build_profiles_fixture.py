"""Build tests/fixtures/profiles.nc from the subsampled fixture cast files.

Run after make_test_fixtures.py:

    venv/bin/python scripts/build_profiles_fixture.py
"""

from __future__ import annotations

from pathlib import Path

from ctd_report._converters import build_profiles

_ROOT = Path(__file__).parent.parent
_NC_DIR = _ROOT / "tests" / "fixtures" / "nc"
_PROFILES_PATH = _ROOT / "tests" / "fixtures" / "profiles.nc"


def main() -> None:
    """Build profiles.nc from fixture cast files."""
    if not _NC_DIR.exists() or not list(_NC_DIR.glob("*.nc")):
        raise SystemExit("Run make_test_fixtures.py first.")

    written = build_profiles(_NC_DIR, _PROFILES_PATH, force=True)
    if written:
        kb = _PROFILES_PATH.stat().st_size // 1024
        print(f"Written: {_PROFILES_PATH} ({kb} KB)")
    else:
        print("Skipped (already exists and force=False).")


if __name__ == "__main__":
    main()
