"""Tests for the stage-2 clock applier (``apply_clock_offset`` / ``_resolve_clock_application``).

The applier is arithmetic over a time coordinate — no instrument measurement is fabricated — so
casts are built synthetically. Each carries the ``raw_metadata`` header the finder re-measures from
and the ``time_coordinate_source`` attribute the gate reads.
"""

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.processors import stage2
from ctdcast.processors.stage2 import _resolve_clock_application, apply_clock_offset


def _cast_ds(
    system: dt.datetime,
    *,
    source: str = "System UTC, first data scan.",
    n: int = 6,
) -> xr.Dataset:
    """A minimal per-cast dataset with a time coordinate, pressure, temperature and the gate attr."""
    t0 = np.datetime64(system.strftime("%Y-%m-%dT%H:%M:%S"))
    time = t0 + np.arange(n) * np.timedelta64(1, "s")
    return xr.Dataset(
        {
            "temperature": ("time", np.linspace(10.0, 4.0, n)),
            "pressure": ("time", np.linspace(0.0, 100.0, n)),
        },
        coords={"time": ("time", time)},
        attrs={
            "time_coordinate_source": source,
            "time_coverage_start": str(np.datetime_as_string(time.min(), unit="s")),
            "time_coverage_end": str(np.datetime_as_string(time.max(), unit="s")),
            "raw_metadata": "unused-by-apply",
        },
    )


class TestApplyClockOffset:
    def test_shifts_time_and_preserves_original(self) -> None:
        """time moves by the offset; time_orig keeps the uncorrected values; coverage recomputes."""
        ds = _cast_ds(dt.datetime(2026, 3, 29, 20, 23, 55))
        out = apply_clock_offset(ds, 5.0, n_casts=3, segment_sd=0.47)
        assert (out["time"].values - ds["time"].values == np.timedelta64(5, "s")).all()
        assert (out["time_orig"].values == ds["time"].values).all()
        assert out.attrs["time_coverage_start"] == str(
            np.datetime_as_string(out["time"].values.min(), unit="s")
        )

    def test_records_value_with_n_and_sd(self) -> None:
        """clock_offset_seconds carries the value and its segment n/sd, per the plan."""
        out = apply_clock_offset(
            _cast_ds(dt.datetime(2026, 3, 29, 20, 0, 0)),
            -2.07,
            n_casts=150,
            segment_sd=0.69,
        )
        assert float(out["clock_offset_seconds"]) == pytest.approx(-2.07)
        comment = out["clock_offset_seconds"].attrs["comment"]
        assert "150 casts" in comment and "sd 0.69" in comment
        assert "clock_offset_seconds=-2.07 applied" in str(out.attrs["history"])

    def test_no_measured_value_changes(self) -> None:
        """A clock correction moves only the time axis — temperature/pressure are untouched."""
        ds = _cast_ds(dt.datetime(2026, 3, 29, 20, 0, 0))
        out = apply_clock_offset(ds, 7.0, n_casts=29, segment_sd=0.57)
        assert (out["temperature"].values == ds["temperature"].values).all()
        assert (out["pressure"].values == ds["pressure"].values).all()

    def test_gate_refuses_a_gps_coordinate(self) -> None:
        """A coordinate already on GPS must not be shifted — refuse loudly."""
        ds = _cast_ds(dt.datetime(2026, 3, 29, 20, 0, 0), source="NMEA time, header")
        with pytest.raises(ValueError, match="already on GPS"):
            apply_clock_offset(ds, 5.0, n_casts=3, segment_sd=0.5)

    def test_gate_refuses_an_unclassifiable_source(self) -> None:
        """A missing/unknown time_coordinate_source is refused, not assumed to be System."""
        ds = _cast_ds(
            dt.datetime(2026, 3, 29, 20, 0, 0), source=""
        )  # e.g. a legacy file
        with pytest.raises(ValueError, match="cannot verify"):
            apply_clock_offset(ds, 5.0, n_casts=3, segment_sd=0.5)

    def test_records_partial_evidence_not_dropped(self) -> None:
        """When config supplies n_casts but no sd, the count is still recorded (not discarded)."""
        out = apply_clock_offset(
            _cast_ds(dt.datetime(2026, 3, 29, 20, 0, 0)), 5.0, n_casts=12
        )
        comment = out["clock_offset_seconds"].attrs["comment"]
        assert "12 casts" in comment
        assert "sd" not in comment  # no sd supplied, so none fabricated

    def test_guard_refuses_already_corrected(self) -> None:
        """A file already carrying time_orig is refused, not shifted a second time."""
        ds = _cast_ds(dt.datetime(2026, 3, 29, 20, 0, 0))
        ds = ds.assign_coords(time_orig=ds["time"])
        with pytest.raises(ValueError, match="time_orig"):
            apply_clock_offset(ds, 5.0, n_casts=3, segment_sd=0.5)

    def test_no_evidence_records_no_statistics(self) -> None:
        """Without config-supplied n/sd, no 'sd 0.00' is fabricated — the number claims no precision."""
        out = apply_clock_offset(_cast_ds(dt.datetime(2026, 3, 29, 20, 0, 0)), 5.0)
        comment = out["clock_offset_seconds"].attrs["comment"]
        assert "segment mean" not in comment and "sd" not in comment
        assert "convention" in comment  # the sign convention is still recorded
        assert "segment mean" not in str(out.attrs["history"])

    def test_acquisition_provenance_attrs_are_untouched(self) -> None:
        """The record of the acquisition clock must keep reading (wrongly) as acquired — never rewritten."""
        ds = _cast_ds(dt.datetime(2026, 3, 29, 20, 23, 55))
        ds.attrs["cnv_upload_date"] = "Mar 29 2026 20:23:55"
        ds.attrs["time_clock_offset_seconds"] = 5.0  # the offset *measured* at stage 1
        out = apply_clock_offset(ds, 7.0, n_casts=3, segment_sd=0.5)
        for key in (
            "raw_metadata",
            "cnv_upload_date",
            "time_clock_offset_seconds",
            "time_coordinate_source",
        ):
            assert out.attrs[key] == ds.attrs[key]


