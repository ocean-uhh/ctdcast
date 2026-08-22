"""Integration tests: the compiled files actually carry the file-level metadata.

The unit tests in ``test_global_attrs.py`` exercise the composer in isolation;
these assert the wiring — that ``build_profiles`` and ``build_ladcp_profiles``
thread ``cruise_info`` through and the attributes land on disk, on real fixtures.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast.processors.ladcp import build_ladcp_profiles, convert_ladcp_cast
from ctdcast.processors.profiles import build_profiles

_NC = Path(__file__).resolve().parent / "fixtures" / "nc"
_LADCP = Path(__file__).resolve().parent / "fixtures" / "ladcp"

_CRUISE_INFO = {
    "cruise_id": "odb2026",
    "project": "AEI-DFG DS-MIXSED",
    "platform": "odb",
    "start_date": "2026-07-09",
    "end_date": "2026-07-31",
    "embargo": {"policy": "SDN:L08::MO"},
    "creator": {"name": "E F-W", "type": "person"},
    # One contributors list; roles scoped per product (C89 codes). The cruise PI
    # (roles: [PI]) is on both files; the LADCP processors are scoped to ladcp.
    "contributors": [
        {"name": "E F-W", "roles": ["PI"]},
        {"name": "Angel Ruiz-Angulo", "roles": {"ladcp": ["DI"]}},
        {"name": "Mara Navarro Buigues", "roles": {"ladcp": ["MC"]}},
    ],
}


def test_ctd_profiles_carries_acdd_metadata(tmp_path):
    out = tmp_path / "profiles.nc"
    build_profiles(_NC, out, force=True, cruise_info=_CRUISE_INFO)
    with xr.open_dataset(out, engine="netcdf4") as ds:
        assert ds.attrs["cruise"] == "odb2026"
        assert ds.attrs["Conventions"] == "CF-1.13, ACDD-1.3"
        assert ds.attrs["featureType"] == "profile"
        assert "date_created" in ds.attrs
        assert ds.attrs["project"] == "AEI-DFG DS-MIXSED"
        assert ds.attrs["platform_name"] == "Odón de Buen"
        # coverage brackets every station
        lat = ds["latitude"].values
        lat = lat[np.isfinite(lat)]
        assert ds.attrs["geospatial_lat_min"] <= lat.min()
        assert ds.attrs["geospatial_lat_max"] >= lat.max()
        assert ds.attrs["geospatial_vertical_units"] == "dbar"
        assert "time_coverage_start" in ds.attrs
        # embargo, not a bare CC-BY grant
        assert "Embargoed" in ds.attrs["license"]
        # expocode both as coordinate and global, and they agree
        assert str(ds["expocode"].values[0]) == "29OD20260709"
        assert ds.attrs["expocode"] == "29OD20260709"
        # CTD file does NOT credit the LADCP processors
        assert "Angel" not in ds.attrs.get("contributor_name", "")


def test_ladcp_profiles_carries_metadata_and_ladcp_only_people(tmp_path):
    for m in ("128", "129"):
        convert_ladcp_cast(
            _LADCP / f"{m}.mat", tmp_path / f"ladcp_{m}.nc", cast_num=int(m)
        )
    out = tmp_path / "ladcp_profiles.nc"
    build_ladcp_profiles(tmp_path, out, force=True, cruise_info=_CRUISE_INFO)
    with xr.open_dataset(out, engine="netcdf4") as ds:
        assert ds.attrs["Conventions"] == "CF-1.13, ACDD-1.3"
        # vertical axis is depth in metres, not pressure
        assert ds.attrs["geospatial_vertical_units"] == "m"
        assert str(ds["expocode"].values[0]) == "29OD20260709"
        # LADCP file credits its processors, after the cruise PI, with the C89
        # prefLabels for their scoped roles (DI, MC).
        names = ds.attrs["contributor_name"]
        assert "Angel Ruiz-Angulo" in names
        assert "Mara Navarro Buigues" in names
        roles = ds.attrs["contributor_role"].split("; ")
        assert roles[-2:] == [
            "Cruise dataset principal investigator",
            "Cruise data manager",
        ]


def test_no_cruise_info_still_builds_without_metadata(tmp_path):
    """A config without cruise_info must still compile — metadata is optional."""
    out = tmp_path / "profiles.nc"
    build_profiles(_NC, out, force=True)
    with xr.open_dataset(out, engine="netcdf4") as ds:
        assert "expocode" not in ds.variables
        assert "contributor_name" not in ds.attrs
        # derived + provenance still present
        assert "geospatial_lat_min" in ds.attrs
        assert ds.attrs["Conventions"] == "CF-1.13, ACDD-1.3"
