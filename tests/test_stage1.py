"""Tests for ctdcast.processors.stage1 (stage1(), get_ctd_backend())."""

import pytest
import xarray as xr
from conftest import FIXTURES_CNV

from ctdcast.processors.stage_layout import parse_stage, stage_dir

pytest.importorskip("seasenselib")


class TestGetCtdBackend:
    """get_ctd_backend() returns the right backend or raises."""

    def test_seasenselib_returns_backend(self):
        """get_ctd_backend('seasenselib') must not raise."""
        from ctdcast.processors.stage1 import get_ctd_backend

        b = get_ctd_backend("seasenselib")
        assert b is not None

    def test_unknown_backend_raises_valueerror(self):
        """An unrecognised backend name must raise ValueError."""
        from ctdcast.processors.stage1 import get_ctd_backend

        with pytest.raises(ValueError, match="Unknown CTD backend"):
            get_ctd_backend("nonexistent_backend")

    def test_backend_has_convert_cast(self):
        """Backend object must implement the convert_cast protocol method."""
        from ctdcast.processors.stage1 import get_ctd_backend

        b = get_ctd_backend("seasenselib")
        assert callable(getattr(b, "convert_cast", None))


class TestStage1:
    """stage1() converts a directory of CNV files to per-cast netCDF."""

    def test_converts_cnv_dir(self, tmp_path):
        """All CNV files in the fixture directory must produce NC files."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        n = stage1(FIXTURES_CNV, nc_dir)
        assert n == len(list(FIXTURES_CNV.glob("*.cnv")))
        assert len(list(stage_dir(nc_dir, 1).glob("*.nc"))) == n

    def test_nc_files_readable(self, tmp_path):
        """Each produced NC file must be openable as an xr.Dataset."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        stage1(FIXTURES_CNV, nc_dir)
        produced = sorted(stage_dir(nc_dir, 1).glob("*.nc"))
        assert produced, "stage 1 produced no files under stage1/"
        for nc_path in produced:
            ds = xr.open_dataset(nc_path, engine="netcdf4")
            assert ds.sizes["time"] > 0
            ds.close()

    def test_conductivity_converted_to_mscm(self, tmp_path):
        """Stage-1 conductivity is in mS/cm (the reader emits it; stage1 guards against double-converting a file already in those units)."""
        import numpy as np

        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        stage1(FIXTURES_CNV, nc_dir)
        checked = 0
        for nc_path in sorted(stage_dir(nc_dir, 1).glob("*.nc")):
            ds = xr.open_dataset(nc_path, engine="netcdf4")
            if "conductivity_1" in ds:
                c = ds["conductivity_1"]
                assert c.attrs.get("units") == "mS cm-1"
                # seawater conductivity is ~10-70 mS/cm; S/m would read ~1-7
                cmax = float(np.nanmax(c.values))
                assert 10.0 < cmax < 70.0, f"conductivity max {cmax} not in mS/cm range"
                checked += 1
            ds.close()
        assert checked > 0, "no fixture exercised the conductivity conversion"

    def test_nc_filename_matches_cnv_stem(self, tmp_path):
        """Each NC file must have the same stem as its source CNV."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        stage1(FIXTURES_CNV, nc_dir)
        cnv_stems = {p.stem for p in FIXTURES_CNV.glob("*.cnv")}
        # Output stems carry the _stage1 suffix; compare the base stems.
        nc_stems = {parse_stage(p)[0] for p in stage_dir(nc_dir, 1).glob("*.nc")}
        assert cnv_stems == nc_stems

    def test_skip_existing_when_force_false(self, tmp_path):
        """Second call with force=False must return 0 (all files already exist)."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        stage1(FIXTURES_CNV, nc_dir, force=False)
        n2 = stage1(FIXTURES_CNV, nc_dir, force=False)
        assert n2 == 0

    def test_overwrite_when_force_true(self, tmp_path):
        """Second call with force=True must rewrite all files and return full count."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        n1 = stage1(FIXTURES_CNV, nc_dir, force=False)
        n2 = stage1(FIXTURES_CNV, nc_dir, force=True)
        assert n2 == n1

    def test_cast_filter_restricts_output(self, tmp_path):
        """cast_filter=4 must convert only files whose stem contains '004'."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        n = stage1(FIXTURES_CNV, nc_dir, cast_filter=4)
        nc_files = list(stage_dir(nc_dir, 1).glob("*.nc"))
        assert n == len(nc_files)
        for nc_path in nc_files:
            assert "004" in nc_path.stem, f"Unexpected file: {nc_path.name}"

    def test_creates_nc_dir_if_absent(self, tmp_path):
        """stage1() must create nc_dir when it does not already exist."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "subdir" / "nc"
        assert not nc_dir.exists()
        stage1(FIXTURES_CNV, nc_dir)
        assert nc_dir.exists()

    def test_returns_zero_for_empty_dir(self, tmp_path):
        """stage1() on an empty directory must return 0 without error."""
        from ctdcast.processors.stage1 import stage1

        empty = tmp_path / "empty"
        empty.mkdir()
        nc_dir = tmp_path / "nc"
        n = stage1(empty, nc_dir)
        assert n == 0
