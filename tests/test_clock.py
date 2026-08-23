"""Tests for the acquisition-clock diagnostic (``ctdcast.analysis.clock``).

The classifier takes cast ids and two whole-second timestamps and does arithmetic on their
differences — no oceanographic measurement is involved — so the pathologies (drift, multi-step,
too-few, a 3-cast level that must not be absorbed) are exercised with **synthetic** series that
run in CI. The real MSM142 header series is kept as a local regression test (git-excluded, real
data not public) that additionally confirms the reader and ``parse_star_block`` on real headers.
"""

import datetime as dt
import json
from pathlib import Path

import pytest
import xarray as xr

from ctdcast.analysis.clock import (
    MIN_CASTS,
    MIN_SEGMENT_CASTS,
    CastClock,
    cast_number,
    classify_offsets,
    clock_offsets,
    coordinate_summary,
    correction_status,
    suggested_config_yaml,
)
from ctdcast.config.cnv_header import parse_star_block

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "clock_local" / "msm142_star_blocks.json"
)


def _series(offsets: list[float], *, hours: float = 6.0) -> list[CastClock]:
    """Build a CastClock series from bare offsets, evenly spaced, for the synthetic branch tests."""
    base = dt.datetime(2026, 1, 1, 0, 0, 0)
    series = []
    for i, off in enumerate(offsets):
        system = base + dt.timedelta(hours=hours * i)
        series.append(
            CastClock(
                f"{i:03d}", system, system + dt.timedelta(seconds=off), float(off)
            )
        )
    return series


class TestClassifySynthetic:
    """Every classifier branch, on synthetic offset series — these run in CI."""

    def test_flat_series_is_constant(self) -> None:
        """A single level classifies as constant with no changepoints."""
        verdict = classify_offsets(_series([5, 4, 5, 6, 5, 5, 4, 5, 6, 5, 4, 5]))
        assert verdict.kind == "constant"
        assert verdict.changepoints == []
        assert verdict.segments[0].offset_seconds == pytest.approx(5.0, abs=0.1)

    def test_single_step_gives_one_changepoint(self) -> None:
        """Two clean levels classify as a step with exactly one boundary."""
        verdict = classify_offsets(_series([2, 2, 3, 2, 2] + [9, 8, 9, 9, 8]))
        assert verdict.kind == "step"
        assert len(verdict.segments) == 2
        assert len(verdict.changepoints) == 1

    def test_two_changepoints_like_msm142(self) -> None:
        """Three clean levels (the MSM142 shape) resolve into three segments, two changepoints."""
        verdict = classify_offsets(
            _series(
                [4, 4, 5] + [8, 8, 9, 8, 8, 8, 8, 8] + [-2, -2, -3, -2, -2, -2, -2, -2]
            )
        )
        assert verdict.kind == "step"
        assert [s.n_casts for s in verdict.segments] == [3, 8, 8]
        assert len(verdict.changepoints) == 2

    def test_step_with_a_noisy_segment_is_flagged_not_reclassified(self) -> None:
        """A real step whose first level is noisy stays a step, with the non-flat sd as a caveat."""
        verdict = classify_offsets(
            _series([4, 4, 5, 3, 6, 4, 5, 3, 6, 4] + [-2, -2, -3, -2, -2, -2, -2, -2])
        )
        assert verdict.kind == "step"
        assert len(verdict.segments) == 2
        assert "more structure may be present" in verdict.resolution_caveat

    def test_three_cast_level_is_not_absorbed(self) -> None:
        """A level only MIN_SEGMENT_CASTS long survives — the load-bearing case behind MSM142 001-003."""
        verdict = classify_offsets(_series([4, 4, 5] + [8, 9, 8, 8, 7, 8, 9, 8, 8, 8]))
        assert verdict.kind == "step"
        assert verdict.segments[0].n_casts == MIN_SEGMENT_CASTS
        assert verdict.segments[0].offset_seconds == pytest.approx(4.333, abs=0.01)

    def test_clean_ramp_is_drift_with_measured_rate(self) -> None:
        """A clean ramp is a drift only because a rate fits it — the note quotes the evidence."""
        verdict = classify_offsets(_series(list(range(12))))
        assert verdict.kind == "drift"
        assert verdict.changepoints == []
        assert (
            "R²" in verdict.note and "residual sd" in verdict.note
        )  # positive evidence quoted

    def test_noisy_level_is_constant_with_caveat_not_drift(self) -> None:
        """A stable level with a noisy comparison is a constant + caveat, never a drift (the OdB case).

        No rate fits (the scatter is within-time, not a trend), so failing to flatten must not be
        promoted to drift; the sd is carried as per-cast uncertainty.
        """
        verdict = classify_offsets(
            _series([-5, -1, -3, -4, -2, -5, -1, -3, -2, -4, -3, -5, -2, -1, -4, -3])
        )
        assert verdict.kind == "constant"
        assert len(verdict.segments) == 1
        assert verdict.resolution_caveat  # sd exceeds quantisation -> flagged
        assert "not structure" in verdict.resolution_caveat

    def test_just_below_min_casts_is_insufficient(self) -> None:
        """One cast short of MIN_CASTS is refused, and the message names the count scanned."""
        n = MIN_CASTS - 1
        verdict = classify_offsets(_series([5] * n), n_scanned=n)
        assert verdict.kind == "insufficient"
        assert f"{n} of {n}" in verdict.note

    def test_no_clock_pair_when_files_scanned_but_none_carry_one(self) -> None:
        """Files scanned yet no pair is its own kind (GPS-fed), distinct from too-few/no-files."""
        verdict = classify_offsets([], n_scanned=182)
        assert verdict.kind == "no_clock_pair"
        assert "182 cast(s) scanned" in verdict.note
        assert "GPS-fed" in verdict.note  # measured now: 182 scanned, none had a pair

    def test_no_casts_scanned_is_insufficient_not_no_clock_pair(self) -> None:
        """An empty series from zero casts scanned is a mount/path problem, not a GPS-fed cruise."""
        verdict = classify_offsets([], n_scanned=0)
        assert verdict.kind == "insufficient"
        assert "no cast files" in verdict.note


