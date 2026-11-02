"""Stage-3 corrections at the native scan rate: alignment, cell thermal mass, and SBE 43 oxygen.

These are the Sea-Bird processing steps that only make sense on unbinned, unfiltered data at the
instrument's own scan rate (24 Hz on a 911plus), applied with Sea-Bird's ``seabirdscientific``
toolkit:

- **alignment** (``processing.align_ctd``): advance conductivity, or an SBE 43 voltage, relative to
  pressure by a configured number of seconds;
- **cell thermal mass** (``processing.cell_thermal_mass``): correct conductivity for the heat the
  conductivity cell stores, from the temperature of the same line;
- **oxygen** (``conversion.convert_sbe43_oxygen``): derive ``ctd_oxygen`` from the aligned SBE 43
  voltage and the corrected temperature, salinity and pressure of its line, with the tau and
  hysteresis corrections of Sea-Bird Application Note 64-3.

**Where this diverges from seabirdscientific (3.1.1).**  The tau and hysteresis corrections are
computed here (:func:`sbe43_dvdt`, :func:`sbe43_hysteresis`, :func:`sbe43_tau_term`) and folded
into the voltage, and ``convert_sbe43_oxygen`` is then called with both of its corrections off.
Two reasons: speed (seabirdscientific fits a regression per scan for dV/dt, about 11 s on a
3000 dbar cast; the same least-squares slope as a convolution agrees to 1e-12 V/s in
milliseconds), and the hysteresis recursion (seabirdscientific feeds the *corrected* previous
voltage where Application Note 64-3 uses the *uncorrected* one; the two differ by a few µmol/kg
at depth).  The divergence is recorded on every derived variable (``oxygen_hysteresis_method``)
and should be removed once seabirdscientific matches Application Note 64-3: call
``convert_sbe43_oxygen`` with ``apply_tau_correction`` and ``apply_hysteresis_correction`` on
again, and drop the three functions.

Every step records its parameters on the variable it changed and in ``history``, so the correction
is reconstructable from the output file alone.  A step that cannot apply to a cast (the data is
binned, or Sea-Bird already applied the same step) is skipped with a warning and a ``history``
note; the cast's other stage-3 steps still run.

Configuration (``data_processing:``, see :mod:`ctdcast.config.layout`): ``alignctd`` and ``celltm``
are steps in ``data_processing.steps``, each entry a bare value or a ``default`` and/or ``ranges``
(``casts`` + ``value``) declaration; the oxygen window and the per-sensor conductivity slope and
offset sit beside the steps::

    data_processing:
      slope_offset:                # per conductivity sensor: C' = slope * C + offset
        conductivity_1: {slope: 1.0000452, offset: 0.0}
      oxygen:
        tau_window_seconds: 2.0    # window for the SBE 43 tau correction's dV/dt
      steps:
        - alignctd:                # seconds; + advances the variable relative to pressure
            conductivity: 0.0
            oxygen: 3.0
            conductivity_2: {ranges: [{casts: [[30, 45]], value: 0.021}]}
        - celltm:                  # alpha and tau (1/beta, seconds); conductivity only
            conductivity: {alpha: 0.03, tau: 7.0}
"""

from __future__ import annotations

import functools
import importlib.metadata
import math
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import xarray as xr
from seabirdscientific import conversion as sbs_conversion
from seabirdscientific import processing as sbs_processing
from seabirdscientific.cal_coefficients import Oxygen43Coefficients

from ctdcast.config.cnv_header import (
    applied_sbe_corrections,
    detect_instrument,
    header_from_raw_metadata,
    parse_sample_interval,
    parse_star_block,
    raw_metadata_block,
)
from ctdcast.identity import expand_cast_numbers
from ctdcast.processors.history import (
    PL_CONVERTED,
    add_processing_level,
    append_history,
)
from ctdcast.processors.qc import QARTOD_MISSING

#: Native scan interval by instrument, as :func:`ctdcast.config.cnv_header.detect_instrument`
#: names it.  Extend as other instruments arrive.
NATIVE_SCAN_INTERVAL_SECONDS: dict[str, float] = {"SBE 9": 1.0 / 24.0}

#: Default window (s) for the SBE 43 tau correction's dV/dt.
DEFAULT_OXYGEN_TAU_WINDOW_SECONDS = 2.0

# Config key -> the stage variables it may align.  A specific key (``conductivity_2``) wins over
# the family key (``conductivity``).
_ALIGN_TARGETS: dict[str, tuple[str, ...]] = {
    "conductivity_1": ("conductivity_1", "conductivity"),
    "conductivity_2": ("conductivity_2", "conductivity"),
    "oxygen_raw_1": ("oxygen_1", "oxygen"),
    "oxygen_raw_2": ("oxygen_2", "oxygen"),
}
_ALIGN_KEYS = frozenset(k for keys in _ALIGN_TARGETS.values() for k in keys)
_CTM_KEYS = frozenset({"conductivity_1", "conductivity_2", "conductivity"})
_DECK_CHANNEL = {
    "conductivity_1": "primary conductivity",
    "conductivity_2": "secondary conductivity",
}


