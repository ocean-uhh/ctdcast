"""``ctdcast fit``: fit alignment and cell thermal mass over a cruise and record the results.

Reads every stage-2 cast at its native scan rate, scores each conductivity line with the cost
functions in :mod:`ctdcast.analysis.fits`, and writes the **per-cast** cost surfaces to
``<ctd_root>/fits.nc``.  The cruise and per-block averages are not stored — :func:`summarise`
computes them from the per-cast costs at report time.  The report draws the corrections page from
that file.  Nothing here changes a stage file: the values reach stage 3 only through the config.

Two passes: alignment first, over every cast; then cell thermal mass on conductivity advanced by
the cruise's fitted (downcast) alignment for that line, because a misaligned line fits the wrong ``(alpha,
tau)``.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xarray as xr
import yaml
from seabirdscientific import processing as sbs_processing

from ctdcast._version import __version__
from ctdcast.analysis import fits as F
from ctdcast.config.cnv_header import applied_sbe_corrections, header_from_raw_metadata
from ctdcast.config.preferred_sensors import PREFERRED_PAIR, segment_key
from ctdcast.identity import format_cast_id
from ctdcast.processors.corrections import native_interval
from ctdcast.processors.sensor_catalog import read_cast_sensor_catalog
from ctdcast.processors.stage_layout import group_by_cast, matches_tags

#: Lines fitted, as (line number, conductivity variable, temperature variable).
_LINES = (
    (1, "conductivity_1", "ctd_temperature_1"),
    (2, "conductivity_2", "ctd_temperature_2"),
)

#: The file ``fit`` writes and ``report`` reads, under the CTD root.
FITS_FILENAME = "fits.nc"

#: Default number of consecutive casts per block.
DEFAULT_BLOCK = 10


@dataclass
class FitSettings:
    """The choices a fit was made with; recorded in ``fits.nc``.

    Attributes
    ----------
    ctm_pmin : float
        Top of the cell thermal mass window (dbar).
    gradient : float
        Thermocline threshold for the alignment cost (°C per dbar).
    align_pmin : float
        Alignment cost: scans shallower than this (dbar) are left out.
    min_speed : float
        Alignment cost: scans moving along the leg slower than this (dbar/s) are left out; 0 keeps
        every scan.
    gap_seconds : float
        Down/up weighting time scale (s).
    ctm_tolerance : float
        Acceptability fraction above the cost minimum for the recommended (alpha, tau): any point
        within it is treated as equally good (0.02 = 2%).
    block : int
        Consecutive casts per block.
    residuals, alpha, tau : numpy.ndarray
        The grids searched.
    """

    ctm_pmin: float = F.DEFAULT_CTM_PMIN
    gradient: float = F.DEFAULT_GRADIENT
    align_pmin: float = F.DEFAULT_ALIGN_PMIN
    min_speed: float = F.DEFAULT_MIN_SPEED
    gap_seconds: float = F.DEFAULT_GAP_SCALE
    ctm_tolerance: float = 0.02
    block: int = DEFAULT_BLOCK
    residuals: np.ndarray = field(default_factory=lambda: F.DEFAULT_RESIDUALS.copy())
    alpha: np.ndarray = field(default_factory=lambda: F.DEFAULT_ALPHA.copy())
    tau: np.ndarray = field(default_factory=lambda: F.DEFAULT_TAU.copy())

    @classmethod
    def from_config(cls, processing: dict | None) -> FitSettings:
        """Build settings from the ``processing.fit`` block, defaults for anything missing.

        Parameters
        ----------
        processing : dict or None
            The config ``processing:`` block.

        Returns
        -------
        FitSettings
            The settings.

        Raises
        ------
        ValueError
            On an unknown key, a value that is not a positive number, or a ``min_speed`` outside
            0–0.5 dbar/s.
        """
        block = (processing or {}).get("fit") or {}
        if not isinstance(block, dict):
            raise ValueError(f"fit: expected a mapping, got {block!r}")
        known = {
            "ctm_pmin",
            "gradient",
            "align_pmin",
            "min_speed",
            "gap_seconds",
            "ctm_tolerance",
            "block",
        }
        unknown = set(block) - known
        if unknown:
            raise ValueError(
                f"fit: unknown key(s) {sorted(unknown)}; use {sorted(known)}"
            )
        out = cls()
        for key in known & set(block):
            value = block[key]
            if key == "min_speed":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= value <= F.MAX_MIN_SPEED
                ):
                    raise ValueError(
                        f"fit.min_speed: expected 0–{F.MAX_MIN_SPEED} dbar/s, got {value!r}"
                    )
                out.min_speed = float(value)
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise ValueError(
                    f"fit.{key}: expected a positive number, got {value!r}"
                )
            setattr(out, key, int(value) if key == "block" else float(value))
        return out


def cast_arrays(ds: xr.Dataset, line: int, interval: float) -> F.Cast | None:
    """Return one line of a stage-2 cast as :class:`~ctdcast.analysis.fits.Cast`, or None.

    Scans stage 2 flagged (soak, on deck) are excluded, the record is trimmed to the first and
    last usable scan, and pressure spikes are set NaN.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 cast.
    line : int
        1 or 2.
    interval : float
        The native scan interval (s).

    Returns
    -------
    Cast or None
        None when the line's temperature or conductivity is absent, or no scan is usable.
    """
    c_var, t_var = f"conductivity_{line}", f"ctd_temperature_{line}"
    if c_var not in ds or t_var not in ds:
        return None
    good = np.ones(ds.sizes["time"], bool)
    for v in (t_var, c_var, "pressure"):
        if f"{v}_qc" in ds:
            good &= np.isin(ds[f"{v}_qc"].values, (1, 2))
    if not good.any():
        return None
    i0, i1 = np.flatnonzero(good)[[0, -1]]
    sl = slice(int(i0), int(i1) + 1)
    p = F.despike_pressure(ds["pressure"].values[sl])
    p[~good[sl]] = np.nan
    if not np.isfinite(p).any():
        return None
    t = ds[t_var].values[sl].astype(np.float64)
    c = ds[c_var].values[sl].astype(np.float64)
    t[~good[sl]] = np.nan
    c[~good[sl]] = np.nan
    return F.Cast(p, t, c, interval)


@dataclass
class _CastRecord:
    label: str
    pmax: float = np.nan
    delta_t: tuple[float, float] = (np.nan, np.nan)
    speed: tuple[float, float] = (np.nan, np.nan)
    config: str = ""
    skipped: str = ""
    sbe_aligned: frozenset[int] = field(default_factory=frozenset)
    sbe_celltm: bool = False
    casts: dict[int, F.Cast] = field(default_factory=dict)
    align: dict[int, np.ndarray] = field(default_factory=dict)
    ctm: dict[int, np.ndarray] = field(default_factory=dict)


def cruise_advance(costs: list[np.ndarray], residuals: np.ndarray) -> float | None:
    """Return the residual advance at the minimum of a line's cruise downcast curve.

    The one function both the fit pass and :func:`summarise` use, so the advance the cell
    thermal mass fit runs on and the advance the report suggests cannot diverge.  Each cost is
    evaluated at the float32 precision ``fits.nc`` stores, so the result is the same whether the
    costs come straight from the fit (float64) or are read back from the file (float32).

    Parameters
    ----------
    costs : list of numpy.ndarray
        One downcast alignment cost per cast (the ``leg = 0`` row of ``alignment_cost``).
    residuals : numpy.ndarray
        The residual-advance grid the costs were scored on.

    Returns
    -------
    float or None
        The advance (s) at the cruise minimum, or None when no cast has a well.
    """
    fit = F.median_curve([c.astype(np.float32).astype(np.float64) for c in costs])
    return None if fit is None else float(residuals[fit.index])


#: Conductivity line names used in the progress lines.
_LINE_NAME = {1: "primary", 2: "secondary"}


def _align_line(rec: _CastRecord, residuals: np.ndarray) -> str:
    """One alignment progress line: per line, the residual advance at the downcast minimum.

    ``–`` for a line whose downcast cost has no well, ``<line> Sea-Bird aligned`` for a line
    Sea-Bird already aligned, ``skipped: <reason>`` for a skipped cast, ``no thermocline`` when no
    line scored a cost.
    """
    head = f"  alignment: cast {rec.label}"
    if rec.skipped:
        return f"{head} skipped: {rec.skipped}"
    if not rec.align and not rec.sbe_aligned:
        return f"{head} no thermocline"
    parts = [head]
    for line, _c, _t in _LINES:
        if line in rec.sbe_aligned:
            parts.append(f"{_LINE_NAME[line]} Sea-Bird aligned")
            continue
        a = rec.align.get(line)
        if a is None:
            continue
        down = a[0]
        val = f"{residuals[int(np.nanargmin(down))]:+.4f}" if F.has_well(down) else "–"
        parts.append(f"{_LINE_NAME[line]} down {val} s")
    return " ".join(parts)


def _ctm_line(rec: _CastRecord, settings: FitSettings) -> str:
    """One cell-thermal-mass progress line: |ΔT| down/up, then each line's one-parameter fits.

    ``Sea-Bird celltm applied`` when Sea-Bird already ran it; ``not fitted (window below
    <ctm_pmin> dbar, both legs needed)`` when no line scored a cost.
    """
    head = f"  cell thermal mass: cast {rec.label}"
    if rec.sbe_celltm:
        return f"{head} Sea-Bird celltm applied"
    if not rec.ctm:
        return (
            f"{head} not fitted "
            f"(window below {settings.ctm_pmin:g} dbar, both legs needed)"
        )
    down, up = rec.delta_t
    parts = [f"{head} |ΔT| down/up {down:.2f} {up:.2f} °C"]
    for line, _c, _t in _LINES:
        m = rec.ctm.get(line)
        if m is None:
            continue
        n = F.normalise(m, (0, 0))
        if n is None:
            continue
        a1, t1 = F.one_parameter_fits(n, settings.alpha, settings.tau)
        parts.append(
            f"{_LINE_NAME[line]} α {a1:.4f} at τ {F.DEFAULT_TAU_SBE:g}, "
            f"τ {t1:.1f} s at α {F.DEFAULT_ALPHA_SBE:g}"
        )
    return " ".join(parts)


def fit_cruise(
    root: Path,
    settings: FitSettings,
    *,
    cast_tags: set[str] | None = None,
    progress: bool = True,
) -> xr.Dataset:
    """Fit every native-rate stage-2 cast under *root* and return the ``fits.nc`` dataset.

    Parameters
    ----------
    root : pathlib.Path
        The CTD root (``data.ctd_root``).
    settings : FitSettings
        The window, threshold and grids.
    cast_tags : set of str, optional
        Restrict to these zero-padded cast numbers (``--only``).
    progress : bool, optional
        Print one line per cast.

    Returns
    -------
    xarray.Dataset
        Per-cast costs, |ΔT|, maximum pressure and skip reasons, and the alignment each line's
        cell thermal mass was fitted on.

    Raises
    ------
    FileNotFoundError
        If *root* has no stage-2 files.
    """
    groups = group_by_cast(root)
    ids = [
        cid
        for cid in sorted(groups)
        if 2 in groups[cid] and (cast_tags is None or matches_tags(cid, cast_tags))
    ]
    if not ids:
        raise FileNotFoundError(f"no stage-2 files under {root}")
    records: list[_CastRecord] = []
    deck: dict[int, float] = {}
    scan_interval: float | None = None
    for cid in ids:
        rec = _CastRecord(format_cast_id(*cid))
        records.append(rec)
        with xr.open_dataset(
            groups[cid][2], engine="netcdf4", decode_timedelta=False
        ) as ds:
            # The cast's T/C hardware key (the preferred-pair segment serials): a change between
            # consecutive casts marks a hardware swap, drawn on the figures.  The same key
            # config.preferred_sensors.derive_segments breaks segments on, so the two agree.
            rec.config = "|".join(
                "" if name is None else name
                for name in segment_key(PREFERRED_PAIR, read_cast_sensor_catalog(ds))
            )
            interval, reason = native_interval(ds)
            if interval is None:
                rec.skipped = reason or "not at the native scan rate"
                continue
            scan_interval = scan_interval or interval
            ds = ds.load()
            # Read every cast's header (not just the first) and apply the stage-3 refusals: do not
            # fit alignment for a line Sea-Bird already aligned, nor cell thermal mass if its celltm
            # ran, so the finder never fits a correction on top of one already applied.
            header = header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
            applied = applied_sbe_corrections(header)
            if not deck:
                adv = applied["deck_advance"]
                for line, name in (
                    (1, "primary conductivity"),
                    (2, "secondary conductivity"),
                ):
                    if name in adv:
                        deck[line] = float(adv[name])
            aligned_vars = applied["aligned"]
            any_align = bool(applied["align_unparsed"])
            rec.sbe_aligned = frozenset(
                line
                for line in (1, 2)
                if any_align
                or f"conductivity_{line}" in aligned_vars
                or f"temperature_{line}" in aligned_vars
            )
            rec.sbe_celltm = "celltm" in applied["modules"]
            for line, _c, _t in _LINES:
                cast = cast_arrays(ds, line, interval)
                if cast is None:
                    continue
                rec.casts[line] = cast
        if not rec.casts:
            rec.skipped = rec.skipped or "no usable temperature/conductivity line"
            continue
        first = next(iter(rec.casts.values()))
        rec.pmax = first.pmax
        rec.delta_t = F.window_delta_t(first, settings.ctm_pmin)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            rec.speed = F.median_speeds(first, settings.align_pmin)
            for line, cast in rec.casts.items():
                if line in rec.sbe_aligned:
                    continue
                a = F.alignment_cost(
                    cast,
                    settings.residuals,
                    gradient=settings.gradient,
                    pmin=settings.align_pmin,
                    min_speed=settings.min_speed,
                )
                if a is not None:
                    rec.align[line] = a
        if progress:
            print(_align_line(rec, settings.residuals))

    align_used: dict[int, float] = {}
    for line, _c, _t in _LINES:
        r = cruise_advance(
            [rec.align[line][0] for rec in records if line in rec.align],
            settings.residuals,
        )
        if r is not None:
            align_used[line] = r

    for rec in records:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for line, cast in rec.casts.items():
                if rec.sbe_celltm:
                    continue
                c = cast.conductivity
                r = align_used.get(line, 0.0)
                if r != 0.0:
                    c = np.array(
                        sbs_processing.align_ctd(
                            F._fill(c), r, cast.interval, flag_value=np.nan
                        ),
                        dtype=float,
                    )
                    # Put the original gaps back: aligning fills them first, so without this the
                    # CTM gap check would depend on whether an alignment was applied.
                    c[np.isnan(cast.conductivity)] = np.nan
                m = F.ctm_cost(
                    F.Cast(cast.pressure, cast.temperature, c, cast.interval),
                    settings.alpha,
                    settings.tau,
                    pmin=settings.ctm_pmin,
                    gap_scale=settings.gap_seconds,
                )
                if m is not None:
                    rec.ctm[line] = m
        rec.casts.clear()
        if progress:
            print(_ctm_line(rec, settings))
    return _to_dataset(records, settings, align_used, deck, scan_interval)


def _to_dataset(
    records: list[_CastRecord],
    settings: FitSettings,
    align_used: dict[int, float],
    deck: dict[int, float],
    scan_interval: float | None = None,
) -> xr.Dataset:
    n, nl = len(records), len(_LINES)
    nr, na, nt = len(settings.residuals), len(settings.alpha), len(settings.tau)
    align = np.full((n, nl, 2, nr), np.nan, np.float32)
    ctm = np.full((n, nl, na, nt), np.nan, np.float32)
    for i, rec in enumerate(records):
        for li, (line, _c, _t) in enumerate(_LINES):
            if line in rec.align:
                align[i, li] = rec.align[line]
            if line in rec.ctm:
                ctm[i, li] = rec.ctm[line]
    return xr.Dataset(
        {
            "cast_id": (("cast",), np.array([r.label for r in records], dtype=object)),
            "pmax": (
                ("cast",),
                np.array([r.pmax for r in records], np.float32),
                {"units": "dbar", "long_name": "maximum pressure"},
            ),
            "delta_t": (
                ("cast", "leg"),
                np.array([r.delta_t for r in records], np.float32),
                {
                    "units": "degree_Celsius",
                    "long_name": "|T(bottom) - T(ctm_pmin)| across the cell thermal mass window",
                },
            ),
            "speed": (
                ("cast", "leg"),
                np.array([r.speed for r in records], np.float32),
                {
                    "units": "dbar s-1",
                    "long_name": "median speed along the leg below alignment_pmin (lowering, hauling)",
                },
            ),
            "skipped": (
                ("cast",),
                np.array([r.skipped for r in records], dtype=object),
            ),
            "sbe_aligned": (
                ("cast", "line"),
                np.array(
                    [
                        [line in r.sbe_aligned for line, _c, _t in _LINES]
                        for r in records
                    ],
                    bool,
                ),
                {
                    "long_name": "Sea-Bird already aligned this conductivity line, so the finder did not fit alignment"
                },
            ),
            "sbe_celltm": (
                ("cast",),
                np.array([r.sbe_celltm for r in records], bool),
                {
                    "long_name": "Sea-Bird's cell thermal mass ran, so the finder did not fit it"
                },
            ),
            "sensor_config": (
                ("cast",),
                np.array([r.config for r in records], dtype=object),
                {
                    "long_name": "T/C hardware key (preferred-pair segment serials); a change marks a hardware swap"
                },
            ),
            "alignment_cost": (
                ("cast", "line", "leg", "residual"),
                align,
                {
                    "long_name": "mean square of high-passed practical salinity in the thermocline"
                },
            ),
            "ctm_cost": (
                ("cast", "line", "alpha", "tau"),
                ctm,
                {
                    "long_name": "time-weighted mean square down-up practical salinity in temperature bins below ctm_pmin"
                },
            ),
            "deck_advance": (
                ("line",),
                np.array(
                    [deck.get(line, np.nan) for line, _c, _t in _LINES], np.float32
                ),
                {
                    "units": "s",
                    "long_name": "conductivity advance applied by the deck unit, already in the data",
                },
            ),
            "ctm_alignment": (
                ("line",),
                np.array(
                    [align_used.get(line, np.nan) for line, _c, _t in _LINES],
                    np.float32,
                ),
                {
                    "units": "s",
                    "long_name": "residual advance applied before the cell thermal mass fit (downcast fit)",
                },
            ),
        },
        coords={
            "line": [line for line, _c, _t in _LINES],
            "leg": ["down", "up"],
            "residual": (
                "residual",
                settings.residuals.astype(np.float32),
                {
                    "units": "s",
                    "long_name": "conductivity advance on top of the data's",
                },
            ),
            "alpha": (
                "alpha",
                settings.alpha.astype(np.float32),
                {"long_name": "cell thermal mass amplitude"},
            ),
            "tau": (
                "tau",
                settings.tau.astype(np.float32),
                {"units": "s", "long_name": "cell thermal mass time constant"},
            ),
        },
        attrs={
            "title": "ctdcast fit: alignment and cell thermal mass cost surfaces",
            "ctdcast_version": __version__,
            "date_created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ctm_pmin_dbar": settings.ctm_pmin,
            "alignment_gradient_degC_per_dbar": settings.gradient,
            "alignment_pmin_dbar": settings.align_pmin,
            "alignment_min_speed_dbar_per_s": settings.min_speed,
            "alignment_highpass": f"salinity minus its 1-s running mean, Tukey window (taper {F.TUKEY_ALPHA})",
            "alignment_speed_filter_seconds": F.PRESSURE_FILTER_SECONDS,
            "ctm_gap_seconds": settings.gap_seconds,
            "ctm_tolerance": settings.ctm_tolerance,
            "block": settings.block,
            "scan_interval_s": np.nan
            if scan_interval is None
            else float(scan_interval),
            "method": "see ctdcast.analysis.fits",
        },
    )


@dataclass(frozen=True)
class LineSummary:
    """What the fits say for one conductivity line.

    Attributes
    ----------
    line : int
        1 (primary) or 2 (secondary).
    residual : float
        Cruise residual advance (s) on top of the data's: the minimum of the downcast's median
        curve, the value suggested.
    alignment_n : int
        Casts in the downcast curve.
    residual_up : float
        The same for the upcast, shown beside it.
    alignment_n_up : int
        Casts in the upcast curve.
    alpha_rec, tau_rec : float
        The recommended (alpha, tau): the point within ``ctm_tolerance`` of the cost minimum
        closest to Sea-Bird's default. The value suggested in the YAML.
    alpha_at_tau, tau_at_alpha : float
        One-parameter fits at Sea-Bird's default for the other.
    ctm_n : int
        Casts in the cell thermal mass average.
    """

    line: int
    residual: float
    alignment_n: int
    residual_up: float
    alignment_n_up: int
    alpha_rec: float
    tau_rec: float
    alpha_at_tau: float
    tau_at_alpha: float
    ctm_n: int


def summarise(fits: xr.Dataset, *, casts: slice | None = None) -> list[LineSummary]:
    """Cruise (or block) fits per line from a ``fits.nc`` dataset.

    Cell thermal mass costs are weighted by each cast's |ΔT| across the window, so a cast with no
    gradient there contributes nothing.

    Parameters
    ----------
    fits : xarray.Dataset
        From :func:`fit_cruise` or ``fits.nc``.
    casts : slice, optional
        Restrict to these casts (a block).

    Returns
    -------
    list of LineSummary
        One per line with any usable cast.
    """
    sub = fits if casts is None else fits.isel(cast=casts)
    res = fits["residual"].values.astype(np.float64)
    al = fits["alpha"].values.astype(np.float64)
    ta = fits["tau"].values.astype(np.float64)
    tol = float(fits.attrs.get("ctm_tolerance", 0.02))
    out = []
    for li, line in enumerate(fits["line"].values):
        acost = sub["alignment_cost"].values[:, li].astype(np.float64)
        afit = F.median_curve(list(acost[:, 0]))
        ufit = F.median_curve(list(acost[:, 1]))
        costs, weights = [], []
        for m, dt in zip(
            sub["ctm_cost"].values[:, li], sub["delta_t"].values, strict=True
        ):
            n = F.normalise(m.astype(np.float64), (0, 0))
            if n is not None:
                costs.append(n)
                weights.append(np.nanmax(dt) if np.isfinite(dt).any() else 0.0)
        cfit = F.cruise_surface(costs, weights)
        if afit is None and cfit is None:
            continue
        a1, t1 = (
            (np.nan, np.nan)
            if cfit is None
            else F.one_parameter_fits(cfit.surface, al, ta)
        )
        a_rec, t_rec = (
            (np.nan, np.nan)
            if cfit is None
            else F.snap_to_default(cfit.surface, al, ta, tolerance=tol)
        )
        # The suggested advance, via the same cruise_advance the fit ran on the data it stored, so
        # the fitted-on and the suggested value cannot diverge.  Blocks compute their own the same way.
        advance = cruise_advance(list(acost[:, 0]), res)
        out.append(
            LineSummary(
                line=int(line),
                residual=np.nan if advance is None else advance,
                alignment_n=0 if afit is None else afit.n_casts,
                residual_up=np.nan if ufit is None else float(res[ufit.index]),
                alignment_n_up=0 if ufit is None else ufit.n_casts,
                alpha_rec=a_rec,
                tau_rec=t_rec,
                alpha_at_tau=a1,
                tau_at_alpha=t1,
                ctm_n=0 if cfit is None else cfit.n_casts,
            )
        )
    return out


def suggested_yaml(summaries: list[LineSummary]) -> str:
    """Return a paste-ready ``processing:`` snippet from the cruise summaries.

    Built as a dict and serialised with :func:`yaml.safe_dump`, so the snippet parses back to the
    same values the resolvers read: per-line ``alignctd`` (the downcast residual) and ``celltm``
    (the recommended alpha/tau).  Values are rounded to the grids' resolution (advance and alpha
    to 4 dp, tau to 2 dp).

    Parameters
    ----------
    summaries : list of LineSummary
        From :func:`summarise` over the whole cruise.

    Returns
    -------
    str
        The YAML text; ``""`` when nothing was fitted.
    """
    align = {
        f"conductivity_{s.line}": round(float(s.residual), 4)
        for s in summaries
        if np.isfinite(s.residual)
    }
    ctm = {
        f"conductivity_{s.line}": {
            "alpha": round(float(s.alpha_rec), 4),
            "tau": round(float(s.tau_rec), 2),
        }
        for s in summaries
        if np.isfinite(s.alpha_rec)
    }
    block: dict[str, dict] = {}
    if align:
        block["alignctd"] = align
    if ctm:
        block["celltm"] = ctm
    if not block:
        return ""
    return yaml.safe_dump(
        {"processing": block}, sort_keys=False, default_flow_style=False
    )
