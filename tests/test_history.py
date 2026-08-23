"""Tests for ctdcast.processors.history — the shared stamped-history helper."""

import xarray as xr
from conftest import CAST_011

from ctdcast._version import __version__
from ctdcast.processors.history import append_history


def _load(path):
    """Load a fixture cast as an in-memory Dataset."""
    with xr.open_dataset(path, engine="netcdf4") as ds:
        return ds.load()


class TestAppendHistory:
    """append_history stamps the one canonical format and accumulates."""

    def test_stamps_version_and_stage(self):
        attrs: dict = {}
        append_history(attrs, "did a thing", stage="stage2")
        line = attrs["history"]
        assert f"ctdcast {__version__} stage2:" in line
        assert line.endswith("did a thing")

    def test_accumulates_newline_joined(self):
        attrs: dict = {}
        append_history(attrs, "first", stage="stage1")
        append_history(attrs, "second", stage="stage2")
        lines = attrs["history"].split("\n")
        assert len(lines) == 2
        assert "stage1: first" in lines[0]
        assert "stage2: second" in lines[1]

    def test_preserves_existing_history(self):
        attrs = {"history": "seed line from upstream"}
        append_history(attrs, "new step", stage="stage3")
        assert attrs["history"].startswith("seed line from upstream\n")
        assert "stage3: new step" in attrs["history"]

    def test_producer_override(self):
        """A non-ctdcast producer is stamped in place of 'ctdcast'."""
        attrs: dict = {}
        append_history(
            attrs,
            "alpha=0.03",
            stage="celltm",
            version="7.26",
            producer="SBE Data Processing",
        )
        assert "SBE Data Processing 7.26 celltm: alpha=0.03" in attrs["history"]
        assert "ctdcast" not in attrs["history"]

    def test_verbatim_timestamp_kept_without_z(self):
        """A supplied timestamp is used as-is; no ISO 'Z' is appended."""
        attrs: dict = {}
        append_history(attrs, "x", stage="datcnv", timestamp="Jul 30 2026 11:10:35")
        assert attrs["history"].startswith("Jul 30 2026 11:10:35 ")
        assert "Z" not in attrs["history"].split(" datcnv")[0]

    def test_prepend_inserts_at_front(self):
        """prepend=True puts the line before existing history (oldest-first upstream step)."""
        attrs = {"history": "reader line"}
        append_history(
            attrs, "x", stage="datcnv", timestamp="Jul 30 2026 11:10:35", prepend=True
        )
        lines = attrs["history"].split("\n")
        assert "datcnv" in lines[0]
        assert lines[1] == "reader line"

    def test_empty_note_no_trailing_space(self):
        """A module with no salient parameters leaves no dangling 'stage: ' whitespace."""
        attrs: dict = {}
        append_history(attrs, "", stage="Derive", timestamp="Jul 30 2026 11:10:44")
        assert (
            attrs["history"]
            == "Jul 30 2026 11:10:44 ctdcast " + __version__ + " Derive:"
        )


def test_history_accumulates_across_stages():
    """A stage-3 dataset inherits the stage-2 line and appends its own.

    The stages copy the input attributes rather than rebuilding them, so history
    grows down the ladder: a seed line survives, stage 2 appends, stage 3 appends.
    """
    from ctdcast.processors.qc import apply_gross_range
    from ctdcast.processors.stage2 import apply_stage2

    ds = _load(CAST_011)
    ds.attrs["history"] = "seed: upstream provenance"

    ds2 = apply_stage2(ds)
    ds3 = apply_gross_range(ds2)  # stage 3's first step

    history = ds3.attrs["history"]
    assert history.startswith("seed: upstream provenance\n"), "seed must survive"
    assert "stage2: soak/deck" in history
    assert "stage3: gross_range" in history
    # order is preserved: stage 2 line precedes the stage 3 line
    assert history.index("stage2:") < history.index("stage3:")
