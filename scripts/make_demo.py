"""Generate demo HTML output from committed fixture data for the Sphinx docs.

Run from the repo root::

    python scripts/make_demo.py

Output is written to ``docs/source/_static/demo/``.  Commit the result so the docs
work without running this script again.

GEBCO bathymetry is read from the sibling ``cruiseplan`` repo if present.
Maps render without bathymetry if the file is not found.
"""

from pathlib import Path

from ctdcast.converters import build_profiles
from ctdcast.plotters import plots
from ctdcast.reports._index import report

REPO = Path(__file__).resolve().parent.parent
NC_DIR = REPO / "tests" / "fixtures" / "nc"
LADCP_DIR = REPO / "tests" / "fixtures" / "ladcp"
SECTIONS_YAML = REPO / "tests" / "fixtures" / "ctd_sections_demo.yaml"
PROFILES_NC = REPO / "tests" / "fixtures" / "profiles_demo.nc"
OUT_DIR = REPO / "docs" / "source" / "_static" / "demo"

GEBCO_NC = REPO.parent / "cruiseplan" / "data" / "bathymetry" / "GEBCO_2025.nc"

CRUISE_INFO = {
    "cruise_id": "odb26",
    "ship": "Odon de Buen",
}

if __name__ == "__main__":
    if GEBCO_NC.exists():
        plots.GEBCO_PATH = GEBCO_NC
        print(f"Using GEBCO bathymetry: {GEBCO_NC}")
    else:
        print(f"GEBCO not found at {GEBCO_NC} — maps will render without bathymetry")

    print(f"Building profiles.nc from {NC_DIR} ...")
    build_profiles(NC_DIR, PROFILES_NC, force=True)
    print(f"  -> {PROFILES_NC}")

    print(f"Generating demo report to {OUT_DIR} ...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report(
        NC_DIR,
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
        cruise_info=CRUISE_INFO,
    )
    print("Done.")
    print(f"  Open: {OUT_DIR / 'index.html'}")