@functools.cache
def _version() -> str:
    return importlib.metadata.version("seabirdscientific")


# --- input checks --------------------------------------------------------------------------


def native_rate_reason(ds: xr.Dataset) -> str | None:
    """Return why *ds* is not at its instrument's native scan rate, or None if it is.

    A thin wrapper over :func:`native_interval`.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 or stage-3 per-cast dataset.

    Returns
    -------
    str or None
        A one-line reason, or None when the data is at the native rate.
    """
    return native_interval(ds)[1]


def native_interval(ds: xr.Dataset) -> tuple[float | None, str | None]:
    """Return the scan interval to correct *ds* with, or why it cannot be corrected.

    Alignment, cell thermal mass and the SBE 43 tau correction act scan by scan; on binned or
    averaged data they would be wrong.  All of these must hold: ``sample_interval_seconds`` equals
    the instrument's native interval (911plus: 1/24 s), the deck unit averaged no scans, and the
    Sea-Bird chain has no ``binavg``.

    The interval returned is the instrument's exact native interval (911plus: 1/24 s), not the
    recorded one: a CNV writes it rounded (``seconds: 0.0416667``), and the rounded value makes
    seabirdscientific's time axis one sample long for some cast lengths.  A stage file written
    before stage 1 recorded the interval falls back to the CNV header's ``# interval`` line.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 or stage-3 per-cast dataset.

    Returns
    -------
    tuple of (float or None, str or None)
        ``(interval_seconds, None)`` at the native rate, else ``(None, reason)``.
    """
    header = header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
    interval = ds.attrs.get("sample_interval_seconds")
    kind = ds.attrs.get("sample_interval_kind")
    if interval is None and kind is None:
        # A stage file written before stage 1 recorded the interval: read the CNV header.
        kind, value = parse_sample_interval(header)
        interval = value if kind == "seconds" else None
    if interval is None:
        return None, (
            f"sampled by {kind}, not by scan" if kind else "no sample interval recorded"
        )
    instrument = detect_instrument(header)
    native = NATIVE_SCAN_INTERVAL_SECONDS.get(instrument or "")
    if native is None:
        return None, f"no native scan interval known for instrument {instrument!r}"
    if not math.isclose(float(interval), native, rel_tol=1e-5):
        return None, (
            f"sampled every {float(interval):g} s, not the {instrument}'s native {native:.6g} s"
        )
    averaged = parse_star_block(header).deck_unit.scans_averaged
    if averaged not in (None, 1):
        return None, f"the deck unit averaged {averaged} scans"
    if "binavg" in applied_sbe_corrections(header)["modules"]:
        return None, "bin-averaged by Sea-Bird (binavg)"
    return native, None


# --- configuration -------------------------------------------------------------------------


def _decl_value(
    decl: object, cast_number: int | None, where: str, *, value_is_mapping: bool = False
) -> tuple[Any, str] | None:
    """Value a declaration gives *cast_number*, with its source, or None.

    A declaration is either a **bare value** — the value for every cast (a number for ``alignctd``,
    an ``{alpha, tau}`` mapping for ``celltm``) — or a mapping with ``default`` and/or ``ranges`` for
    per-cast-range exceptions.

    *value_is_mapping* says whether a bare value is itself a mapping (``celltm``'s ``{alpha, tau}``).
    When it is not (``alignctd``'s number), a mapping can only be a declaration, so one that lacks
    ``default``/``ranges`` is a mis-spelled declaration and its keys are reported by name — not
    passed on as a value that later fails with a less helpful "expected a number".
    """
    is_declaration = isinstance(decl, dict) and bool({"default", "ranges"} & set(decl))
    if not is_declaration:
        if isinstance(decl, dict) and not value_is_mapping:
            raise ValueError(
                f"{where}: unknown key(s) {sorted(decl)}; use default and/or ranges"
            )
        # A bare value: the default for every cast (a number, or an {alpha, tau} mapping).
        return decl, "default"
    unknown = set(decl) - {"default", "ranges"}
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
    hits = []
    for i, rng in enumerate(decl.get("ranges") or []):
        if not isinstance(rng, dict) or "casts" not in rng or "value" not in rng:
            raise ValueError(f"{where} range {i}: needs casts and value")
        if cast_number is not None and cast_number in expand_cast_numbers(rng["casts"]):
            hits.append(rng["value"])
    if hits:
        if any(h != hits[0] for h in hits):
            raise ValueError(
                f"{where}: cast {cast_number} is in ranges with different values {hits}"
            )
        return hits[0], "range"
    if "default" in decl:
        return decl["default"], "default"
    return None