class TestCastNumber:
    """Cast-id -> integer, tolerant of a letter suffix."""

    def test_plain_and_suffixed(self) -> None:
        """A plain zero-padded id and a lettered variant both yield the numeric cast."""
        assert cast_number("001") == 1
        assert cast_number("029b") == 29


class TestSuggestedConfigYaml:
    """The paste-ready block: one entry per segment for step/constant, None otherwise."""

    def test_step_emits_one_entry_per_segment_with_ranges_and_signs(self) -> None:
        """A three-level step yields three ``casts``/``clock_offset_seconds`` pairs, signs intact."""
        verdict = classify_offsets(
            _series(
                [4, 4, 5] + [8, 8, 9, 8, 8, 8, 8, 8] + [-2, -2, -3, -2, -2, -2, -2, -2]
            )
        )
        block = suggested_config_yaml(verdict)
        assert block is not None
        assert block.count("- casts:") == 3
        assert "clock_offset_seconds: -2" in block  # sign preserved, not abs
        assert "do not hand-compute the sign" in block
        # each segment carries its evidence so the applier records it, not a re-measurement
        assert block.count("n_casts:") == 3
        assert block.count("clock_offset_sd_seconds:") == 3

    def test_constant_emits_one_spanning_entry(self) -> None:
        """A constant offset yields a single range spanning the whole cruise."""
        block = suggested_config_yaml(classify_offsets(_series([5] * 12)))
        assert block is not None
        assert block.count("- casts:") == 1

    def test_non_applicable_verdicts_have_no_block(self) -> None:
        """Drift, no_clock_pair and insufficient produce no block (nothing to apply)."""
        assert (
            suggested_config_yaml(classify_offsets(_series(list(range(12))))) is None
        )  # drift
        assert (
            suggested_config_yaml(classify_offsets([], n_scanned=99)) is None
        )  # no_clock_pair
        assert (
            suggested_config_yaml(classify_offsets(_series([5, 5]))) is None
        )  # insufficient

    def test_range_with_gaps_or_lettered_casts_gets_a_verify_comment(self) -> None:
        """A [[lo,hi]] range that doesn't match the cast count is flagged, not silently mis-scoped."""
        base = dt.datetime(2026, 1, 1)
        # 11 casts numbered 1-5,7-12 (cast 6 missing): numeric span 12 != 11 casts.
        nums = [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12]
        series = [
            CastClock(
                f"{n:03d}",
                base + dt.timedelta(hours=6 * i),
                base + dt.timedelta(hours=6 * i, seconds=5),
                5.0,
            )
            for i, n in enumerate(nums)
        ]
        block = suggested_config_yaml(classify_offsets(series))
        assert block is not None
        assert "VERIFY" in block


