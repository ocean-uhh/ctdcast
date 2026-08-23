"""Cruise-scale acquisition-clock diagnostic: per-cast NMEA-vs-System offsets, changepoints, verdict.

Reads the acquisition (System) and GPS (NMEA) clock pair off each cast's raw Sea-Bird header —
already on every stage-1 file in ``raw_metadata`` — and classifies the cruise's clock error as a
constant offset, a drift, or one or more step changes. Read-only: this *finds* the error; whether
a correction is *applied* is a separate stage-2 decision, and turns not only on the kind here but
on whether the time coordinate is already on GPS (``start_time`` sourced from NMEA) — the two are
orthogonal.

**Sign convention, stated once because a sign error here is silent and catastrophic:**
``offset = NMEA - System`` — the seconds *added* to acquisition time to obtain corrected (GPS)
time. Positive means the acquisition clock ran **behind** GPS. This matches oceanarray's
``_apply_clock_offset``, so the value transfers without a flip.

The offsets are whole seconds, so structure is read as a **histogram of levels**, not a fitted
line: three contiguous casts at one value are a level, not scatter. :func:`classify_offsets`
recurses, splitting at each detected step until every segment is flat (sd below the quantisation).
A segment that will not flatten is a drift only if a rate positively fits it — otherwise it is a
noisy level, reported as a constant/step with a resolution caveat rather than a drift.
:func:`classify_offsets` is pure; :func:`clock_offsets` reads the stage-1 files.
"""

from __future__ import annotations

import datetime as _dt
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, pstdev, pvariance

import numpy as np
import xarray as xr

from ctdcast.config.cnv_header import (
    header_from_raw_metadata,
    parse_star_block,
    parse_start_time,
)
from ctdcast.identity import cast_id_from_name, format_cast_id
from ctdcast.processors.stage_layout import parse_stage, stage_dir

# SBE header timestamps are whole seconds.  Named, with its reasoning, so a future sub-second
# Seasave that changes the resolution does not silently loosen the flatness test below.
QUANTISATION_SECONDS = 1.0
# Fewest casts that constitute a level rather than an accident: three contiguous casts at one
# value (MSM142's 001-003, sd 0.47) are a level.  Measured and load-bearing — 4 or 5 would absorb
# that 3-cast level into its neighbour and leave those casts corrected by a value ~3 s wrong.
MIN_SEGMENT_CASTS = 3
# A split is a real step only when the between-segment gap dominates the within-segment scatter.
# With the quantisation as the scatter floor this makes ~3 s the smallest resolvable step, which
# still catches MSM142's tightest boundary (3.43 s).
STEP_GAP_FACTOR = 3.0
# A cruise with fewer casts than this cannot show cruise-scale structure: one cast's offset cannot
# be told from a stale NMEA sentence, and only the series reveals a step. Distinct from
# MIN_SEGMENT_CASTS, which is the floor on one level *within* an already-trusted series.
MIN_CASTS = 10
# When the series will not resolve into flat segments, a rate is only *claimed* (drift, not
# unresolved) with positive evidence: the line must explain the offsets down to near the
# quantisation AND account for most of their variance AND move materially over the cruise. MSM142's
# rejected fit — residual sd 2.84 s, R² 0.41 — fails all three, which is the point: a merely messy
# cruise (OdB) is a constant with a caveat, not a drift.
_DRIFT_MAX_RESIDUAL_SD = 1.5  # s; MSM142's 2.84 must fail
_DRIFT_MIN_R2 = 0.80  # MSM142's 0.41 must fail
_DRIFT_MIN_CHANGE = (
    2.0  # s over the cruise; a sub-2 s trend is not a drift worth the name
)


@dataclass(frozen=True)
class CastClock:
    """One cast's acquisition/GPS clock pair, with both raw times so the sign is checkable.

    Carries both times and the cast id (not just the derived offset): the per-cast table shows
    both so a reader can confirm the sign, and segments are labelled by cast range.
    """

    cast_id: str
    system_utc: _dt.datetime
    nmea_utc: _dt.datetime
    offset_seconds: float


@dataclass(frozen=True)
class ClockSegment:
    """A run of casts sharing one clock offset, between changepoints — one row of the segment table."""

    first_cast: str
    last_cast: str
    start: _dt.datetime
    end: _dt.datetime
    offset_seconds: float
    sd_seconds: float
    n_casts: int

    @property
    def cast_range(self) -> str:
        """Cast-id span as ``"001-003"`` (or just ``"001"`` for a single-cast segment)."""
        return (
            self.first_cast
            if self.first_cast == self.last_cast
            else f"{self.first_cast}-{self.last_cast}"
        )


