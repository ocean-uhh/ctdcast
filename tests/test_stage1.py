"""Tests for ctdcast.processors.stage1 (stage1(), get_ctd_backend())."""

import pytest
import xarray as xr
from conftest import FIXTURES_CNV, FIXTURES_NC

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

    def test_correction_ledger_stamped(self, tmp_path):
        """Stage-1 output carries the SBE correction ledger read from the raw header."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        stage1(FIXTURES_CNV, nc_dir)
        stamped = 0
        for nc_path in sorted(stage_dir(nc_dir, 1).glob("*.nc")):
            ds = xr.open_dataset(nc_path, engine="netcdf4")
            attrs = ds.attrs
            ds.close()
            if "sbe_processing_order" not in attrs:
                continue
            stamped += 1
            assert "datcnv" in attrs["sbe_processing_order"]
            assert "align(deck)" in attrs["sbe_processing_order"]
            assert attrs["correction_align"].endswith(" s")
            assert attrs["sbe_acquisition"].startswith("* Sea-Bird SBE 9")
        assert stamped, "no stage-1 file carried the correction ledger"

    def test_conformance_advisories_warn_at_stage1(self):
        """A cast whose SBE processing deviates from a documented reference warns at stage 1.

        The conformance advisories #32 surfaces on the cast page are also raised as warnings
        during processing, alongside (and separate from) the structural provenance ones.
        """
        from ctdcast.processors.stage1 import _normalise

        ds = xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4")
        with pytest.warns(UserWarning) as record:
            _normalise(ds)
        messages = " ".join(str(w.message) for w in record)
        # OdB: an oxygen channel is present but no Align CTD step advances it — a conformance
        # advisory (would not appear before this loop was added).
        assert "no Align CTD step advances it" in messages

    def test_sbe_history_prepended_before_ctdcast(self, tmp_path):
        """SBE steps appear in history, oldest-first, attributed to SBE and ahead of ctdcast."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        stage1(FIXTURES_CNV, nc_dir)
        checked = 0
        for nc_path in sorted(stage_dir(nc_dir, 1).glob("*.nc")):
            ds = xr.open_dataset(nc_path, engine="netcdf4")
            history = ds.attrs.get("history", "")
            ds.close()
            if "SBE Data Processing" not in history:
                continue
            checked += 1
            lines = history.split("\n")
            # the first line is an SBE step (upstream steps prepended, oldest-first)
            assert "SBE Data Processing" in lines[0]
            # every SBE line precedes ctdcast's stage-1 line
            first_sbe = next(
                i for i, ln in enumerate(lines) if "SBE Data Processing" in ln
            )
            ctdcast_line = next(
                i for i, ln in enumerate(lines) if "ctdcast" in ln and "stage1:" in ln
            )
            assert first_sbe < ctdcast_line
            # SBE timestamps are verbatim — no ISO 'Z' before the producer
            for ln in lines:
                if "SBE Data Processing" in ln:
                    assert "Z" not in ln.split("SBE Data Processing")[0]
        assert checked, "no stage-1 file carried SBE history"

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

    def test_stamps_cruise_identity_when_cruise_info_given(self, tmp_path):
        """With cruise_info, stage 1 stamps cruise + platform + expocode globals."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        ci = {"cruise_id": "odb2026", "platform": "odb", "start_date": "2026-07-09"}
        stage1(FIXTURES_CNV, nc_dir, cruise_info=ci)
        files = sorted(stage_dir(nc_dir, 1).glob("*.nc"))
        assert files, "stage 1 produced no files"
        for nc_path in files:
            ds = xr.open_dataset(nc_path, engine="netcdf4")
            try:
                assert ds.attrs.get("cruise") == "odb2026"
                assert ds.attrs.get("platform_name")  # platform block resolved
                assert str(ds.attrs.get("expocode", "")).startswith("29OD")
            finally:
                ds.close()

    def test_no_cruise_identity_without_cruise_info(self, tmp_path):
        """Without cruise_info, stage 1 writes no identity (backward compatible)."""
        from ctdcast.processors.stage1 import stage1

        nc_dir = tmp_path / "nc"
        stage1(FIXTURES_CNV, nc_dir)
        for nc_path in sorted(stage_dir(nc_dir, 1).glob("*.nc")):
            ds = xr.open_dataset(nc_path, engine="netcdf4")
            try:
                assert "cruise" not in ds.attrs
                assert "expocode" not in ds.attrs
            finally:
                ds.close()