def _write_stage1_cast(
    stage1, cast_num: int, system: dt.datetime, offset_s: int
) -> None:
    """Write a stage-1 cast with header clocks (for the finder) and a time axis (for the applier)."""
    nmea = system + dt.timedelta(seconds=offset_s)
    header = (
        f"* System UTC = {system:%b %d %Y %H:%M:%S}\n"
        f"* NMEA UTC (Time) = {nmea:%b %d %Y %H:%M:%S}\n"
        f"# start_time = {system:%b %d %Y %H:%M:%S} [System UTC, first data scan.]"
    )
    ds = _cast_ds(system)
    ds.attrs["raw_metadata"] = json.dumps(
        {"schema": "test", "raw_format": "sbe-cnv", "blocks": {"header": header}}
    )
    ds.to_netcdf(stage1 / f"cast_{cast_num:03d}_stage1.nc", engine="netcdf4")


def _cruise(tmp_path, offset_s: int = 5, n_casts: int = 12):
    stage1 = tmp_path / "stage1"
    stage1.mkdir(parents=True)
    base = dt.datetime(2026, 3, 29, 20, 0, 0)
    for i in range(1, n_casts + 1):
        _write_stage1_cast(stage1, i, base + dt.timedelta(hours=i), offset_s)
    return tmp_path


class TestResolveClockApplication:
    def test_builds_lookup_with_config_supplied_evidence(self, tmp_path) -> None:
        """Each cast maps to the config offset and the config's n/sd — the evidence for that number."""
        root = _cruise(tmp_path, offset_s=5)
        lookup = _resolve_clock_application(
            root,
            {
                "segments": [
                    {
                        "casts": [[1, 12]],
                        "clock_offset_seconds": 5.0,
                        "n_casts": 12,
                        "clock_offset_sd_seconds": 0.4,
                    }
                ]
            },
        )
        assert lookup[1] == (5.0, 12, 0.4)
        assert lookup[7] == (5.0, 12, 0.4)  # every cast in range present

    def test_missing_evidence_stays_none_not_fabricated(self, tmp_path) -> None:
        """A hand-written segment with no n/sd yields None — never a fabricated zero."""
        root = _cruise(tmp_path, offset_s=5)
        lookup = _resolve_clock_application(
            root, {"segments": [{"casts": [[1, 12]], "clock_offset_seconds": 5.0}]}
        )
        assert lookup[1] == (5.0, None, None)

    def test_warns_when_config_disagrees_with_measured(self, tmp_path) -> None:
        """A configured offset far from the measured mean warns (config still wins)."""
        root = _cruise(tmp_path, offset_s=5)  # measured +5
        with pytest.warns(UserWarning, match="stale or"):
            lookup = _resolve_clock_application(
                root, {"segments": [{"casts": [[1, 12]], "clock_offset_seconds": 9.0}]}
            )
        assert lookup[1][0] == 9.0  # applied value is the configured one

    def test_no_clock_config_is_empty(self, tmp_path) -> None:
        """No processing.clock means nothing to apply (and no re-measure is triggered)."""
        root = _cruise(tmp_path)
        assert _resolve_clock_application(root, None) == {}
        assert _resolve_clock_application(root, {}) == {}
        assert _resolve_clock_application(root, {"segments": []}) == {}