@dataclass(frozen=True)
class ClockVerdict:
    """The cruise's clock classification: kind, level segments and a plain-language note.

    ``kind`` is ``"constant"``, ``"drift"``, ``"step"``, ``"no_clock_pair"`` or ``"insufficient"``.
    ``"drift"`` is claimed only when a rate is *measured* (the note quotes slope, R² and residual
    sd) — failing to resolve into flat segments is **not** evidence of a rate, so a merely noisy
    cruise is a ``"constant"`` (or ``"step"``) with a resolution caveat, never a drift.
    ``"no_clock_pair"`` (files scanned, none carrying a pair) is distinct from ``"insufficient"``
    (too few casts, or no files) so a renderer selects on ``kind`` alone, never on the note prose.
    ``resolution_caveat`` is non-empty when a segment's sd exceeds the quantisation: a statement
    about resolution (per-cast comparison noise, or possibly-hidden structure), carried beside the
    verdict rather than as a verdict of its own. Changepoints are exposed via :attr:`changepoints`.
    """

    kind: str
    segments: list[ClockSegment]
    note: str
    resolution_caveat: str = ""

    @property
    def changepoints(self) -> list[_dt.datetime]:
        """Acquisition times of the segment boundaries (empty unless the verdict is a step)."""
        return [s.start for s in self.segments[1:]] if self.kind == "step" else []


def cast_number(cast_id: str) -> int:
    """Integer cast number from a formatted cast id (``"001"`` -> 1, ``"029b"`` -> 29)."""
    return int("".join(ch for ch in cast_id if ch.isdigit()))


def suggested_config_yaml(verdict: ClockVerdict) -> str | None:
    """Paste-ready ``processing.clock`` YAML for a step/constant verdict, or ``None`` if inapplicable.

    One ``segments`` entry per segment, keyed on inclusive cast-number ranges (the
    ``ctd_groupings.yaml`` idiom). Returns ``None`` for ``drift`` (no applier), ``no_clock_pair``
    and ``insufficient``. The sign is emitted so it is copied, never hand-computed — that is the
    one thing here that is silently catastrophic to get backwards. A ``[[lo, hi]]`` range expands to
    plain casts only, so a segment holding lettered casts (``029b``) or gaps gets a warning comment
    to verify by hand rather than silently mis-scoping the correction.
    """
    if verdict.kind not in ("step", "constant"):
        return None
    lines = [
        "processing:",
        "  clock:",
        "    # seconds added to acquisition time to obtain corrected time (NMEA - System).",
        "    # Generated by ctdcast; paste as-is -- do not hand-compute the sign.",
        "    segments:",
    ]
    for seg in verdict.segments:
        lo, hi = cast_number(seg.first_cast), cast_number(seg.last_cast)
        lines.append(f"      - casts: [[{lo}, {hi}]]")
        if hi - lo + 1 != seg.n_casts:
            lines.append(
                f"        # VERIFY: {seg.n_casts} casts span numeric range {lo}-{hi} "
                f"({hi - lo + 1} numbers) — lettered casts and/or gaps; a [[lo,hi]] range covers "
                "plain casts only, so adjust by hand if a lettered cast needs the offset."
            )
        lines.append(f"        clock_offset_seconds: {seg.offset_seconds:.2f}")
    return "\n".join(lines)


def clock_offsets(
    root: Path | str,
) -> tuple[list[CastClock], int, dict[str, int]]:
    """Return the stage-1 casts carrying both clocks, the number of files scanned, and a coordinate census.

    Reads each file's ``raw_metadata`` header; a cast missing/unparseable a clock, or whose
    filename carries no cast number, is skipped and counted in a single warning. The scanned count
    lets a caller distinguish "these headers are GPS-fed" from "the data volume is not mounted". The
    census counts which clock each cast's ``start_time`` bracket anchors the *coordinate* to
    (``system`` vs ``nmea``) — the fact the stage-2 gate keys on, orthogonal to the offset
    structure. Only *determined* sources are counted; a bracketless header (``"unknown"``) is left
    out rather than tallied as a source it never named.
    """
    casts: list[CastClock] = []
    coordinate_counts: Counter[str] = Counter()
    scanned = 0
    skipped = 0
    for nc_path in sorted(stage_dir(root, 1).glob("*.nc")):
        scanned += 1
        ds = xr.open_dataset(nc_path, engine="netcdf4")
        try:
            header = header_from_raw_metadata(ds.attrs.get("raw_metadata"))
        finally:
            ds.close()
        start = parse_start_time(header or "")
        if (
            start.clock and start.clock != "unknown"
        ):  # count only a determined coordinate source
            coordinate_counts[start.clock] += 1
        clocks = parse_star_block(header or "").clocks
        parsed = parse_stage(nc_path)
        ident = cast_id_from_name(parsed[0]) if parsed else None
        if clocks.offset_seconds is None or ident is None:
            # No computable offset, or no cast number to key it on: keep it out of the series
            # rather than fabricate a cast id that later numeric steps cannot use.
            skipped += 1
            continue
        casts.append(
            CastClock(
                cast_id=format_cast_id(*ident),
                system_utc=clocks.system_dt,
                nmea_utc=clocks.nmea_dt,
                offset_seconds=clocks.offset_seconds,
            )
        )
    if skipped:
        warnings.warn(
            f"clock diagnostic: {skipped} of {scanned} cast(s) skipped for a missing clock or an "
            "unnumbered filename.",
            stacklevel=2,
        )
    casts.sort(key=lambda c: c.system_utc)
    return casts, scanned, dict(coordinate_counts)


