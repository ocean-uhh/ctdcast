"""Create test fixtures from real OdB2026 CTD and LADCP data.

Run once with the data drive mounted:

    venv/bin/python scripts/make_test_fixtures.py

Copies four full cast files and four LADCP .mat files verbatim into
tests/fixtures/.  No subsampling, no variable pruning.

Fixture selection
-----------------
Section — Kangerlussuaq Outer shelf (two casts on a transect with LADCP):
    mixsed2_011.nc  65.861 N  29.433 W   625 pts  ~192 KB
    mixsed2_012.nc  65.847 N  29.588 W   603 pts  ~188 KB

Timeseries — Triangle ~700 m isobath (genuine repeat station with LADCP):
    mixsed2_128.nc  65.586 N  29.480 W  1365 pts  ~319 KB
    mixsed2_129.nc  65.583 N  29.451 W  1429 pts  ~330 KB

LADCP .mat files (LDEO IXv14 processed):
    011.mat  012.mat  128.mat  129.mat

Total fixtures: ~1.1 MB CTD + ~0.1 MB LADCP = ~1.2 MB.
"""

from __future__ import annotations

import shutil
from pathlib import Path

_DRIVE = Path("/Volumes/T9ifmeo/odb2026")
_SRC_NC = _DRIVE / "CTD" / "cnv_nc"
_SRC_LADCP = _DRIVE / "LADCP" / "ladcp_test" / "data" / "processed"

_ROOT = Path(__file__).parent.parent
_DST_NC = _ROOT / "tests" / "fixtures" / "nc"
_DST_LADCP = _ROOT / "tests" / "fixtures" / "ladcp"

_STEM = "mixsed2"

_CTD_CASTS = [11, 12, 128, 129]
_LADCP_CASTS = [11, 12, 128, 129]


def main() -> None:
    """Copy fixture files verbatim from the data drive."""
    if not _SRC_NC.exists():
        raise SystemExit(f"Data drive not mounted or path wrong: {_SRC_NC}")

    _DST_NC.mkdir(parents=True, exist_ok=True)
    _DST_LADCP.mkdir(parents=True, exist_ok=True)

    print("=== CTD fixtures ===")
    for cn in _CTD_CASTS:
        src = _SRC_NC / f"{_STEM}_{cn:03d}.nc"
        dst = _DST_NC / f"{_STEM}_{cn:03d}.nc"
        if not src.exists():
            print(f"  MISSING: {src}")
            continue
        shutil.copy2(src, dst)
        kb = dst.stat().st_size // 1024
        print(f"  {src.name} → {dst.name} ({kb} KB)")

    print("\n=== LADCP fixtures ===")
    for cn in _LADCP_CASTS:
        src = _SRC_LADCP / f"{cn:03d}.mat"
        dst = _DST_LADCP / f"{cn:03d}.mat"
        if not src.exists():
            print(f"  MISSING: {src}")
            continue
        shutil.copy2(src, dst)
        kb = dst.stat().st_size // 1024
        print(f"  {src.name} → {dst.name} ({kb} KB)")

    print("\nDone. Now run:")
    print("  venv/bin/python scripts/build_profiles_fixture.py")


if __name__ == "__main__":
    main()
