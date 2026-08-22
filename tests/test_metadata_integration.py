"""Integration tests: the compiled files actually carry the file-level metadata.

The unit tests in ``test_global_attrs.py`` exercise the composer in isolation;
these assert the wiring — that ``build_profiles`` and ``build_ladcp_profiles``
thread ``cruise_info`` through and the attributes land on disk, on real fixtures.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ctdcast.processors.ladcp import build_ladcp_profiles, convert_ladcp_cast
from ctdcast.processors.profiles import build_profiles
from ctdcast.processors.stage_layout import stage_path

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


def _stage1_fixtures_with_cruise(root: Path, cruise_for) -> None:
    """Copy the real NC fixtures into a stage-1 layout, stamping a ``cruise`` attr.

    Not fabricated data: the arrays are the committed instrument fixtures; only
    the ``cruise`` global attribute — the one stage 1 writes from cruise_info — is
    set, so the strict identity aggregation (§4d) can be exercised at the builder
    level without re-running the seasenselib conversion.
    """
    for src in sorted(_NC.glob("*.nc")):
        with xr.open_dataset(src, engine="netcdf4") as ds:
            ds = ds.load()
        ds.attrs["cruise"] = cruise_for(src.stem)
        out = stage_path(root, src.stem, 1)
        out.parent.mkdir(parents=True, exist_ok=True)
        ds.to_netcdf(out, engine="netcdf4")


def test_ctd_profiles_lifts_identity_from_per_cast(tmp_path, recwarn):
    """When the per-cast files state ``cruise``, the builder lifts it — no fallback."""
    root = tmp_path / "CTD"
    _stage1_fixtures_with_cruise(root, lambda _stem: "odb2026")
    out = root / "profiles.nc"
    build_profiles(root, out, force=True, cruise_info=_CRUISE_INFO)
    with xr.open_dataset(out, engine="netcdf4") as ds:
        assert ds.attrs["cruise"] == "odb2026"
    # the per-cast files state cruise, so no "taking it from cruise_info" fallback
    msgs = [str(w.message) for w in recwarn]
    assert not any("no per-cast file states 'cruise'" in m for m in msgs)


def test_ctd_profiles_errors_when_casts_disagree_on_cruise(tmp_path):
    """Two cruises in one directory is a mistake, not a merge — build must error."""
    root = tmp_path / "CTD"
    stems = sorted(p.stem for p in _NC.glob("*.nc"))
    assert len(stems) >= 2, "need at least two fixtures to disagree"
    labels = {s: ("cruiseA" if i == 0 else "cruiseB") for i, s in enumerate(stems)}
    _stage1_fixtures_with_cruise(root, lambda stem: labels[stem])
    out = root / "profiles.nc"
    with pytest.raises(ValueError, match="disagree about 'cruise'"):
        build_profiles(root, out, force=True, cruise_info=_CRUISE_INFO)


def test_ctd_profiles_title_and_cruise_agree_when_config_is_stale(tmp_path):
    """A config edited after stage 1 must not split the file's own story.

    The per-cast files win — they record the cruise the cast was actually taken
    on — so the title has to be built from the lifted value too.  Building the
    title from config while `attrs.update(identity)` set `cruise` from the files
    produced a file titled for one cruise and attributed to another, behind a
    warning that announced the opposite resolution.
    """
    root = tmp_path / "CTD"
    _stage1_fixtures_with_cruise(root, lambda _stem: "onthefiles")
    out = root / "profiles.nc"
    with pytest.warns(UserWarning, match="using the files' value"):
        build_profiles(root, out, force=True, cruise_info=_CRUISE_INFO)
    with xr.open_dataset(out, engine="netcdf4") as ds:
        assert ds.attrs["cruise"] == "onthefiles"
        assert ds.attrs["title"].startswith("onthefiles")


def test_ctd_profiles_history_survives_the_global_attr_merge(tmp_path):
    """`history` is appended by every writer, so no layer may *return* one.

    `cruise_global_attrs` is merged with `.update()`; a `history` key in its
    result silently replaced whatever the builder had already recorded, making
    the merge order load-bearing.  Both the creation note and the compile note
    must survive.
    """
    root = tmp_path / "CTD"
    _stage1_fixtures_with_cruise(root, lambda _stem: "odb2026")
    out = root / "profiles.nc"
    build_profiles(root, out, force=True, cruise_info=_CRUISE_INFO)
    with xr.open_dataset(out, engine="netcdf4") as ds:
        history = ds.attrs["history"]
    assert "create: file created by ctdcast" in history
    assert "profiles: compiled" in history
    assert history.index("create:") < history.index("profiles:"), "creation first"