def _number(value: object, where: str) -> float:
    """*value* as a finite float, or a ValueError naming *where*."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: expected a number, got {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{where}: expected a finite number, got {value!r}")
    return out


def resolve_alignment(
    cfg: dict | None, var: str, cast_number: int | None
) -> tuple[float, str] | None:
    """Return the configured advance (s) for *var* on *cast_number*, and the key it came from.

    Parameters
    ----------
    cfg : dict or None
        ``{"alignctd": ...}``: the step's parameters from ``data_processing.steps``.
    var : str
        A stage variable: ``conductivity_1/2`` or ``oxygen_raw_1/2``.
    cast_number : int or None
        The cast's number (a lettered cast resolves by its number).

    Returns
    -------
    tuple of (float, str) or None
        ``(seconds, "alignctd.<key> <default|range>")``, or None when nothing is configured.

    Raises
    ------
    ValueError
        On an unknown key, a malformed entry, or overlapping ranges with different values.
    """
    block = (cfg or {}).get("alignctd")
    if not block:
        return None
    if not isinstance(block, dict):
        raise ValueError(f"alignctd: expected a mapping, got {block!r}")
    unknown = set(block) - _ALIGN_KEYS
    if unknown:
        raise ValueError(
            f"alignctd: unknown channel key(s) {sorted(unknown)}; use {sorted(_ALIGN_KEYS)}"
        )
    for key in _ALIGN_TARGETS.get(var, ()):
        if key in block:
            hit = _decl_value(block[key], cast_number, f"alignctd.{key}")
            if hit is not None:
                return _number(hit[0], f"alignctd.{key}"), f"alignctd.{key} {hit[1]}"
    return None


def resolve_cell_thermal_mass(
    cfg: dict | None, var: str, cast_number: int | None
) -> tuple[float, float, str] | None:
    """Return the configured ``(alpha, tau_seconds, source)`` for conductivity *var*, or None.

    The ``celltm`` block may hold ``default``/``ranges`` itself (every conductivity channel) and
    per-channel keys (``conductivity_2``) that win over it.

    Parameters
    ----------
    cfg : dict or None
        ``{"celltm": ...}``: the step's parameters from ``data_processing.steps``.
    var : str
        ``conductivity_1`` or ``conductivity_2``.
    cast_number : int or None
        The cast's number.

    Returns
    -------
    tuple of (float, float, str) or None
        ``(alpha, tau, "celltm[.<key>] <default|range>")``, or None when nothing is configured.

    Raises
    ------
    ValueError
        On an unknown key, a value without ``alpha`` and ``tau``, or conflicting ranges.
    """
    block = (cfg or {}).get("celltm")
    if not block:
        return None
    if not isinstance(block, dict):
        raise ValueError(f"celltm: expected a mapping, got {block!r}")
    unknown = set(block) - _CTM_KEYS - {"default", "ranges"}
    if unknown:
        raise ValueError(f"celltm: unknown key(s) {sorted(unknown)}")
    candidates = [(var, f"celltm.{var}"), ("conductivity", "celltm.conductivity")]
    hit = None
    for key, where in candidates:
        if key in block:
            hit = _decl_value(block[key], cast_number, where, value_is_mapping=True)
            if hit is not None:
                where_hit = where
                break
    if hit is None:
        top = {k: v for k, v in block.items() if k in ("default", "ranges")}
        if top:
            hit = _decl_value(top, cast_number, "celltm", value_is_mapping=True)
            where_hit = "celltm"
    if hit is None:
        return None
    value = hit[0]
    if not isinstance(value, dict) or "alpha" not in value or "tau" not in value:
        raise ValueError(f"{where_hit}: a value needs alpha and tau, got {value!r}")
    alpha = _number(value["alpha"], f"{where_hit}.alpha")
    tau = _number(value["tau"], f"{where_hit}.tau")
    if alpha < 0 or tau <= 0:
        raise ValueError(f"{where_hit}: needs alpha >= 0 and tau > 0, got {value!r}")
    return alpha, tau, f"{where_hit} {hit[1]}"


def resolve_slope_offset(
    block: dict | None, var: str, cast_number: int | None
) -> tuple[float, float, str] | None:
    """Return ``(slope, offset, source)`` for conductivity *var* on *cast_number*, or None.

    ``data_processing.slope_offset`` holds one entry per conductivity sensor
    (``conductivity_1``, ``conductivity_2``), each a bare ``{slope:, offset:}`` or a
    ``{default:, ranges:}`` declaration of them; ``offset`` defaults to 0.

    Parameters
    ----------
    block : dict or None
        The ``data_processing.slope_offset`` block.
    var : str
        ``conductivity_1`` or ``conductivity_2``.
    cast_number : int or None
        The cast's number.

    Returns
    -------
    tuple of (float, float, str) or None
        None when nothing is configured for *var* on this cast.

    Raises
    ------
    ValueError
        On an unknown key or a malformed value.
    """
    if not block:
        return None
    if not isinstance(block, dict):
        raise ValueError(f"slope_offset: expected a mapping, got {block!r}")
    unknown = set(block) - {"conductivity_1", "conductivity_2"}
    if unknown:
        raise ValueError(
            f"slope_offset: unknown key(s) {sorted(unknown)}; use conductivity_1, conductivity_2"
        )
    if var not in block:
        return None
    where = f"slope_offset.{var}"
    hit = _decl_value(block[var], cast_number, where, value_is_mapping=True)
    if hit is None:
        return None
    value = hit[0]
    if (
        not isinstance(value, dict)
        or "slope" not in value
        or set(value) - {"slope", "offset"}
    ):
        raise ValueError(f"{where}: a value is {{slope:, offset:}}, got {value!r}")
    slope = _number(value["slope"], f"{where}.slope")
    offset = _number(value.get("offset", 0.0), f"{where}.offset")
    if slope <= 0:
        raise ValueError(f"{where}.slope: must be positive, got {slope!r}")
    return slope, offset, f"{where} {hit[1]}"


def resolve_oxygen_window(cfg: dict | None) -> float:
    """Return the SBE 43 tau-correction window (s) from ``data_processing.oxygen``.

    Parameters
    ----------
    cfg : dict or None
        The ``data_processing:`` config block.

    Returns
    -------
    float
        ``oxygen.tau_window_seconds``, or :data:`DEFAULT_OXYGEN_TAU_WINDOW_SECONDS`.

    Raises
    ------
    ValueError
        If the block is not a mapping, has unknown keys, or the window is not a number
        spanning more than two native scans.
    """
    block = (cfg or {}).get("oxygen") or {}
    if not isinstance(block, dict):
        raise ValueError(f"oxygen: expected a mapping, got {block!r}")
    unknown = set(block) - {"tau_window_seconds"}
    if unknown:
        raise ValueError(f"oxygen: unknown key(s) {sorted(unknown)}")
    window = _number(
        block.get("tau_window_seconds", DEFAULT_OXYGEN_TAU_WINDOW_SECONDS),
        "oxygen.tau_window_seconds",
    )
    shortest = 2 * min(NATIVE_SCAN_INTERVAL_SECONDS.values())
    if window <= shortest:
        raise ValueError(
            f"oxygen.tau_window_seconds: must span more than two scans (> {shortest:.4g} s), "
            f"got {window!r}"
        )
    return window


# --- appliers ------------------------------------------------------------------------------


def align(
    values: np.ndarray, offset_seconds: float, interval_seconds: float
) -> tuple[np.ndarray, np.ndarray]:
    """Advance *values* by *offset_seconds* with seabirdscientific's ``align_ctd``.

    Positive advances the variable relative to pressure: the value at scan *k* becomes the one
    measured ``offset_seconds`` later (linear interpolation between scans).  Values that would
    come from beyond either end of the cast are NaN.

    Parameters
    ----------
    values : numpy.ndarray
        One variable at the native scan rate.
    offset_seconds : float
        The advance, in seconds.
    interval_seconds : float
        Time between scans.

    Returns
    -------
    tuple of (numpy.ndarray, numpy.ndarray)
        The aligned values (float64) and a boolean mask of the scans set NaN because they fell
        past an end.

    Raises
    ------
    ValueError
        If seabirdscientific returns an array of a different length.
    """
    x = np.asarray(values, dtype=np.float64)
    out = sbs_processing.align_ctd(
        x, offset_seconds, interval_seconds, flag_value=np.nan
    )
    if out.shape != x.shape:
        raise ValueError(f"align_ctd returned {out.shape} for input {x.shape}")
    t = np.arange(x.size) * interval_seconds + offset_seconds
    past_end = (t < 0) | (t > (x.size - 1) * interval_seconds + 1e-9)
    out[past_end] = np.nan
    return out, past_end


def cell_thermal_mass(
    conductivity_mS_cm: np.ndarray,
    temperature: np.ndarray,
    alpha: float,
    tau_seconds: float,
    interval_seconds: float,
) -> np.ndarray:
    """Correct conductivity for cell thermal mass with seabirdscientific's ``cell_thermal_mass``.

    seabirdscientific's filter works in S/m (its ``0.1 × (1 + 0.006 (T − 20))`` term is S/m per
    °C), so conductivity is converted from mS/cm to S/m, corrected, and converted back.

    Parameters
    ----------
    conductivity_mS_cm : numpy.ndarray
        Conductivity in mS/cm at the native scan rate.
    temperature : numpy.ndarray
        Temperature (°C, ITS-90) of the same line; must be finite throughout, since the
        recursive filter would carry a NaN to every later scan.
    alpha : float
        Thermal anomaly amplitude.
    tau_seconds : float
        Thermal anomaly time constant (1/beta), in seconds.
    interval_seconds : float
        Time between scans.

    Returns
    -------
    numpy.ndarray
        Corrected conductivity in mS/cm (float64).

    Raises
    ------
    ValueError
        If the temperature has non-finite values, or alpha < 0 or tau <= 0.  Alpha = 0 returns
        the conductivity unchanged.
    """
    if alpha < 0 or tau_seconds <= 0:
        raise ValueError(
            f"cell thermal mass needs alpha >= 0 and tau > 0, got {alpha}, {tau_seconds}"
        )
    if alpha == 0:
        # No correction; seabirdscientific's filter divides by alpha.
        return np.asarray(conductivity_mS_cm, dtype=np.float64).copy()
    t = np.asarray(temperature, dtype=np.float64)
    if not np.isfinite(t).all():
        raise ValueError(
            "temperature has gaps (NaN); the recursive CTM filter cannot cross them"
        )
    c_si = np.asarray(conductivity_mS_cm, dtype=np.float64) / 10.0
    corrected = sbs_processing.cell_thermal_mass(
        t, c_si, alpha, tau_seconds, interval_seconds
    )
    return np.asarray(corrected, dtype=np.float64) * 10.0


# --- orchestration -------------------------------------------------------------------------


@dataclass
class CorrectionRecord:
    """What :func:`apply_corrections` did to one cast, for stage 3 and the compiled product."""

    #: Variables whose values changed (conductivity and SBE 43 voltages).
    changed: list[str] = field(default_factory=list)
    #: ``{variable: seconds}`` advances applied.
    alignment: dict[str, float] = field(default_factory=dict)
    #: ``{variable: (alpha, tau)}`` cell-thermal-mass corrections applied.
    cell_thermal_mass: dict[str, tuple[float, float]] = field(default_factory=dict)
    #: ``{variable: boolean mask}`` scans set NaN by an alignment.
    edge_masks: dict[str, np.ndarray] = field(default_factory=dict)
    #: One-line reasons for steps that were configured but skipped.
    skipped: list[str] = field(default_factory=list)


def flag_missing(ds: xr.Dataset, var: str, mask: np.ndarray) -> None:
    """Set ``{var}_qc`` to QARTOD 9 (missing) where *mask* is true, in place.

    Parameters
    ----------
    ds : xarray.Dataset
        The dataset to flag.
    var : str
        The data variable; its ``{var}_qc`` is changed if it exists.
    mask : numpy.ndarray
        Boolean, true at the scans with no measurement.
    """
    qc = f"{var}_qc"
    if not mask.any():
        return
    if qc in ds:
        flags = ds[qc].values.copy()
        flags[mask] = QARTOD_MISSING
        ds[qc] = (ds[qc].dims, flags, ds[qc].attrs)


def _skip(record: CorrectionRecord, ds: xr.Dataset, cast: str, message: str) -> None:
    record.skipped.append(message)
    warnings.warn(f"cast {cast}: {message}", stacklevel=3)
    append_history(ds.attrs, message, stage="stage3")


def apply_corrections(
    ds: xr.Dataset,
    cruise_cfg: dict | None,
    cast_number: int | None,
    *,
    cast_label: str = "?",
) -> tuple[xr.Dataset, CorrectionRecord]:
    """Apply the configured alignment and cell thermal mass corrections to one cast.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 dataset at its native scan rate.
    cruise_cfg : dict or None
        ``{"alignctd": ...}`` and/or ``{"celltm": ...}``: one step's parameters from
        ``data_processing.steps``.
    cast_number : int or None
        The cast's number, for per-range values.
    cast_label : str, optional
        How the cast is named in warnings (e.g. ``"011"``).

    Returns
    -------
    tuple of (xarray.Dataset, CorrectionRecord)
        A new dataset (the input is not mutated) and what was done.  With neither block
        configured, the dataset is returned unchanged.

    Raises
    ------
    ValueError
        On malformed configuration.
    """
    cfg = cruise_cfg or {}
    record = CorrectionRecord()
    if not cfg.get("alignctd") and not cfg.get("celltm"):
        return ds, record
    ds = ds.copy()
    native, reason = native_interval(ds)
    if reason is not None or native is None:
        _skip(record, ds, cast_label, f"alignctd/celltm skipped: {reason}")
        return ds, record

    interval = native
    header = header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
    applied = applied_sbe_corrections(header)
    version = _version()

    # Alignment first (Sea-Bird's order: align, then cell thermal mass).
    for var in _ALIGN_TARGETS:
        if var not in ds:
            continue
        hit = resolve_alignment(cfg, var, cast_number)
        if hit is None:
            continue
        seconds, source = hit
        base = "oxygen_" + var[-1] if var.startswith("oxygen_raw") else var
        if applied["align_unparsed"]:
            _skip(
                record,
                ds,
                cast_label,
                f"alignctd {var} skipped: Sea-Bird alignctd already ran on channels ctdcast cannot name ({', '.join(applied['align_unparsed'])})",
            )
            continue
        if var.startswith("oxygen_raw") and any(
            v in ds for v in ("ctd_oxygen", "ctd_oxygen_1", "ctd_oxygen_2")
        ):
            _skip(
                record,
                ds,
                cast_label,
                f"alignctd {var} skipped: Sea-Bird already converted oxygen, which ctdcast keeps; aligning the voltage would not change it",
            )
            continue
        line_temp = f"temperature_{var[-1]}"
        if var.startswith("conductivity") and applied["aligned"].get(line_temp):
            _skip(
                record,
                ds,
                cast_label,
                f"alignctd {var} skipped: Sea-Bird alignctd advanced {line_temp} {applied['aligned'][line_temp]:+g} s, so a conductivity advance relative to pressure no longer matches it",
            )
            continue
        if base in applied["aligned"]:
            _skip(
                record,
                ds,
                cast_label,
                f"alignctd {var} skipped: Sea-Bird alignctd already advanced it {applied['aligned'][base]:+g} s",
            )
            continue
        values, mask = align(ds[var].values, seconds, interval)
        attrs = dict(ds[var].attrs)
        attrs["alignment_offset_seconds"] = seconds
        attrs["alignment_method"] = f"seabirdscientific {version} processing.align_ctd"
        attrs["alignment_config"] = source
        deck = applied["deck_advance"].get(_DECK_CHANNEL.get(var, ""))
        note = f"alignctd: {var} {seconds:+.3f} s ({source})"
        if deck:
            attrs["alignment_deck_unit_advance_seconds"] = deck
            note += f", residual on the deck-unit advance {deck:+.3f} s"
        if mask.any():
            note += (
                f"; {int(mask.sum())} scan(s) past the cast's ends set NaN, flagged 9"
            )
        ds[var] = (ds[var].dims, values.astype(ds[var].dtype, copy=False), attrs)
        flag_missing(ds, var, mask)
        record.alignment[var] = seconds
        record.edge_masks[var] = mask
        record.changed.append(var)
        append_history(ds.attrs, note, stage="stage3")

    # Cell thermal mass, conductivity only, with the temperature of the same line.
    for var in ("conductivity_1", "conductivity_2"):
        if var not in ds:
            continue
        hit = resolve_cell_thermal_mass(cfg, var, cast_number)
        if hit is None:
            continue
        alpha, tau, source = hit
        if "celltm" in applied["modules"]:
            _skip(
                record,
                ds,
                cast_label,
                f"celltm {var} skipped: Sea-Bird celltm already ran",
            )
            continue
        line = var[-1]
        temp = next(
            (t for t in (f"ctd_temperature_{line}", "ctd_temperature") if t in ds), None
        )
        if temp is None:
            _skip(
                record,
                ds,
                cast_label,
                f"celltm {var} skipped: no temperature for line {line}",
            )
            continue
        try:
            values = cell_thermal_mass(
                ds[var].values, ds[temp].values, alpha, tau, interval
            )
        except ValueError as exc:
            _skip(record, ds, cast_label, f"celltm {var} skipped: {exc}")
            continue
        attrs = dict(ds[var].attrs)
        attrs["cell_thermal_mass_alpha"] = alpha
        attrs["cell_thermal_mass_tau_seconds"] = tau
        attrs["cell_thermal_mass_temperature"] = temp
        attrs["cell_thermal_mass_method"] = (
            f"seabirdscientific {version} processing.cell_thermal_mass"
        )
        attrs["cell_thermal_mass_config"] = source
        ds[var] = (ds[var].dims, values.astype(ds[var].dtype, copy=False), attrs)
        record.cell_thermal_mass[var] = (alpha, tau)
        if var not in record.changed:
            record.changed.append(var)
        append_history(
            ds.attrs,
            f"celltm: {var} alpha={alpha:g} tau={tau:g} s with {temp} ({source})",
            stage="stage3",
        )
    return ds, record


# --- SBE 43 oxygen -------------------------------------------------------------------------


# --- SBE 43 corrections: diverges from seabirdscientific until it matches AN 64-3 ---------------
#: What the ``oxygen_hysteresis_method`` attribute records, so a reader of the file knows which
#: recursion was used.
SBE43_HYSTERESIS_METHOD = (
    "Sea-Bird Application Note 64-3: Oxnew(i) = (Ox(i) + Oxnew(i-1)*C*D - Ox(i-1)*C)/D, "
    "Ox(i-1) uncorrected (seabirdscientific 3.1.1 uses the corrected value)"
)


def sbe43_dvdt(volts: np.ndarray, window_seconds: float, interval: float) -> np.ndarray:
    """Return dV/dt for the SBE 43 tau correction: a least-squares slope over a centred window.

    The same slope seabirdscientific's ``convert_sbe43_oxygen`` fits scan by scan, as one
    convolution.  ``floor(window / 2 / interval)`` scans each side; the scans within that many of
    either end get 0, as in seabirdscientific.

    Parameters
    ----------
    volts : numpy.ndarray
        SBE 43 voltage at the native scan rate, without gaps.
    window_seconds : float
        Width of the fitting window, in seconds.
    interval : float
        Time between scans, in seconds.

    Returns
    -------
    numpy.ndarray
        dV/dt in V/s, the same length as *volts*.
    """
    v = np.asarray(volts, dtype=np.float64)
    k = math.floor(window_seconds / 2 / interval)
    out = np.zeros_like(v)
    if k < 1 or v.size < 2 * k + 1:
        return out
    j = np.arange(-k, k + 1, dtype=np.float64)
    weights = j / (interval * np.sum(j**2))
    out[k : v.size - k] = np.convolve(v, weights[::-1], mode="valid")
    return out


def sbe43_hysteresis(
    volts: np.ndarray,
    pressure: np.ndarray,
    coefs: Oxygen43Coefficients,
    interval: float,
) -> np.ndarray:
    """Return SBE 43 voltage corrected for hysteresis, as Sea-Bird Application Note 64-3 gives it.

    ``Oxnew(i) = (Ox(i) + Oxnew(i-1)·C·D − Ox(i-1)·C) / D`` with ``Ox = V + Voffset``,
    ``D = 1 + H1·(exp(P/H2) − 1)`` and ``C = exp(−interval/H3)``; ``Ox(i-1)`` is the uncorrected
    previous value.  Written as ``y(i) = C·y(i-1) + (x(i) − C·x(i-1))/D(i)``, a first-order
    recursive filter.

    Parameters
    ----------
    volts : numpy.ndarray
        SBE 43 voltage, without gaps.
    pressure : numpy.ndarray
        Pressure (dbar), same length.
    coefs : seabirdscientific.cal_coefficients.Oxygen43Coefficients
        The sensor's calibration (``h1``, ``h2``, ``h3``, ``v_offset``).
    interval : float
        Time between scans, in seconds.

    Returns
    -------
    numpy.ndarray
        Corrected voltage (V), the same length; the first scan is unchanged.
    """
    from scipy import signal

    x = np.asarray(volts, dtype=np.float64) + coefs.v_offset
    if x.size < 2:
        return x - coefs.v_offset
    d = 1.0 + coefs.h1 * (
        np.exp(np.asarray(pressure, dtype=np.float64) / coefs.h2) - 1.0
    )
    c = math.exp(-interval / coefs.h3)
    u = np.empty_like(x)
    u[0] = x[0]
    u[1:] = (x[1:] - c * x[:-1]) / d[1:]
    return signal.lfilter([1.0], [1.0, -c], u) - coefs.v_offset


def sbe43_tau_term(
    dvdt: np.ndarray,
    temperature: np.ndarray,
    pressure: np.ndarray,
    coefs: Oxygen43Coefficients,
) -> np.ndarray:
    """Return the tau correction in volts: ``tau20·exp(D1·P + D2·(T − 20))·dV/dt``.

    Added to the voltage, it gives what seabirdscientific's equation does with its tau term.

    Parameters
    ----------
    dvdt : numpy.ndarray
        From :func:`sbe43_dvdt`.
    temperature : numpy.ndarray
        ITS-90 temperature (°C).
    pressure : numpy.ndarray
        Pressure (dbar).
    coefs : seabirdscientific.cal_coefficients.Oxygen43Coefficients
        The sensor's calibration (``tau_20``, ``d1``, ``d2``).

    Returns
    -------
    numpy.ndarray
        The term, in volts.
    """
    return (
        coefs.tau_20
        * np.exp(coefs.d1 * pressure + coefs.d2 * (temperature - 20.0))
        * dvdt
    )


def sbe43_oxygen(
    volts: np.ndarray,
    temperature: np.ndarray,
    pressure: np.ndarray,
    salinity: np.ndarray,
    coefs: Oxygen43Coefficients,
    window_seconds: float,
    interval: float,
) -> np.ndarray:
    """Return SBE 43 oxygen (µmol/kg) with the tau and Application Note 64-3 hysteresis corrections.

    dV/dt comes from the uncorrected voltage and hysteresis acts on the voltage, as in
    seabirdscientific; the corrected voltage plus the tau term then goes through
    ``convert_sbe43_oxygen`` with its own corrections off.

    Parameters
    ----------
    volts, temperature, pressure, salinity : numpy.ndarray
        SBE 43 voltage, ITS-90 temperature (°C), pressure (dbar) and practical salinity of one
        unbroken run of finite scans.
    coefs : seabirdscientific.cal_coefficients.Oxygen43Coefficients
        The sensor's calibration.
    window_seconds : float
        The tau correction's dV/dt window, in seconds.
    interval : float
        Time between scans, in seconds.

    Returns
    -------
    numpy.ndarray
        Oxygen in µmol/kg.
    """
    dvdt = sbe43_dvdt(volts, window_seconds, interval)
    v = sbe43_hysteresis(volts, pressure, coefs, interval)
    v = v + sbe43_tau_term(dvdt, temperature, pressure, coefs)
    return sbs_conversion.convert_sbe43_oxygen(
        v, temperature, pressure, salinity, coefs,
        apply_tau_correction=False, apply_hysteresis_correction=False, units="umol/kg",
    )  # fmt: skip


def _finite_runs(good: np.ndarray) -> list[slice]:
    """Slices of each unbroken run of True in *good*."""
    edges = np.diff(np.concatenate(([0], good.astype(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    return [slice(int(a), int(b)) for a, b in zip(starts, stops, strict=True)]


def derive_oxygen(
    ds: xr.Dataset, cruise_cfg: dict | None = None, *, cast_label: str = "?"
) -> tuple[xr.Dataset, list[str]]:
    """Derive ``ctd_oxygen`` from each SBE 43 voltage, as Sea-Bird's Data Conversion does.

    For each ``oxygen_raw_<N>`` with no converted oxygen beside it (a CNV's own ``ctd_oxygen`` is
    never re-derived), oxygen in µmol/kg is computed with ``convert_sbe43_oxygen`` from the
    (aligned) voltage, the temperature, practical salinity and pressure of line *N* (line 1 if the
    cast has no line *N*), and the sensor's coefficients from the ``.xmlcon`` in
    ``raw_metadata``, with the tau and hysteresis corrections on (Sea-Bird Application Note 64-3).
    One sensor gives plain ``ctd_oxygen``; two give ``ctd_oxygen_1``/``_2``.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-3 dataset after alignment, CTM and salinity.
    cruise_cfg : dict or None
        The ``data_processing:`` block; ``oxygen.tau_window_seconds`` sets the tau-correction window.
    cast_label : str, optional
        How the cast is named in warnings.

    Returns
    -------
    tuple of (xarray.Dataset, list of str)
        A new dataset and the names of the variables written.
    """
    raws = [v for v in ("oxygen_raw_1", "oxygen_raw_2") if v in ds]
    if not raws or any(v in ds for v in ("ctd_oxygen", "ctd_oxygen_1", "ctd_oxygen_2")):
        return ds, []
    xml = raw_metadata_block(ds.attrs.get("raw_metadata"), "xmlcon")
    if xml is None:
        warnings.warn(
            f"cast {cast_label}: oxygen not derived: no .xmlcon in raw_metadata",
            stacklevel=2,
        )
        return ds, []
    from ctdcast.readers.xmlcon import oxygen43_coefficients, parse_xmlcon

    sensors = parse_xmlcon(xml).by_element("OxygenSensor")
    interval, reason = native_interval(ds)
    if interval is None:
        warnings.warn(
            f"cast {cast_label}: oxygen not derived: {reason}",
            stacklevel=2,
        )
        return ds, []
    window = resolve_oxygen_window(cruise_cfg)
    ds = ds.copy()
    written = []
    version = _version()
    single = len(raws) == 1
    for raw in raws:
        n = int(raw[-1])
        if n > len(sensors):
            warnings.warn(
                f"cast {cast_label}: {raw} has no OxygenSensor {n} in the .xmlcon",
                stacklevel=2,
            )
            continue
        line = str(n) if f"ctd_temperature_{n}" in ds else "1"
        temp = next(
            v for v in (f"ctd_temperature_{line}", "ctd_temperature") if v in ds
        )
        sal = next(
            (v for v in (f"ctd_salinity_{line}", "ctd_salinity") if v in ds), None
        )
        if sal is None:
            warnings.warn(
                f"cast {cast_label}: {raw} not converted: no salinity on line {line}",
                stacklevel=2,
            )
            continue
        volts = ds[raw].values.astype(np.float64)
        t, s, p = (ds[v].values.astype(np.float64) for v in (temp, sal, "pressure"))
        good = np.isfinite(volts) & np.isfinite(t) & np.isfinite(s) & np.isfinite(p)
        o2 = np.full(volts.shape, np.nan)
        coefs = oxygen43_coefficients(sensors[n - 1])
        # The tau and hysteresis corrections step scan to scan, so each unbroken run of finite
        # scans is converted on its own: a NaN would otherwise spread through the filter.  A
        # run shorter than the tau window stays NaN.
        min_run = int(math.ceil(window / interval)) + 1
        for span in _finite_runs(good):
            if span.stop - span.start < min_run:
                continue
            o2[span] = sbe43_oxygen(
                volts[span], t[span], p[span], s[span], coefs, window, interval
            )
        name = "ctd_oxygen" if single else f"ctd_oxygen_{n}"
        attrs = {
            "units": "umol kg-1",
            "conversion_method": (
                f"seabirdscientific {version} conversion.convert_sbe43_oxygen, its corrections "
                "off; tau and hysteresis by ctdcast.processors.corrections.sbe43_oxygen"
            ),
            "oxygen_tau_correction": "yes",
            "oxygen_tau_window_seconds": window,
            "oxygen_hysteresis_correction": "yes",
            "oxygen_hysteresis_method": SBE43_HYSTERESIS_METHOD,
            "derived_from": f"{raw}, {temp}, {sal}, pressure",
            "sensor_serial_number": sensors[n - 1].serial or "UNK",
        }
        if "sensor" in ds[raw].attrs:  # the voltage's link to its SENSOR_OXYGEN_* entry
            attrs["sensor"] = ds[raw].attrs["sensor"]
        add_processing_level(attrs, PL_CONVERTED)
        ds[name] = (ds[raw].dims, o2, attrs)
        if f"{raw}_qc" in ds:
            # The voltage's flags (stage-2 soak/deck, alignment edges) carry to the oxygen.
            # Its long_name names the voltage; dropped so the writer names this variable.
            ds[f"{name}_qc"] = (
                ds[raw].dims,
                ds[f"{raw}_qc"].values.copy(),
                {k: v for k, v in ds[f"{raw}_qc"].attrs.items() if k != "long_name"},
            )
        written.append(name)
        append_history(
            ds.attrs,
            f"oxygen: {name} from {raw} with {temp}, {sal}, pressure; SBE 43 tau correction "
            f"(window {window:g} s) and Application Note 64-3 hysteresis correction",
            stage="stage3",
        )
    return ds, written
