"""Stage-3 editing at the native scan rate: Sea-Bird's Wild Edit and Loop Edit.

Wild Edit marks values that sit far from the rest of their block of scans, as SBE Data
Processing's module of the same name does: in each block of ``scans_per_block`` scans, the
values beyond ``pass1_nstd`` standard deviations of the block mean are set aside, the mean and
standard deviation are recomputed from what is left, and a value is marked when it lies beyond
``pass2_nstd`` of those *and* farther than ``mindelta`` from the mean.  The last, partial block
is judged against the last full ``scans_per_block`` scans of the cast.

Sea-Bird replaces a marked value with its bad flag; ctdcast keeps the value and sets
``{var}_qc`` to QARTOD 4 (fail), so nothing is lost and the edit is visible in the file.  The
parameters and the number of values marked are recorded on each variable and in ``history``.

The marking is :func:`seabirdscientific.processing.wild_edit`'s; ctdcast turns its bad-flag values
into ``_qc`` flags and keeps the data.

**Where it appears to differ from SBE Data Processing** (Sea-Bird's Windows program).  On a block
where a channel sits at one or two A/D levels (an SBE 43 voltage, altimeter or fluorescence near
the surface), the standard deviation left after the first pass is about zero.  With
``mindelta`` 0 the Windows program then marks every value in the block; seabirdscientific marks
only the values off the block's main level.  On OdB cast 050 every value ctdcast marked was also
marked in the cruise's CNV, which marked 5–10 times more on those channels, in whole blocks.  The
cause is inferred from the output, not from the Windows program's source.  A ``mindelta`` of a few
A/D steps on such channels avoids both.

Loop Edit marks whole scans where the package went up on the downcast (or down on the upcast),
moved slower than ``min_velocity``, or was still in the surface soak, with
:func:`seabirdscientific.processing.loop_edit`.  ctdcast keeps every value: the marks go into
``loop_edit_flag`` and QARTOD 4 in each variable's ``_qc``, and later steps (Wild Edit and Window
Filter with ``exclude_flagged``, Bin Average) leave the marked scans out.

**Deck pressure.**  With ``deck_pressure: true``, seabirdscientific offsets the soak window by the
first scan's depth.  On OdB casts 011, 017 and 050, whose CNV headers say ``useDeckPress = 1``, SBE
Data Processing's marks match no offset instead (the recordings start with the package already in
the water, 1.8–7.5 dbar): with the first-scan offset the soak runs 90–800 scans longer, with none
the two agree except at 20–40 single scans at the speed threshold.  ``deck_pressure`` also takes a
number, the deck pressure in dbar, so ``deck_pressure: 0`` reproduces those CNVs.

Configuration, a step in ``data_processing.steps``::

    - wildedit:
        pass1_nstd: 2.0
        pass2_nstd: 20.0
        mindelta: 0.0
        scans_per_block: 100
        exclude_flagged: true    # leave scans an earlier Loop Edit marked out of the statistics
        variables: [pressure, ctd_temperature_1, conductivity_1]
    - loopedit:
        min_velocity: 0.25         # dbar/s; or mean_speed_percent: 20 with window_seconds: 300
        surface_soak: {min_depth: 5.0, max_depth: 20.0, deck_pressure: true}   # or false
        exclude_flagged: true
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import xarray as xr
from seabirdscientific import conversion as sbs_conversion
from seabirdscientific import processing as sbs_processing

from ctdcast.config.cnv_header import applied_sbe_corrections, header_from_raw_metadata
from ctdcast.processors.corrections import _number, _version
from ctdcast.processors.history import append_history
from ctdcast.processors.qc import QARTOD_FAIL, _ensure_qc, _raise_flag

#: SBE Data Processing's example values (its Wild Edit dialog), used for a key the config leaves out.
WILD_EDIT_DEFAULTS: dict[str, float | int | bool] = {
    "pass1_nstd": 2.0,
    "pass2_nstd": 20.0,
    "mindelta": 0.0,
    "scans_per_block": 100,
    "exclude_flagged": True,
}

#: Variables edited when the config names none.
DEFAULT_WILD_EDIT_VARIABLES = (
    "pressure",
    "ctd_temperature_1",
    "ctd_temperature_2",
    "conductivity_1",
    "conductivity_2",
    "oxygen_raw_1",
    "oxygen_raw_2",
)


@dataclass(frozen=True)
class WildEdit:
    """Resolved Wild Edit parameters.

    Attributes
    ----------
    pass1_nstd, pass2_nstd : float
        Standard deviations for the first and second passes.
    mindelta : float
        A value closer to the block mean than this is never marked, in the variable's units.
    scans_per_block : int
        Scans per block.
    exclude_flagged : bool
        Leave scans an earlier Loop Edit marked out of the block statistics.
    variables : tuple of str
        Variables to edit.
    """

    pass1_nstd: float
    pass2_nstd: float
    mindelta: float
    scans_per_block: int
    exclude_flagged: bool
    variables: tuple[str, ...]

    def describe(self) -> str:
        """Return the parameters as one line, for attributes and ``history``."""
        return (
            f"pass1_nstd={self.pass1_nstd:g} pass2_nstd={self.pass2_nstd:g} "
            f"mindelta={self.mindelta:g} scans_per_block={self.scans_per_block} "
            f"exclude_flagged={'yes' if self.exclude_flagged else 'no'}"
        )


def resolve_wild_edit(cfg: dict | None) -> WildEdit | None:
    """Return the Wild Edit parameters from ``{"wildedit": parameters}``, or None when absent.

    Parameters
    ----------
    cfg : dict or None
        ``{"wildedit": ...}``: the step's parameters from ``data_processing.steps``.

    Returns
    -------
    WildEdit or None
        None when ``wildedit`` is absent or empty.

    Raises
    ------
    ValueError
        On an unknown key or a value of the wrong kind.
    """
    cfg = cfg or {}
    if "wildedit" not in cfg:
        return None
    block = cfg["wildedit"] or {}
    if not isinstance(block, dict):
        raise ValueError(f"wildedit: expected a mapping, got {block!r}")
    unknown = set(block) - set(WILD_EDIT_DEFAULTS) - {"variables"}
    if unknown:
        raise ValueError(f"wildedit: unknown key(s) {sorted(unknown)}")
    merged = {**WILD_EDIT_DEFAULTS, **block}
    p1, p2, md = (
        _number(merged[k], f"wildedit.{k}")
        for k in ("pass1_nstd", "pass2_nstd", "mindelta")
    )
    spb = merged["scans_per_block"]
    if isinstance(spb, bool) or not isinstance(spb, int):
        raise ValueError(
            f"wildedit.scans_per_block: expected a whole number, got {spb!r}"
        )
    if not isinstance(merged["exclude_flagged"], bool):
        raise ValueError(
            f"wildedit.exclude_flagged: expected true or false, got {merged['exclude_flagged']!r}"
        )
    if spb < 2 or p1 <= 0 or p2 <= 0 or md < 0:
        raise ValueError(
            "wildedit: scans_per_block must be at least 2, pass1_nstd and pass2_nstd positive, "
            "mindelta not negative"
        )
    variables = block.get("variables") or DEFAULT_WILD_EDIT_VARIABLES
    if isinstance(variables, str) or not all(isinstance(v, str) for v in variables):
        raise ValueError(
            f"wildedit.variables: expected a list of names, got {variables!r}"
        )
    return WildEdit(p1, p2, md, spb, merged["exclude_flagged"], tuple(variables))


def wild_edit_mask(
    values: np.ndarray,
    params: WildEdit,
    excluded: np.ndarray | None = None,
) -> np.ndarray:
    """Return where Wild Edit marks *values*, using :func:`seabirdscientific.processing.wild_edit`.

    Parameters
    ----------
    values : numpy.ndarray
        One variable at the native scan rate; NaN is never marked and never counted.
    params : WildEdit
        The resolved parameters.
    excluded : numpy.ndarray, optional
        Boolean, true at scans to leave out of the block statistics (an earlier Loop Edit's
        marks); used only when ``params.exclude_flagged``.

    Returns
    -------
    numpy.ndarray
        Boolean, true at the values marked.
    """
    x = np.asarray(values, dtype=float)
    flags = np.zeros_like(x)
    if excluded is not None and params.exclude_flagged:
        flags[np.asarray(excluded, dtype=bool)] = sbs_processing.FLAG_VALUE
    # seabirdscientific's last-block rule indexes from len - scans_per_block, so a cast shorter
    # than one block is judged as one block.
    k = min(params.scans_per_block, x.size)
    if k < 2:
        return np.zeros(x.size, dtype=bool)
    out = sbs_processing.wild_edit(
        x,
        flags,
        params.pass1_nstd,
        params.pass2_nstd,
        k,
        params.mindelta,
        params.exclude_flagged,
    )
    return (out == sbs_processing.FLAG_VALUE) & (x != sbs_processing.FLAG_VALUE)


def apply_wild_edit(
    ds: xr.Dataset,
    cfg: dict | None,
    *,
    excluded: np.ndarray | None = None,
    cast_label: str = "?",
) -> tuple[xr.Dataset, dict[str, np.ndarray]]:
    """Apply Wild Edit to one cast: mark outliers QARTOD 4 in each named variable's ``_qc``.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 dataset at its native scan rate.
    cfg : dict or None
        ``{"wildedit": ...}``: the step's parameters from ``data_processing.steps``.
    excluded : numpy.ndarray, optional
        Scans an earlier Loop Edit marked, left out of the statistics when ``exclude_flagged``.
    cast_label : str, optional
        How the cast is named in warnings.

    Returns
    -------
    tuple of (xarray.Dataset, dict)
        A new dataset (the input is not mutated) and ``{variable: mask}`` of the values marked.
        Without a ``wildedit`` entry the dataset is returned unchanged.  A cast Sea-Bird already
        wild-edited is skipped, with a warning and a ``history`` note.
    """
    params = resolve_wild_edit(cfg)
    if params is None:
        return ds, {}
    ds = ds.copy()
    header = header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
    if "wildedit" in applied_sbe_corrections(header)["modules"]:
        message = "wildedit skipped: Sea-Bird wildedit already ran"
        warnings.warn(f"cast {cast_label}: {message}", stacklevel=2)
        append_history(ds.attrs, message, stage="stage3")
        return ds, {}
    # exclude_flagged leaves out scans an earlier Loop Edit marked; say how many there were, so
    # the record never claims an exclusion that did not happen.
    n_excluded = (
        int(np.asarray(excluded, dtype=bool).sum())
        if excluded is not None and params.exclude_flagged
        else 0
    )
    if params.exclude_flagged:
        exclusion = (
            f"{n_excluded} scan(s) marked by an earlier Loop Edit left out of the statistics"
            if excluded is not None
            else "no earlier Loop Edit, so no scans left out of the statistics"
        )
    else:
        exclusion = "no scans left out of the statistics"
    method = f"seabirdscientific {_version()} processing.wild_edit"
    marks: dict[str, np.ndarray] = {}
    absent = []
    for var in params.variables:
        if var not in ds.data_vars or ds[var].dims != ("time",):
            absent.append(var)
            continue
        mask = wild_edit_mask(ds[var].values, params, excluded)
        qc_name = _ensure_qc(ds, var)
        qc = ds[qc_name].values.copy()
        _raise_flag(qc, mask, QARTOD_FAIL)
        ds[qc_name] = (ds[qc_name].dims, qc, ds[qc_name].attrs)
        attrs = dict(ds[var].attrs)
        attrs["wild_edit"] = params.describe()
        attrs["wild_edit_method"] = method
        attrs["wild_edit_excluded"] = exclusion
        attrs["wild_edit_marked"] = int(mask.sum())
        ds[var].attrs = attrs
        marks[var] = mask
    note = f"wildedit: {params.describe()} ({exclusion}); marked " + (
        ", ".join(f"{v} {int(m.sum())}" for v, m in marks.items()) or "nothing"
    )
    if absent:
        note += f"; not in this cast: {', '.join(absent)}"
    append_history(ds.attrs, note, stage="stage3")
    return ds, marks


# --- Loop Edit ---------------------------------------------------------------------------------

#: What ``loop_edit_flag`` holds.
LOOP_EDIT_FLAG = "loop_edit_flag"


@dataclass(frozen=True)
class LoopEdit:
    """Resolved Loop Edit parameters.

    Attributes
    ----------
    min_velocity : float
        Slowest good speed along the leg, dbar/s (``fixed``), or the floor under the percent rule.
    mean_speed_percent : float or None
        When set, a scan is good if its speed is at least this percentage of the mean speed over
        ``window_seconds``; None for the fixed rule.
    window_seconds : float
        The window of the mean-speed rule.
    surface_soak : bool
        Mark the surface soak: the scans before the package passes ``min_depth`` after its last
        excursion above it, below ``max_depth``.
    min_depth, max_depth : float
        The soak window, in metres.
    deck_pressure : bool or float
        True: offset the soak window by the first scan's depth (seabirdscientific's meaning); a
        number: offset it by that pressure, in dbar; False: no offset.
    exclude_flagged : bool
        Keep the marks of an earlier Loop Edit.
    """

    min_velocity: float
    mean_speed_percent: float | None
    window_seconds: float
    surface_soak: bool
    min_depth: float
    max_depth: float
    deck_pressure: bool | float
    exclude_flagged: bool

    def describe(self) -> str:
        """Return the parameters as one line, for attributes and ``history``."""
        rule = (
            f"min_velocity={self.min_velocity:g} dbar/s"
            if self.mean_speed_percent is None
            else f"mean_speed_percent={self.mean_speed_percent:g} over {self.window_seconds:g} s "
            f"(min_velocity={self.min_velocity:g})"
        )
        soak = (
            f"surface_soak min_depth={self.min_depth:g} max_depth={self.max_depth:g} "
            f"deck_pressure={self.deck_pressure if isinstance(self.deck_pressure, bool) else f'{self.deck_pressure:g} dbar'}"
            if self.surface_soak
            else "no surface soak"
        )
        return f"{rule}; {soak}"


def resolve_loop_edit(params: object) -> LoopEdit:
    """Return the Loop Edit parameters of a ``loopedit`` step.

    Parameters
    ----------
    params : dict
        ``min_velocity`` (default 0.25 dbar/s), or ``mean_speed_percent`` with ``window_seconds``
        (default 300); ``surface_soak: {min_depth, max_depth, deck_pressure}`` (default 5, 20,
        true), or ``surface_soak: false``; ``exclude_flagged`` (default true).

    Returns
    -------
    LoopEdit
        The resolved parameters.

    Raises
    ------
    ValueError
        On an unknown key or a value of the wrong kind.
    """
    params = params or {}
    if not isinstance(params, dict):
        raise ValueError(f"loopedit: expected a mapping, got {params!r}")
    unknown = set(params) - {
        "min_velocity",
        "mean_speed_percent",
        "window_seconds",
        "surface_soak",
        "exclude_flagged",
    }
    if unknown:
        raise ValueError(f"loopedit: unknown key(s) {sorted(unknown)}")
    vmin = _number(params.get("min_velocity", 0.25), "loopedit.min_velocity")
    pct = params.get("mean_speed_percent")
    pct = None if pct is None else _number(pct, "loopedit.mean_speed_percent")
    window = _number(params.get("window_seconds", 300.0), "loopedit.window_seconds")
    if vmin < 0 or window <= 0 or (pct is not None and not 0 < pct <= 100):
        raise ValueError(
            "loopedit: min_velocity must not be negative, window_seconds positive, "
            "mean_speed_percent in (0, 100]"
        )
    soak = params.get("surface_soak", {})
    if soak is False:
        on, lo, hi, deck = False, 0.0, 0.0, False
    elif isinstance(soak, dict):
        extra = set(soak) - {"min_depth", "max_depth", "deck_pressure"}
        if extra:
            raise ValueError(f"loopedit.surface_soak: unknown key(s) {sorted(extra)}")
        on = True
        lo = _number(soak.get("min_depth", 5.0), "loopedit.surface_soak.min_depth")
        hi = _number(soak.get("max_depth", 20.0), "loopedit.surface_soak.max_depth")
        deck = soak.get("deck_pressure", True)
        if not isinstance(deck, bool):
            deck = _number(deck, "loopedit.surface_soak.deck_pressure")
        if hi < lo:
            raise ValueError(
                "loopedit.surface_soak: max_depth is shallower than min_depth"
            )
    else:
        raise ValueError(
            f"loopedit.surface_soak: expected a mapping or false, got {soak!r}"
        )
    excl = params.get("exclude_flagged", True)
    if not isinstance(excl, bool):
        raise ValueError(
            f"loopedit.exclude_flagged: expected true or false, got {excl!r}"
        )
    return LoopEdit(vmin, pct, window, on, lo, hi, deck, excl)


def _latitude(ds: xr.Dataset) -> float | None:
    for name in ("latitude", "lat"):
        if name in ds.variables:
            lat = np.asarray(ds[name].values, dtype=float)
            if np.isfinite(lat).any():
                return float(np.nanmean(lat))
    return None


def loop_edit_mask(
    pressure: np.ndarray,
    params: LoopEdit,
    interval: float,
    latitude: float,
    excluded: np.ndarray | None = None,
) -> np.ndarray:
    """Return the scans Loop Edit marks, with :func:`seabirdscientific.processing.loop_edit`.

    Parameters
    ----------
    pressure : numpy.ndarray
        Sea pressure, dbar, at the native scan rate.
    params : LoopEdit
        The resolved parameters.
    interval : float
        Scan interval, seconds.
    latitude : float
        For the depth conversion.
    excluded : numpy.ndarray, optional
        Scans an earlier Loop Edit marked, kept when ``exclude_flagged``.

    Returns
    -------
    numpy.ndarray
        Boolean, true at the scans marked.
    """
    p = np.asarray(pressure, dtype=float)
    finite = np.isfinite(p)
    if not finite.any():
        return np.ones(p.size, dtype=bool)
    if not finite.all():
        idx = np.arange(p.size)
        p = p.copy()
        p[~finite] = np.interp(idx[~finite], idx[finite], p[finite])
    flag = np.zeros(p.size)
    if excluded is not None:
        flag[np.asarray(excluded, dtype=bool)] = sbs_processing.FLAG_VALUE
    lo, hi, deck = params.min_depth, params.max_depth, params.deck_pressure
    if not isinstance(deck, bool):
        # An explicit deck pressure: offset the soak window by its depth.
        shift = float(sbs_conversion.depth_from_pressure(np.array([deck]), latitude)[0])
        lo, hi, deck = lo + shift, hi + shift, False
    out = sbs_processing.loop_edit(
        p,
        flag,
        interval,
        "fixed" if params.mean_speed_percent is None else "percent",
        params.min_velocity,
        params.window_seconds,
        params.mean_speed_percent or 20.0,
        params.surface_soak,
        lo,
        hi,
        deck,
        params.exclude_flagged,
        latitude=latitude,
        units="pressure",
    )
    return (out == sbs_processing.FLAG_VALUE) | ~finite


def apply_loop_edit(
    ds: xr.Dataset,
    params: dict,
    interval: float,
    *,
    excluded: np.ndarray | None = None,
) -> tuple[xr.Dataset, np.ndarray]:
    """Apply Loop Edit to one cast: mark whole scans, keep every value.

    The marks are written as ``loop_edit_flag`` (1 where marked) and as QARTOD 4 in every
    variable that has a ``_qc``; the parameters are recorded on ``loop_edit_flag`` and in
    ``history``.

    Parameters
    ----------
    ds : xarray.Dataset
        A dataset at its native scan rate, with ``pressure``.
    params : dict
        The ``loopedit`` step's parameters (see :func:`resolve_loop_edit`).
    interval : float
        Scan interval, seconds.
    excluded : numpy.ndarray, optional
        Scans an earlier Loop Edit marked.

    Returns
    -------
    tuple of (xarray.Dataset, numpy.ndarray)
        A new dataset (the input is not mutated) and the scans marked, including any from an
        earlier Loop Edit kept by ``exclude_flagged``.

    Raises
    ------
    ValueError
        On malformed parameters, or no ``pressure``.
    """
    p = resolve_loop_edit(params)
    if "pressure" not in ds:
        raise ValueError("loopedit: the cast has no pressure")
    lat = _latitude(ds)
    mask = loop_edit_mask(
        ds["pressure"].values, p, interval, 0.0 if lat is None else lat, excluded
    )
    ds = ds.copy()
    method = f"seabirdscientific {_version()} processing.loop_edit"
    ds[LOOP_EDIT_FLAG] = (
        "time",
        mask.astype(np.int8),
        {
            "long_name": "Scan marked by Loop Edit",
            "flag_values": np.array([0, 1], dtype=np.int8),
            "flag_meanings": "not_marked marked",
            "comment": "Pressure reversal, too slow along the leg, or surface soak; every "
            "value is kept and flagged QARTOD 4 in its _qc.",
            "loop_edit": p.describe(),
            "loop_edit_method": method,
        },
    )
    flagged = []
    for name in list(ds.data_vars):
        qc = f"{name}_qc"
        if name.endswith("_qc") or qc not in ds or ds[name].dims != ("time",):
            continue
        values = ds[qc].values.copy()
        _raise_flag(values, mask, QARTOD_FAIL)
        ds[qc] = (ds[qc].dims, values, ds[qc].attrs)
        flagged.append(name)
    note = f"loopedit: {p.describe()}; marked {int(mask.sum())} of {mask.size} scans"
    if lat is None:
        note += "; no latitude in the cast, depth computed at latitude 0"
    append_history(ds.attrs, note, stage="stage3")
    return ds, mask