_COORDINATE_LABELS = {"system": "System (PC clock)", "nmea": "NMEA (GPS)"}


def coordinate_summary(coordinate_counts: dict[str, int], scanned: int) -> str:
    """One line stating which clock the *time coordinate* is anchored to, and the correction consequence.

    Orthogonal to the offset verdict: a cruise can show a real offset yet need no correction because
    its coordinate was already on GPS (OdB). Reports the count, not a single answer — mixed values
    across a cruise are themselves a finding. ``nmea`` needs no correction; ``system`` is where a
    non-zero offset would be applied.
    """
    if not coordinate_counts:
        return f"Coordinate: source unknown on 0/{scanned} casts (no start_time bracket parsed)."
    if set(coordinate_counts) == {"nmea"}:
        n = coordinate_counts["nmea"]
        return f"Coordinate: NMEA (GPS) on {n}/{scanned} casts — already correct; no correction applies."
    if set(coordinate_counts) == {"system"}:
        n = coordinate_counts["system"]
        return (
            f"Coordinate: System (PC clock) on {n}/{scanned} casts — a correction applies where "
            "the offset is non-zero."
        )
    parts = ", ".join(
        f"{_COORDINATE_LABELS.get(k, k)} on {v}"
        for k, v in sorted(coordinate_counts.items(), key=lambda kv: -kv[1])
    )
    return f"Coordinate: mixed — {parts} of {scanned} — investigate before correcting."


def correction_status(coordinate_counts: dict[str, int]) -> str:
    """Whether a clock correction applies, from the coordinate census: ``apply``/``on_gps``/``undetermined``.

    The single source of truth for the gate both the CLI and the report read, so they cannot
    disagree. Any cast on the System clock means a correction is relevant (``apply``); a coordinate
    only ever on GPS needs none (``on_gps``); an empty census means no ``start_time`` bracket was
    parsed, so whether a correction applies is ``undetermined`` — which must NOT be reported as
    "already on GPS", a source that was never measured.
    """
    if coordinate_counts.get("system", 0) > 0:
        return "apply"
    if coordinate_counts.get("nmea", 0) > 0:
        return "on_gps"
    return "undetermined"


def _segment(casts: list[CastClock]) -> ClockSegment:
    """Summarise a contiguous run of casts as one :class:`ClockSegment`."""
    offsets = [c.offset_seconds for c in casts]
    return ClockSegment(
        first_cast=casts[0].cast_id,
        last_cast=casts[-1].cast_id,
        start=casts[0].system_utc,
        end=casts[-1].system_utc,
        offset_seconds=fmean(offsets),
        sd_seconds=pstdev(offsets) if len(offsets) > 1 else 0.0,
        n_casts=len(casts),
    )


def _segment_runs(casts: list[CastClock]) -> list[list[CastClock]]:
    """Recursively split *casts* at each detected step; a run with no clean step stays whole.

    The step test is the stopping rule: a run is split only where the best changepoint's
    between-segment gap dominates the within-segment scatter and both sides hold at least
    ``MIN_SEGMENT_CASTS``. A flat run has no such split and is returned as one segment.
    """
    n = len(casts)
    if n < 2 * MIN_SEGMENT_CASTS:  # cannot form two valid segments
        return [casts]
    y = [c.offset_seconds for c in casts]
    best_k = min(
        range(MIN_SEGMENT_CASTS, n - MIN_SEGMENT_CASTS + 1),
        key=lambda k: pvariance(y[:k]) * k + pvariance(y[k:]) * (n - k),
    )
    left, right = y[:best_k], y[best_k:]
    gap = abs(fmean(left) - fmean(right))
    worst_sd = max(pstdev(left), pstdev(right))
    if gap > STEP_GAP_FACTOR * max(worst_sd, QUANTISATION_SECONDS):
        return _segment_runs(casts[:best_k]) + _segment_runs(casts[best_k:])
    return [casts]


