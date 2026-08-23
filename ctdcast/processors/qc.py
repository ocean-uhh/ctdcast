"""Stage QC — two-tier gross-range and spike flagging.

Each test has a suspect tier (QARTOD flag 3) and a fail tier (flag 4); the wider
fail bound wins, and a more-severe flag is never downgraded (worst-flag-wins).
Non-finite samples are marked missing (flag 9), not pass.  The thresholds applied
are recorded as attributes on each ``{var}_qc`` companion so the treatment
reconstructs from the file alone.  Operates on per-cast Datasets (dim=time); call
after ``apply_stage2`` so the soak/deck flags are already present.

Note: config overrides are trusted, not validated — a suspect range set wider
than its fail range is accepted as given (ioos_qc would reject it).
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from ctdcast.processors.history import append_history

#: QARTOD primary flag values (IOOS QARTOD).  The complete vocabulary — every
#: value and its meaning — is encoded in :func:`_qc_attrs`; these name the two
#: flags the ctdcast pipeline sets, so the code that writes a flag, the code that
#: masks on it, and the vocabulary that gives it meaning share one definition.
QARTOD_SUSPECT = np.int8(3)
QARTOD_FAIL = np.int8(4)

# QC threshold defaults.  Every test has two tiers: SUSPECT (flag 3,
# oceanographically implausible) and FAIL (flag 4, instrument malfunction).
# Conductivity is stored in mS/cm (stage 1 converts from S/m).  Per-cruise
# overrides go in config.yaml under processing.qc.{gross_range,spike} as
# {suspect: {<var>: ...}, fail: {<var>: ...}}.  A variable may define one tier or
# both; the report shows the tiers actually applied.


#: The on-disk variable names each physical family maps to (canonical + legacy).
_VARIANTS: dict[str, tuple[str, ...]] = {
    "temperature": (
        "ctd_temperature",
        "ctd_temperature_1",
        "ctd_temperature_2",
        "temperature_1",
        "temperature_2",
    ),
    "salinity": (
        "ctd_salinity",
        "ctd_salinity_1",
        "ctd_salinity_2",
        "salinity_1",
        "salinity_2",
    ),
    "conductivity": ("conductivity_1", "conductivity_2"),
    "pressure": ("pressure",),
    "oxygen": ("ctd_oxygen", "ctd_oxygen_1", "ctd_oxygen_2", "oxygen_1"),
    "fluor": ("ctd_fluor", "fluorescence"),
    "turbidity": ("ctd_turbidity", "turbidity"),
    "oxygen_saturation": ("oxygen_saturation", "oxsat_1"),
}


def _by_variant(spec: dict[str, object]) -> dict[str, object]:
    """Expand a per-family spec into one entry per on-disk variable name."""
    return {name: value for fam, value in spec.items() for name in _VARIANTS[fam]}


#: Gross-range SUSPECT bounds (flag 3): outside is oceanographically implausible.
GROSS_RANGE_SUSPECT: dict[str, tuple[float, float]] = _by_variant(
    {
        "temperature": (-2.0, 35.0),
        "salinity": (2.0, 40.0),
        "conductivity": (0.0, 65.0),
        "pressure": (-0.5, 7000.0),
    }
)

#: Gross-range FAIL bounds (flag 4): outside is instrument malfunction.
GROSS_RANGE_FAIL: dict[str, tuple[float, float]] = _by_variant(
    {
        "temperature": (-2.5, 40.0),
        "salinity": (0.0, 40.0),
        "conductivity": (0.0, 75.0),
        "pressure": (-5.0, 7000.0),
        "oxygen": (0.0, 450.0),
        "fluor": (0.0, 50.0),
        "turbidity": (0.0, 50.0),
        "oxygen_saturation": (0.0, 200.0),
    }
)

#: Spike SUSPECT thresholds (flag 3) on ``|v[i] - (v[i-1]+v[i+1])/2|``, in the
#: variable's units.  Fluorescence and turbidity are excluded — natural
#: fine-scale variability, not instrument spikes.
SPIKE_SUSPECT: dict[str, float] = _by_variant(
    {
        "temperature": 2.0,
        "salinity": 1.0,
        "conductivity": 2.0,
        "pressure": 10.0,
        "oxygen": 20.0,
    }
)

#: Spike FAIL thresholds (flag 4).  Oxygen has no fail default yet (suspect only).
SPIKE_FAIL: dict[str, float] = _by_variant(
    {
        "temperature": 6.0,
        "salinity": 2.0,
        "conductivity": 5.0,
        "pressure": 50.0,
    }
)


def _ensure_qc(ds: xr.Dataset, var: str) -> str:
    """Create the ``{var}_qc`` companion and mark missing (flag 9) where data is NaN.

    A non-finite sample cannot be evaluated by any value test, so it is *missing*
    (flag 9), not *pass* (flag 1).  Without this a half-NaN variable would read
    100% pass, and a downstream "keep flag 1" filter would admit missing data.
    Only pass positions are re-marked, so a soak/deck fail on a NaN sample is
    preserved.  Returns the companion's name.
    """
    qc_name = f"{var}_qc"
    finite = np.isfinite(ds[var].values.astype(float))
    if qc_name not in ds:
        dim = ds[var].dims[0]
        qc = np.where(finite, 1, 9).astype(np.int8)
        ds[qc_name] = xr.DataArray(
            qc, dims=[dim], attrs=_qc_attrs(var, ds[var].attrs.get("standard_name"))
        )
    else:
        qc = ds[qc_name].values.copy()
        qc[~finite & (qc == 1)] = np.int8(9)
        ds[qc_name] = xr.DataArray(qc, dims=ds[qc_name].dims, attrs=ds[qc_name].attrs)
    return qc_name


def _raise_flag(qc: np.ndarray, mask: np.ndarray, flag: np.int8) -> None:
    """Set *flag* where *mask* holds and it raises (never lowers) the existing flag.

    Because the flag values order 1 < 2 < 3 < 4 < 9, ``qc < flag`` leaves a
    more-severe flag and ``missing`` (9) untouched: a fail (4) is never downgraded
    by a later suspect (3), and a soak/deck fail survives a gross-range or spike
    suspect.
    """
    qc[mask & (qc < flag)] = flag


def _split_tiers(defaults: dict, overrides: dict | None) -> tuple[dict, dict]:
    """Return ``(suspect, fail)`` dicts, merging config overrides over *defaults*.

    *defaults* is a ``(suspect_map, fail_map)`` pair; *overrides* (from config) may
    carry ``suspect`` and/or ``fail`` sub-dicts keyed by variable.
    """
    suspect = {**defaults[0], **(overrides or {}).get("suspect", {})}
    fail = {**defaults[1], **(overrides or {}).get("fail", {})}
    return suspect, fail


def apply_gross_range(
    ds: xr.Dataset,
    thresholds: dict | None = None,
) -> xr.Dataset:
    """Two-tier gross-range QC: flag 3 outside suspect bounds, flag 4 outside fail.

    Creates ``{var}_qc`` companions (int8, 1=pass) as needed, sets suspect (3) then
    fail (4) so the wider fail bound wins, and records the applied bounds
    (``qc_gross_range_{suspect,fail}_{min,max}``) on each companion so the report
    reads them back.  A more-severe flag is never downgraded.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time); input is not mutated.
    thresholds:
        Config overrides with ``suspect`` and/or ``fail`` sub-dicts of
        ``{var: (min, max)}``, merged over
        :data:`GROSS_RANGE_SUSPECT` / :data:`GROSS_RANGE_FAIL`.

    Returns
    -------
    xr.Dataset
        New Dataset with the flags and threshold attributes.
    """
    ds = ds.copy()
    suspect, fail = _split_tiers((GROSS_RANGE_SUSPECT, GROSS_RANGE_FAIL), thresholds)
    applied: list[str] = []
    for var in sorted(set(suspect) | set(fail)):
        if var not in ds:
            continue
        qc_name = _ensure_qc(ds, var)
        qc = ds[qc_name].values.copy()
        vals = ds[var].values.astype(float)
        finite = ~np.isnan(vals)
        attrs = dict(ds[qc_name].attrs)
        s = suspect.get(var)
        f = fail.get(var)
        if s is not None:
            _raise_flag(qc, finite & ((vals < s[0]) | (vals > s[1])), QARTOD_SUSPECT)
            attrs["qc_gross_range_suspect_min"] = float(s[0])
            attrs["qc_gross_range_suspect_max"] = float(s[1])
        if f is not None:
            _raise_flag(qc, finite & ((vals < f[0]) | (vals > f[1])), QARTOD_FAIL)
            attrs["qc_gross_range_fail_min"] = float(f[0])
            attrs["qc_gross_range_fail_max"] = float(f[1])
        ds[qc_name] = xr.DataArray(qc, dims=ds[qc_name].dims, attrs=attrs)
        applied.append(var)
    if applied:
        append_history(ds.attrs, f"gross_range: {', '.join(applied)}", stage="stage3")
    return ds


def apply_spike_test(
    ds: xr.Dataset,
    thresholds: dict | None = None,
) -> xr.Dataset:
    """Two-tier QARTOD spike test: flag 3 above the suspect threshold, flag 4 above fail.

    The spike metric for an interior sample is ``|v[i] - (v[i-1] + v[i+1]) / 2|``;
    endpoints are not evaluated.  Records the thresholds
    (``qc_spike_{suspect,fail}_threshold``) on each ``{var}_qc``.  Fluorescence and
    turbidity have no spike test (natural fine-scale variability).  A more-severe
    flag is never downgraded.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time); input is not mutated.
    thresholds:
        Config overrides with ``suspect`` and/or ``fail`` sub-dicts of
        ``{var: threshold}``, merged over :data:`SPIKE_SUSPECT` / :data:`SPIKE_FAIL`.

    Returns
    -------
    xr.Dataset
        New Dataset with the flags and threshold attributes.
    """
    ds = ds.copy()
    suspect, fail = _split_tiers((SPIKE_SUSPECT, SPIKE_FAIL), thresholds)
    applied: list[str] = []
    for var in sorted(set(suspect) | set(fail)):
        if var not in ds:
            continue
        vals = ds[var].values.astype(float)
        if vals.ndim != 1 or vals.size < 3:
            continue
        spike = np.full(vals.shape, np.nan)
        spike[1:-1] = np.abs(vals[1:-1] - 0.5 * (vals[:-2] + vals[2:]))
        finite = np.isfinite(spike)
        qc_name = _ensure_qc(ds, var)
        qc = ds[qc_name].values.copy()
        attrs = dict(ds[qc_name].attrs)
        s = suspect.get(var)
        f = fail.get(var)
        if s is not None:
            _raise_flag(qc, finite & (spike > s), QARTOD_SUSPECT)
            attrs["qc_spike_suspect_threshold"] = float(s)
        if f is not None:
            _raise_flag(qc, finite & (spike > f), QARTOD_FAIL)
            attrs["qc_spike_fail_threshold"] = float(f)
        ds[qc_name] = xr.DataArray(qc, dims=ds[qc_name].dims, attrs=attrs)
        applied.append(var)
    if applied:
        append_history(ds.attrs, f"spike: {', '.join(applied)}", stage="stage3")
    return ds


def _qc_attrs(var: str, standard_name: str | None) -> dict:
    """Return CF-compliant flag attributes for a QC variable."""
    attrs: dict = {
        "long_name": f"Quality flag for {var}",
        "flag_values": np.array([1, 2, 3, 4, 9], dtype=np.int8),
        "flag_meanings": "pass not_evaluated suspect_or_of_high_interest fail missing_data",
        "valid_min": np.int8(1),
        "valid_max": np.int8(9),
        "conventions": "QARTOD",
    }
    if standard_name:
        attrs["standard_name"] = f"{standard_name} status_flag"
    return attrs