class TestCorrectionStatus:
    """The gate the CLI and report both read — so they cannot disagree."""

    def test_system_applies(self) -> None:
        """Any cast on the System clock means a correction is relevant."""
        assert correction_status({"system": 180, "nmea": 2}) == "apply"

    def test_nmea_only_is_on_gps(self) -> None:
        """A coordinate only ever on GPS needs no correction."""
        assert correction_status({"nmea": 195}) == "on_gps"

    def test_empty_is_undetermined_not_on_gps(self) -> None:
        """No parsed source is 'undetermined' — never silently treated as GPS."""
        assert correction_status({}) == "undetermined"


class TestCoordinateSummary:
    """The coordinate-source line — orthogonal to the verdict, printed on every run."""

    def test_nmea_says_already_correct(self) -> None:
        """A GPS-anchored coordinate needs no correction whatever the offset shows."""
        line = coordinate_summary({"nmea": 195}, 195)
        assert "NMEA (GPS) on 195/195" in line
        assert "already correct" in line

    def test_system_says_correction_applies(self) -> None:
        """A PC-clock-anchored coordinate is where a non-zero offset would be applied."""
        line = coordinate_summary({"system": 182}, 182)
        assert "System (PC clock) on 182/182" in line
        assert "correction applies" in line

    def test_mixed_is_flagged_for_investigation(self) -> None:
        """Mixed coordinate sources across a cruise are themselves a finding."""
        assert "mixed" in coordinate_summary({"nmea": 100, "system": 5}, 105)

    def test_none_parsed_is_stated_not_guessed(self) -> None:
        """No parseable bracket says so rather than asserting a source."""
        assert "unknown" in coordinate_summary({}, 3)


class TestPlotter:
    """The offset-vs-cast figure returns a Figure when there is something to plot."""

    def test_step_returns_a_figure(self) -> None:
        """A step verdict yields a Figure (segments + changepoints have something to draw)."""
        import matplotlib

        matplotlib.use("Agg")
        from ctdcast.plotters.plots import draw_clock_offset_fig

        series = _series([2, 2, 3, 2, 2] + [9, 8, 9, 9, 8])
        fig = draw_clock_offset_fig(series, classify_offsets(series))
        assert fig is not None
        matplotlib.pyplot.close(fig)

    def test_empty_segments_returns_none(self) -> None:
        """A verdict with no segments (no_clock_pair) has nothing to plot."""
        from ctdcast.plotters.plots import draw_clock_offset_fig

        assert draw_clock_offset_fig([], classify_offsets([], n_scanned=5)) is None