def _rate(series: list[CastClock]) -> tuple[float, float, float, float]:
    """Fit offset against acquisition time and return (slope s/day, R², residual sd s, total change s).

    Positive evidence for a drift: a good line means the offsets are explained by a rate, not by
    unresolved structure. MSM142's fit is deliberately poor (R² 0.41, residual sd 2.84), which is
    how the classifier tells a real drift from a merely messy series.
    """
    t0 = series[0].system_utc
    days = np.array([(c.system_utc - t0).total_seconds() / 86400.0 for c in series])
    y = np.array([c.offset_seconds for c in series])
    slope, intercept = np.polyfit(days, y, 1)
    residual = y - (slope * days + intercept)
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    residual_sd = float(np.sqrt(ss_res / len(y)))
    total_change = float(abs(slope) * (days[-1] - days[0]))
    return float(slope), r2, residual_sd, total_change


def classify_offsets(
    series: list[CastClock], *, n_scanned: int | None = None
) -> ClockVerdict:
    """Classify a cruise's offset series (sorted by acquisition time) into a :class:`ClockVerdict`.

    Recursively segments the series and reads the result: one segment is a **constant**, several
    are a **step**. A segment that will not flatten triggers a rate test — only a rate that
    positively fits is a **drift**; otherwise the segments stand and the non-flat sd becomes a
    resolution caveat (per-cast comparison noise, or possibly-hidden structure). *n_scanned*, when
    given, is reported in the too-few message so a reader can tell "no clocks in these headers"
    from "few files present"; the cause of an empty result is not asserted here.
    """
    n = len(series)
    scanned = n_scanned if n_scanned is not None else n
    if n == 0:
        # Split by what was measured, not assumed: no files scanned is a mount/path problem;
        # files scanned but none carrying a pair means the headers are GPS-fed.
        if scanned == 0:
            return ClockVerdict("insufficient", [], "no stage-1 files found to scan.")
        return ClockVerdict(
            "no_clock_pair",
            [],
            f"no cast carries a System/NMEA clock pair in the {scanned} file(s) scanned — "
            "start_time is GPS-fed, so there is no acquisition-clock error to correct.",
        )
    if n < MIN_CASTS:
        return ClockVerdict(
            "insufficient",
            [],
            f"only {n} of {scanned} file(s) carry a clock pair — too few to classify.",
        )

    segments = [_segment(run) for run in _segment_runs(series)]
    if not all(s.sd_seconds <= QUANTISATION_SECONDS for s in segments):
        # A segment did not flatten. That is only a *drift* if a rate positively fits; failing to
        # flatten is not itself evidence of one (MSM142's rejected fit, OdB's noisy comparison).
        # Otherwise the segments still stand as the verdict, with the non-flat sd carried as a
        # resolution caveat rather than promoted to a different diagnosis.
        slope, r2, residual_sd, total_change = _rate(series)
        if (
            residual_sd <= _DRIFT_MAX_RESIDUAL_SD
            and r2 >= _DRIFT_MIN_R2
            and total_change >= _DRIFT_MIN_CHANGE
        ):
            evidence = f"slope {slope:+.2f} s/day, R²={r2:.2f}, residual sd {residual_sd:.2f} s"
            return ClockVerdict(
                "drift",
                [_segment(series)],
                f"clock drifts ({evidence}) — a rate correction is NOT implemented, so the "
                "stage-2 applier must refuse this verdict.",
            )

    if len(segments) == 1:
        seg = segments[0]
        caveat = ""
        if seg.sd_seconds > QUANTISATION_SECONDS:
            caveat = (
                f"sd {seg.sd_seconds:.2f} s exceeds the {QUANTISATION_SECONDS:.0f} s quantisation "
                "— per-cast comparison uncertainty (likely NMEA-sentence latency), not structure."
            )
        return ClockVerdict(
            "constant",
            segments,
            f"constant offset {seg.offset_seconds:+.2f} s (sd {seg.sd_seconds:.2f}).",
            caveat,
        )

    levels = "; ".join(
        f"casts {s.cast_range} {s.offset_seconds:+.2f} s" for s in segments
    )
    boundaries = ", ".join(f"{s.start:%Y-%m-%d}" for s in segments[1:])
    non_flat = [s for s in segments if s.sd_seconds > QUANTISATION_SECONDS]
    caveat = ""
    if non_flat:
        ranges = ", ".join(s.cast_range for s in non_flat)
        caveat = (
            f"segment(s) {ranges} have sd above the {QUANTISATION_SECONDS:.0f} s quantisation — "
            "more structure may be present."
        )
    return ClockVerdict(
        "step",
        segments,
        f"step, {len(segments)} segments — {levels} (changepoint(s) {boundaries}).",
        caveat,
    )
