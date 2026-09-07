"""Per-file identity and lineage: tracking_id, source_tracking_id, and cross-stage survival.

The writer-level tests are not gated. The stage 1 → 2 → 3 propagation test drives the real
pipeline and so is gated on ``seasenselib`` inline — it is the cheapest guard on the
three-package (ctdcast → caldip → oceanarray) design: if a future refactor rebuilds a Dataset
instead of mutating it, the sensor catalog and the lineage vanish and this fails here, in
ctdcast, rather than two packages downstream as a missing serial.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr
from conftest import FIXTURES_CNV


def _tiny_ds() -> xr.Dataset:
    """A minimal per-cast-shaped Dataset for writer-level tests."""
    return xr.Dataset(
        {"ctd_temperature_1": ("time", np.arange(3.0))},
        coords={"time": np.arange(3)},
    )


class TestTrackingIdAtWriter:
    """The writer stamps a fresh tracking_id and moves date_modified on every write."""

    def test_tracking_id_present_and_unique_per_write(self, tmp_path):
        """Two writes of the same Dataset get two different tracking_ids."""
        from ctdcast.writers.netcdf import write

        a, b = tmp_path / "a.nc", tmp_path / "b.nc"
        write(_tiny_ds(), a)
        write(_tiny_ds(), b)
        da = xr.open_dataset(a, engine="netcdf4")
        db = xr.open_dataset(b, engine="netcdf4")
        try:
            assert da.attrs["tracking_id"] and db.attrs["tracking_id"]
            assert da.attrs["tracking_id"] != db.attrs["tracking_id"]
        finally:
            da.close()
            db.close()

    def test_date_created_stable_date_modified_moves_on_rewrite(self, tmp_path):
        """Re-writing a loaded file preserves date_created but refreshes date_modified."""
        from ctdcast.writers.netcdf import write

        p = tmp_path / "c.nc"
        write(_tiny_ds(), p)
        first = xr.open_dataset(p, engine="netcdf4").load()
        created_1, modified_1 = (
            first.attrs["date_created"],
            first.attrs["date_modified"],
        )
        # Release the handle before rewriting the same path — Windows refuses to replace
        # an open file, and .load() has already read the data into memory.
        first.close()
        # Re-write the loaded dataset (a stage-3-style rewrite of an existing file).
        write(first, p)
        second = xr.open_dataset(p, engine="netcdf4")
        try:
            assert second.attrs["date_created"] == created_1  # set once, preserved
            assert second.attrs["date_modified"] >= modified_1  # moves (or ties)
        finally:
            second.close()


def test_stage1_to_stage3_carries_catalog_and_lineage(tmp_path):
    """stage 1 → 2 → 3 preserves the sensor catalog and identity, and chains tracking_ids."""
    pytest.importorskip("seasenselib")
    from ctdcast.processors import stage2, stage3
    from ctdcast.processors.stage1 import stage1
    from ctdcast.processors.stage_layout import group_by_cast

    root = tmp_path / "ctd"
    # One cruise: the fixture CNV dir also holds an MSM cast.
    assert stage1(FIXTURES_CNV, root, pattern="mixsed2_*.cnv") >= 1
    stage2.run(root)
    stage3.run(root)

    groups = group_by_cast(root)
    cast_id = sorted(groups)[0]
    s1, s2, s3 = groups[cast_id][1], groups[cast_id][2], groups[cast_id][3]

    a1 = xr.open_dataset(s1, engine="netcdf4")
    a2 = xr.open_dataset(s2, engine="netcdf4")
    a3 = xr.open_dataset(s3, engine="netcdf4")
    try:
        # lineage chain: each stage names the instance it was made from
        assert a1.attrs["source_cnv"].endswith(".cnv")
        assert a1.attrs["tracking_id"]
        assert a2.attrs["source_tracking_id"] == a1.attrs["tracking_id"]
        assert a3.attrs["source_tracking_id"] == a2.attrs["tracking_id"]
        # Each file records its own stage and cast identity in attributes (caldip reads a
        # file copied out of its directory, where the filename-borne stage and cast are lost).
        assert a1.attrs["processing_stage"] == 1
        assert a2.attrs["processing_stage"] == 2
        assert a3.attrs["processing_stage"] == 3
        assert a1.attrs["cast_id"] == a3.attrs["cast_id"]  # carries forward unchanged
        assert a1.attrs["cast_id"]  # a non-empty canonical cast id
        assert (
            len(
                {
                    a1.attrs["tracking_id"],
                    a2.attrs["tracking_id"],
                    a3.attrs["tracking_id"],
                }
            )
            == 3
        )

        # the sensor catalog survived to stage 3, with its key provenance attrs
        sensors = [
            v
            for v in a3.variables
            if str(v).startswith("SENSOR_") and not str(v).endswith("_qc")
        ]
        assert sensors, "sensor catalog did not survive to stage 3"
        freq = next(
            (v for v in sensors if "sensor_calibration_slope" in a3[v].attrs), None
        )
        assert freq is not None, (
            "no frequency sensor carried its calibration slope to stage 3"
        )
        for key in ("sensor_serial_number", "sensor_role", "sensor_calibration_date"):
            assert key in a3[freq].attrs
        # the upstream SBE header (source of the correction ledger) survived too
        assert a3.attrs.get("raw_metadata")
    finally:
        a1.close()
        a2.close()
        a3.close()