class TestRunIntegration:
    def test_run_applies_offset_and_is_idempotent(self, tmp_path) -> None:
        """Stage 2 shifts time by the configured offset; a --force re-run gives the same result."""
        root = _cruise(tmp_path, offset_s=5)
        cfg = {
            "clock": {"segments": [{"casts": [[1, 12]], "clock_offset_seconds": 5.0}]}
        }
        assert stage2.run(root, cruise_cfg=cfg, force=True) == 12

        out = xr.open_dataset(root / "stage2" / "cast_001_stage2.nc", engine="netcdf4")
        try:
            shift = out["time"].values - out["time_orig"].values
            assert (shift == np.timedelta64(5, "s")).all()
            first_time = out["time"].values.copy()
        finally:
            out.close()

        # Re-run from the (frozen) stage-1 input: same shift, not a doubled one.
        stage2.run(root, cruise_cfg=cfg, force=True)
        out2 = xr.open_dataset(root / "stage2" / "cast_001_stage2.nc", engine="netcdf4")
        try:
            assert (out2["time"].values == first_time).all()
        finally:
            out2.close()

    def test_changed_offset_produces_the_new_value(self, tmp_path) -> None:
        """Re-running with a changed offset applies the new value, not the old one."""
        root = _cruise(tmp_path, offset_s=5)
        stage2.run(
            root,
            cruise_cfg={
                "clock": {
                    "segments": [{"casts": [[1, 12]], "clock_offset_seconds": 5.0}]
                }
            },
            force=True,
        )
        stage2.run(
            root,
            cruise_cfg={
                "clock": {
                    "segments": [{"casts": [[1, 12]], "clock_offset_seconds": 7.0}]
                }
            },
            force=True,
        )
        out = xr.open_dataset(root / "stage2" / "cast_001_stage2.nc", engine="netcdf4")
        try:
            assert (
                out["time"].values - out["time_orig"].values == np.timedelta64(7, "s")
            ).all()
        finally:
            out.close()

    def test_cast_outside_any_segment_is_not_shifted(self, tmp_path) -> None:
        """A cast in no segment gets no correction and no time_orig."""
        root = _cruise(tmp_path, offset_s=5)
        cfg = {
            "clock": {"segments": [{"casts": [[1, 3]], "clock_offset_seconds": 5.0}]}
        }
        stage2.run(root, cruise_cfg=cfg, force=True)
        out = xr.open_dataset(root / "stage2" / "cast_005_stage2.nc", engine="netcdf4")
        try:
            assert "time_orig" not in out.coords  # untouched
        finally:
            out.close()


class TestDownstreamSeams:
    """The seams a component test misses: the config that reaches stage 2, and the file profiles reads."""

    def test_process_verb_threads_clock_config_to_stage2(self, tmp_path) -> None:
        """process(stage=2, cruise_cfg=...) reaches the applier — the wiring cli/run and cli/process rely on."""
        from ctdcast.processors import process

        root = _cruise(tmp_path, offset_s=5)
        process(
            stage=2,
            ctd_root=root,
            cruise_cfg={
                "clock": {
                    "segments": [{"casts": [[1, 12]], "clock_offset_seconds": 5.0}]
                }
            },
            force=True,
        )
        out = xr.open_dataset(root / "stage2" / "cast_001_stage2.nc", engine="netcdf4")
        try:
            assert (
                "time_orig" in out.coords
            )  # applied via the public pipeline, not just stage2.run
        finally:
            out.close()

    def test_profiles_compiles_when_a_cast_carries_the_clock_scalar(
        self, tmp_path
    ) -> None:
        """build_profiles must tolerate the clock applier's scalar var, not grid it (it has no profile dim)."""
        from ctdcast.processors.profiles import build_profiles

        nc_dir = tmp_path / "nc"
        nc_dir.mkdir()
        for i, src in enumerate(sorted(Path(FIXTURES_NC).glob("*.nc"))):
            ds = xr.open_dataset(src, engine="netcdf4").load()
            if (
                i == 0
            ):  # one clock-corrected cast is enough to trip the scalar-gridding bug
                ds["clock_offset_seconds"] = 5.0
            ds.to_netcdf(nc_dir / src.name, engine="netcdf4")
            ds.close()

        out = tmp_path / "profiles.nc"
        build_profiles(
            nc_dir, out, force=True
        )  # would IndexError on the 0-d scalar before the fix
        assert out.exists()
        prof = xr.open_dataset(out, engine="netcdf4")
        try:
            assert "clock_offset_seconds" not in prof.data_vars  # skipped, not gridded
        finally:
            prof.close()
