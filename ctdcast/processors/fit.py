"""``ctdcast fit``: fit alignment and cell thermal mass over a cruise and record the results.

Reads every stage-2 cast at its native scan rate, scores each conductivity line with the cost
functions in :mod:`ctdcast.analysis.fits`, and writes them, with the cruise averages and the
blocks of consecutive casts, to ``<ctd_root>/fits.nc``.  The report draws the corrections page
from that file.  Nothing here changes a stage file: the values reach stage 3 only through the
config.

Two passes: alignment first, over every cast; then cell thermal mass on conductivity advanced by
the cruise's fitted alignment for that line, because a misaligned line fits the wrong ``(alpha,
tau)``.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xarray as xr
from seabirdscientific import processing as sbs_processing

from ctdcast._version import __version__
from ctdcast.analysis import fits as F
from ctdcast.config.cnv_header import applied_sbe_corrections, header_from_raw_metadata
from ctdcast.identity import format_cast_id
from ctdcast.processors.corrections import native_interval
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
    gap_seconds : float
        Down/up weighting time scale (s).
    block : int
        Consecutive casts per block.
    residuals, alpha, tau : numpy.ndarray
        The grids searched.
    """

    ctm_pmin: float = F.DEFAULT_CTM_PMIN
    gradient: float = F.DEFAULT_GRADIENT
    gap_seconds: float = F.DEFAULT_GAP_SCALE
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
            On an unknown key or a value that is not a positive number.
        """
        block = (processing or {}).get("fit") or {}
        if not isinstance(block, dict):
            raise ValueError(f"fit: expected a mapping, got {block!r}")
        known = {"ctm_pmin", "gradient", "gap_seconds", "block"}
        unknown = set(block) - known
        if unknown:
            raise ValueError(
                f"fit: unknown key(s) {sorted(unknown)}; use {sorted(known)}"
            )
        out = cls()
        for key in known & set(block):
            value = block[key]
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
    skipped: str = ""
    casts: dict[int, F.Cast] = field(default_factory=dict)
    align: dict[int, np.ndarray] = field(default_factory=dict)
    ctm: dict[int, np.ndarray] = field(default_factory=dict)


def _cruise_alignment(
    records: list[_CastRecord], line: int, residuals: np.ndarray
) -> float | None:
    """Return the residual advance at the minimum of the line's cruise-average alignment cost."""
    j0 = int(np.argmin(np.abs(residuals)))
    costs = []
    for r in records:
        a = r.align.get(line)
        if a is None:
            continue
        total = np.where(np.isfinite(a).any(axis=0), np.nansum(a, axis=0), np.nan)
        n = F.normalise(total, (j0,)) if F.has_interior_minimum(total) else None
        if n is not None:
            costs.append(n)
    fit = F.cruise_surface(costs)
    return None if fit is None else float(residuals[fit.index[0]])


#: Conductivity line names used in the progress lines.
_LINE_NAME = {1: "primary", 2: "secondary"}


def _align_line(rec: _CastRecord, residuals: np.ndarray) -> str:
    """One alignment progress line: per line, the residual advance at the down+up minimum.

    ``no minimum`` when the summed cost still falls at an end of the search, ``skipped: <reason>``
    for a skipped cast, ``no thermocline`` when no line scored a cost.
    """
    head = f"  alignment: cast {rec.label}"
    if rec.skipped:
        return f"{head} skipped: {rec.skipped}"
    if not rec.align:
        return f"{head} no thermocline"
    parts = [head]
    for line, _c, _t in _LINES:
        a = rec.align.get(line)
        if a is None:
            continue
        total = np.where(np.isfinite(a).any(axis=0), np.nansum(a, axis=0), np.nan)
        best = (
            float(residuals[int(np.nanargmin(total))])
            if F.has_interior_minimum(total)
            else None
        )
        best_s = "no minimum" if best is None else f"{best:+.3f} s"
        parts.append(f"{_LINE_NAME[line]} {best_s}")
    return " ".join(parts)