class TestReader:
    """The stage-1 file reader (clock_offsets), on tmp_path files — runs in CI."""

    @staticmethod
    def _write(directory: Path, name: str, header: str) -> None:
        """Write a minimal cast file *name* carrying *header* as the seasenselib raw_metadata envelope."""
        directory.mkdir(parents=True, exist_ok=True)
        envelope = {
            "schema": "test",
            "raw_format": "sbe-cnv",
            "blocks": {"header": header},
        }
        ds = xr.Dataset(attrs={"raw_metadata": json.dumps(envelope)})
        ds.to_netcdf(directory / name, engine="netcdf4")

    def test_skips_clockless_cast_and_counts_scanned(self, tmp_path: Path) -> None:
        """A cast without both clocks is skipped and warned; scanned counts every cast, kept or not."""
        stage1 = tmp_path / "stage1"
        self._write(
            stage1,
            "cast_001_stage1.nc",
            "* System UTC = Mar 29 2026 20:23:55\n* NMEA UTC (Time) = Mar 29 2026 20:24:00\n"
            "# start_time = Mar 29 2026 20:23:55 [System UTC, first data scan.]",
        )
        self._write(stage1, "cast_002_stage1.nc", "* System UTC = Mar 29 2026 21:00:00")
        with pytest.warns(UserWarning, match="skipped"):
            casts, scanned, coordinate_counts = clock_offsets(tmp_path)
        assert scanned == 2
        assert [c.cast_id for c in casts] == ["001"]
        assert casts[0].offset_seconds == pytest.approx(5.0)
        # cast_001 carried a [System UTC] bracket; cast_002 had none, so only the determined
        # source is counted — the bracketless cast is left out, not tallied as "unknown".
        assert coordinate_counts == {"system": 1}

    def test_reads_flat_nc_dir_layout(self, tmp_path: Path) -> None:
        """A legacy flat nc_dir (suffix-less cast files under the root, no stage1/) is discovered."""
        self._write(
            tmp_path,
            "cast_001.nc",
            "* System UTC = Mar 29 2026 20:23:55\n* NMEA UTC (Time) = Mar 29 2026 20:24:00",
        )
        self._write(
            tmp_path,
            "cast_002.nc",
            "* System UTC = Mar 29 2026 21:00:00\n* NMEA UTC (Time) = Mar 29 2026 21:00:03",
        )
        casts, scanned, _ = clock_offsets(tmp_path)
        assert scanned == 2  # flat files are folded in as stage 1, not missed
        assert [c.cast_id for c in casts] == ["001", "002"]


class TestRealMSM142Regression:
    """Local regression against the real MSM142 clock reset — skips on a fresh clone."""

    @staticmethod
    def _series() -> list[CastClock]:
        if not _FIXTURE.exists():
            pytest.skip(
                f"no local MSM142 clock fixture at {_FIXTURE} (real headers, kept off CI)"
            )
        series: list[CastClock] = []
        for rec in json.loads(_FIXTURE.read_text()):
            clocks = parse_star_block(rec["star_block"]).clocks
            assert clocks.offset_seconds is not None
            series.append(
                CastClock(
                    cast_id=rec["cast_id"],
                    system_utc=clocks.system_dt,
                    nmea_utc=clocks.nmea_dt,
                    offset_seconds=clocks.offset_seconds,
                )
            )
        series.sort(key=lambda c: c.system_utc)
        return series

    def test_recovers_three_segment_reset(self) -> None:
        """MSM142 is a real +4.33 -> +7.76 -> -2.07 step; recursion recovers all three levels."""
        verdict = classify_offsets(self._series())
        assert verdict.kind == "step"
        assert [s.n_casts for s in verdict.segments] == [3, 29, 150]
        offsets = [round(s.offset_seconds, 2) for s in verdict.segments]
        assert offsets == [4.33, 7.76, -2.07]
        assert all(
            s.sd_seconds <= 1.0 for s in verdict.segments
        )  # every segment is flat (clean)
        assert [d.date().isoformat() for d in verdict.changepoints] == [
            "2026-03-30",
            "2026-04-03",
        ]

    def test_sign_convention_is_nmea_minus_system(self) -> None:
        """offset = NMEA - System: cast 001 (system 20:23:55, nmea 20:24:00) is +5 s, not -5."""
        cast = next(c for c in self._series() if c.cast_id == "001")
        assert cast.offset_seconds == pytest.approx(
            (cast.nmea_utc - cast.system_utc).total_seconds()
        )
        assert cast.offset_seconds == pytest.approx(5.0)
