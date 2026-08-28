"""Print the sensor catalog and per-variable sensor links of a stage-1 cast file.

The eyeball tool for the stage-1 sensor catalog (branch proc/sensors-stage1 and the
aggregation/report phases that follow). Point it at any per-cast netCDF that carries the
catalog and it prints two tables: one row per physical device (model, serial, calibration
date, and drift Slope/Offset for frequency sensors), and one row per data variable showing
which device fills its role.

Usage:
    venv/bin/python scripts/inspect_sensor_catalog.py <cast_stage1.nc>

To inspect a raw cast without disturbing the real pipeline, convert it to a scratch dir
first (stage files are regenerable from raw):

    mkdir -p /tmp/insp/cnv && cp /path/to/mixsed2_004.cnv /tmp/insp/cnv/
    venv/bin/python -c "from pathlib import Path; from ctdcast.processors.stage1 import stage1; \
        stage1(Path('/tmp/insp/cnv'), Path('/tmp/insp/nc'), force=True)"
    venv/bin/python scripts/inspect_sensor_catalog.py /tmp/insp/nc/stage1/mixsed2_004_stage1.nc
"""

import sys
from pathlib import Path

import xarray as xr


def main(path: str) -> int:
    """Print the catalog and link tables for the cast file at *path*."""
    ds = xr.open_dataset(path, engine="netcdf4")
    print(f"FILE: {Path(path).name}\n")

    print("=== sensor catalog (one row per physical device) ===")
    catalog = sorted(str(v) for v in ds.variables if str(v).startswith("SENSOR_"))
    if not catalog:
        print("  (no SENSOR_* catalog — this file predates the stage-1 sensor catalog)")
    for name in catalog:
        a = ds[name].attrs
        model = a.get("sensor_model", "?")
        serial = a.get("sensor_serial_number", "?")
        cal = a.get("sensor_calibration_date", "?")
        slope = a.get("sensor_calibration_slope")
        drift = (
            f"  slope={slope} offset={a.get('sensor_calibration_offset')}"
            if slope is not None
            else ""
        )
        print(f"  {name:34} {model:18} SN {serial:12} cal {cal}{drift}")

    print("\n=== data variables → which sensor fills their role ===")
    linked = [v for v in ds.data_vars if "sensor" in ds[v].attrs]
    if not linked:
        print("  (no variable carries a sensor link)")
    for v in linked:
        a = ds[v].attrs
        # Mark variables whose linked sensor carries a non-identity drift correction.
        sattrs = ds[a["sensor"]].attrs if a["sensor"] in ds else {}
        drift = ""
        try:
            if (
                float(sattrs.get("sensor_calibration_slope", 1.0)) != 1.0
                or float(sattrs.get("sensor_calibration_offset", 0.0)) != 0.0
            ):
                drift = " [non-identity drift]"
        except (TypeError, ValueError):
            pass
        print(
            f"  {v:20} role={a['sensor_role']:16} "
            f"ch{a['sensor_channel']:<3} → {a['sensor']}{drift}"
        )
    ds.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
