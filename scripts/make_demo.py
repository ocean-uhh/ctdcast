"""Generate demo HTML output from committed fixture data for the Sphinx docs.

Run from the repo root::

    python scripts/make_demo.py

Output is written to ``docs/source/_static/demo/``.  Commit the result so the docs
work without running this script again.

GEBCO bathymetry is read from the sibling ``cruiseplan`` repo if present.
Maps render without bathymetry if the file is not found.
"""

import sys
import tempfile
from pathlib import Path

# Allow ``python scripts/make_demo.py`` from the repo root without an editable
# install: put the repo root on sys.path ahead of this script's own directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import xarray as xr
import yaml

from ctdcast.config.report_config import ReportConfig
from ctdcast.identity import cast_id_from_name
from ctdcast.processors.profiles import build_profiles
from ctdcast.processors.qc import apply_gross_range, apply_spike_test
from ctdcast.processors.stage2 import apply_stage2
from ctdcast.processors.stage3 import (
    _build_preferred_composites,
    _stamp_preferred_sensors,
)
from ctdcast.processors.stage_layout import stage_path
from ctdcast.reports._index import report

REPO = Path(__file__).resolve().parent.parent
NC_DIR = REPO / "tests" / "fixtures" / "nc"
LADCP_DIR = REPO / "tests" / "fixtures" / "ladcp"
SECTIONS_YAML = REPO / "tests" / "fixtures" / "ctd_sections_demo.yaml"
PROFILES_NC = REPO / "tests" / "fixtures" / "profiles_demo.nc"
OUT_DIR = REPO / "docs" / "source" / "_static" / "demo"
CONFIG_DEMO = REPO / "config_demo.yaml"

GEBCO_NC = REPO.parent / "cruiseplan" / "data" / "bathymetry" / "GEBCO_2025.nc"


def _demo_processing() -> dict:
    """Read the ``processing`` block from ``config_demo.yaml`` (the single declaration)."""
    with CONFIG_DEMO.open() as f:
        return (yaml.safe_load(f) or {}).get("processing") or {}


CRUISE_INFO = {
    "cruise_id": "odb26",
    "ship": "Odon de Buen",
}


def _build_stage3(nc_dir: Path, root: Path, cruise_cfg: dict) -> None:
    """Process each fixture cast through stage 2 + stage 3 into ``root/stage3/``.

    Runs soak/deck flagging (stage 2) then two-tier gross-range and spike QC
    (stage 3), so the demo cast pages show the QC panel — flag counts, the
    thresholds table, and the distribution histograms — from a real ``_qc``.  Then
    applies the preferred-sensor stamp and builds the plain composites from
    ``cruise_cfg`` (``config_demo.yaml``'s ``processing`` block), so the demo shows
    ``ctd_temperature`` / ``ctd_salinity`` / ``conductivity`` beside the ``_1`` / ``_2``
    channels and the per-cast preferred choice.
    """
    for src in sorted(nc_dir.glob("*.nc")):
        with xr.open_dataset(src, engine="netcdf4") as ds:
            ds = ds.load()
        ds = apply_spike_test(apply_gross_range(apply_stage2(ds)))
        parsed = cast_id_from_name(src.stem)
        if parsed is not None:
            _stamp_preferred_sensors(ds, cruise_cfg, parsed[0])
            _build_preferred_composites(ds, cruise_cfg, parsed[0])
        out = stage_path(root, src.stem, 3)
        out.parent.mkdir(parents=True, exist_ok=True)
        ds.to_netcdf(out)


if __name__ == "__main__":
    if GEBCO_NC.exists():
        cfg = ReportConfig(gebco_path=GEBCO_NC)
        print(f"Using GEBCO bathymetry: {GEBCO_NC}")
    else:
        cfg = ReportConfig()
        print(f"GEBCO not found at {GEBCO_NC} — maps will render without bathymetry")

    processing = _demo_processing()

    with tempfile.TemporaryDirectory() as _tmp:
        stage_root = Path(_tmp) / "ctd"
        print(f"Processing fixtures through stage 2 + stage 3 into {stage_root} ...")
        _build_stage3(NC_DIR, stage_root, processing)

        print("Building profiles.nc from the stage-3 files ...")
        build_profiles(stage_root, PROFILES_NC, force=True, cruise_cfg=processing)
        print(f"  -> {PROFILES_NC}")

        print(f"Generating demo report to {OUT_DIR} ...")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        report(
            stage_root,
            OUT_DIR,
            profiles_path=PROFILES_NC,
            section_yaml=SECTIONS_YAML,
            ladcp_dir=LADCP_DIR,
            generate={
                "stations": True,
                "sections": True,
                "timeseries": True,
                "index": True,
                "map": True,
            },
            force=True,
            config=cfg,
            cruise_info=CRUISE_INFO,
        )
    print("Done.")
    print(f"  Open: {OUT_DIR / 'index.html'}")