def _ctm_line(rec: _CastRecord, settings: FitSettings) -> str:
    """One cell-thermal-mass progress line: |ΔT| down/up, then each line's one-parameter fits.

    ``not fitted (window below <ctm_pmin> dbar, both legs needed)`` when no line scored a cost.
    """
    if not rec.ctm:
        return (
            f"  cell thermal mass: cast {rec.label} not fitted "
            f"(window below {settings.ctm_pmin:g} dbar, both legs needed)"
        )
    down, up = rec.delta_t
    parts = [
        f"  cell thermal mass: cast {rec.label} |ΔT| down/up {down:.2f} {up:.2f} °C"
    ]
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
    for cid in ids:
        rec = _CastRecord(format_cast_id(*cid))
        records.append(rec)
        with xr.open_dataset(
            groups[cid][2], engine="netcdf4", decode_timedelta=False
        ) as ds:
            interval, reason = native_interval(ds)
            if interval is None:
                rec.skipped = reason or "not at the native scan rate"
                continue
            ds = ds.load()
            if not deck:
                header = header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
                adv = applied_sbe_corrections(header)["deck_advance"]
                for line, name in (
                    (1, "primary conductivity"),
                    (2, "secondary conductivity"),
                ):
                    if name in adv:
                        deck[line] = float(adv[name])
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
            for line, cast in rec.casts.items():
                a = F.alignment_cost(
                    cast, settings.residuals, gradient=settings.gradient
                )
                if a is not None:
                    rec.align[line] = a
        if progress:
            print(_align_line(rec, settings.residuals))

    align_used: dict[int, float] = {}
    for line, _c, _t in _LINES:
        r = _cruise_alignment(records, line, settings.residuals)
        if r is not None:
            align_used[line] = r

    for rec in records:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for line, cast in rec.casts.items():
                c = cast.conductivity
                r = align_used.get(line, 0.0)
                if r != 0.0:
                    c = sbs_processing.align_ctd(
                        F._fill(c), r, cast.interval, flag_value=np.nan
                    )
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
    return _to_dataset(records, settings, align_used, deck)


def _to_dataset(
    records: list[_CastRecord],
    settings: FitSettings,
    align_used: dict[int, float],
    deck: dict[int, float],
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
            "skipped": (
                ("cast",),
                np.array([r.skipped for r in records], dtype=object),
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
                    "long_name": "residual advance applied before the cell thermal mass fit",
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
            "ctm_gap_seconds": settings.gap_seconds,
            "block": settings.block,
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
        Cruise residual advance (s) on top of the data's.
    alignment_n : int
        Casts in the alignment average.
    alpha, tau : float
        Cruise two-parameter minimum.
    alpha_at_tau, tau_at_alpha : float
        One-parameter fits at Sea-Bird's default for the other.
    sbe_ratio : float
        Sea-Bird's (0.03, 7) cost as a multiple of the minimum.
    ctm_n : int
        Casts in the cell thermal mass average.
    """

    line: int
    residual: float
    alignment_n: int
    alpha: float
    tau: float
    alpha_at_tau: float
    tau_at_alpha: float
    sbe_ratio: float
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
    j0 = int(np.argmin(np.abs(res)))
    out = []
    for li, line in enumerate(fits["line"].values):
        acosts = []
        for a in sub["alignment_cost"].values[:, li]:
            total = np.where(
                np.isfinite(a).any(axis=0), np.nansum(a, axis=0), np.nan
            ).astype(np.float64)
            n = F.normalise(total, (j0,)) if F.has_interior_minimum(total) else None
            if n is not None:
                acosts.append(n)
        afit = F.cruise_surface(acosts)
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
        if cfit is not None:
            ia = int(np.argmin(np.abs(al - F.DEFAULT_ALPHA_SBE)))
            jt = int(np.argmin(np.abs(ta - F.DEFAULT_TAU_SBE)))
            ratio = float(cfit.surface[ia, jt] / cfit.surface[cfit.index])
        out.append(
            LineSummary(
                line=int(line),
                residual=np.nan if afit is None else float(res[afit.index[0]]),
                alignment_n=0 if afit is None else afit.n_casts,
                alpha=np.nan if cfit is None else float(al[cfit.index[0]]),
                tau=np.nan if cfit is None else float(ta[cfit.index[1]]),
                alpha_at_tau=a1,
                tau_at_alpha=t1,
                sbe_ratio=np.nan if cfit is None else ratio,
                ctm_n=0 if cfit is None else cfit.n_casts,
            )
        )
    return out


def suggested_yaml(summaries: list[LineSummary], deck_advance: float | None) -> str:
    """Return a paste-ready ``processing:`` snippet from the cruise summaries.

    Parameters
    ----------
    summaries : list of LineSummary
        From :func:`summarise` over the whole cruise.
    deck_advance : float or None
        The deck unit's advance already in the data (s), for the comment.

    Returns
    -------
    str
        YAML text with per-line ``alignctd`` and ``celltm`` entries and comments giving n and how
        Sea-Bird's default compares.
    """
    align = [
        f"    conductivity_{s.line}: {{default: {s.residual:+.3f}}}  # n={s.alignment_n}"
        + (
            ""
            if deck_advance is None
            else f", total {deck_advance + s.residual:.3f} s with the deck unit's {deck_advance:.3f}"
        )
        for s in summaries
        if np.isfinite(s.residual)
    ]
    ctm = [
        f"    conductivity_{s.line}: {{default: {{alpha: {s.alpha:g}, tau: {s.tau:g}}}}}"
        f"  # n={s.ctm_n}; Sea-Bird (0.03, 7) is {s.sbe_ratio:.3f}x the minimum;"
        f" alpha {s.alpha_at_tau:g} at tau 7, tau {s.tau_at_alpha:g} at alpha 0.03"
        for s in summaries
        if np.isfinite(s.alpha)
    ]
    lines = ["processing:"]
    if align:
        lines += ["  alignctd:", *align]
    if ctm:
        lines += ["  celltm:", *ctm]
    return "\n".join(lines)
