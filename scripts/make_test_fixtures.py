"""Create test fixtures from real OdB2026 CTD and LADCP data.

Run once with the data drive mounted:

    venv/bin/python scripts/make_test_fixtures.py

Regenerates four per-cast CTD fixtures by running ctdcast's stage-1 conversion
over the calibrated CNV files, and copies four LADCP .mat files verbatim into
tests/fixtures/.  No subsampling, no variable pruning.

CTD source: cnv_cal
-------------------
The fixtures are built from ``CTD/cnv_cal`` — the bottle-calibrated CNV, which is
what ``config_odb.yaml`` feeds to stage 1 (``cnv_dir:``).  This is the calibrated
product: the conductivity cells carry their applied drift Slope, so the per-cast
sensor catalog stage 1 builds shows genuine non-identity calibration (the raw
``CTD/cnv`` files carry identity slopes and would not exercise it).  Running
stage 1 rather than copying a prebuilt file means the fixtures always match what
the current reader and normaliser write — including the ``SENSOR_*`` catalog.

Fixture selection
-----------------
Section — Kangerlussuaq Outer shelf (two casts on a transect with LADCP):
    mixsed2_011.nc  65.861 N  29.433 W   625 pts
    mixsed2_012.nc  65.847 N  29.588 W   603 pts

Timeseries — Triangle ~700 m isobath (genuine repeat station with LADCP):
    mixsed2_128.nc  65.586 N  29.480 W  1365 pts
    mixsed2_129.nc  65.583 N  29.451 W  1429 pts

LADCP .mat files (LDEO IXv14 processed):
    011.mat  012.mat  128.mat  129.mat
"""

from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

# Run from anywhere: put the repo root on the path before importing ctdcast.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ctdcast.processors.stage1 import get_ctd_backend

_DRIVE = Path("/Volumes/T9ifmeo/odb2026")
# Calibrated CNV — the stage-1 input named by config_odb.yaml's cnv_dir.
_SRC_CNV = _DRIVE / "CTD" / "cnv_cal"
_SRC_LADCP = _DRIVE / "LADCP" / "ladcp_test" / "data" / "processed"

_ROOT = Path(__file__).parent.parent
_DST_NC = _ROOT / "tests" / "fixtures" / "nc"
_DST_LADCP = _ROOT / "tests" / "fixtures" / "ladcp"

_STEM = "mixsed2"

_CTD_CASTS = [11, 12, 128, 129]
_LADCP_CASTS = [11, 12, 128, 129]


def main() -> None:
    """Regenerate the CTD fixtures via stage 1 and copy the LADCP fixtures verbatim."""
    if not _SRC_CNV.exists():
        raise SystemExit(f"Data drive not mounted or path wrong: {_SRC_CNV}")

    _DST_NC.mkdir(parents=True, exist_ok=True)
    _DST_LADCP.mkdir(parents=True, exist_ok=True)

    # cruise_info=None and no sensor overrides: the fixtures are deliberately
    # identity-free so tests control cruise/platform metadata themselves, and the
    # OdB config carries no sensors: block (empty overrides is the faithful run).
    backend = get_ctd_backend("seasenselib")
    print("=== CTD fixtures (stage 1 over cnv_cal) ===")
    for cn in _CTD_CASTS:
        src = _SRC_CNV / f"{_STEM}_{cn:03d}.cnv"
        dst = _DST_NC / f"{_STEM}_{cn:03d}.nc"
        if not src.exists():
            print(f"  MISSING: {src}")
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            backend.convert_cast(
                src, dst, force=True, cruise_info=None, sensor_overrides=None
            )
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
