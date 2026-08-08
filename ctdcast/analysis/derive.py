"""Derived physical quantities computed from raw CTD measurements.

All functions use GSW — the same library oceanographers use directly.

Per-cast (1-D, dim=time) functions
------------------------------------
derive_salinity   SP from conductivity/temperature/pressure
derive_SA         Absolute Salinity from SP/pressure/lat/lon
derive_CT         Conservative Temperature from SA/in-situ-T/pressure
derive_sigma0     Potential density anomaly from SA/CT
derive_AOU        Apparent Oxygen Utilization from oxygen_saturation (% sat)
derive_teos10     Convenience: SA + CT + sigma0 + optional O2 unit conversion

Profiles (2-D, dims N_PROF × pressure) functions
--------------------------------------------------
derive_teos10_profiles   SA + CT + sigma0 for compiled profiles datasets

Output variable names match the VARIABLES registry in
``ctdcast.config.parameters``: ``absolute_salinity``,
``conservative_temperature``, ``sigma0``.

Variable resolution
-------------------
Functions accept both the canonical CCHDO names (``ctd_temperature``,
``ctd_salinity``, ``ctd_oxygen``) and the suffixed dual-sensor names
(``ctd_temperature_1``, ``ctd_salinity_1``, ``ctd_oxygen_1``).  Old
pre-rename names (``temperature_1``, ``salinity_1``, ``oxygen_1``)
are accepted for backward compatibility with NC files written before
the stage1-normalise rename.
"""

from __future__ import annotations

import warnings

import gsw
import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# Variable-resolution helpers
# ---------------------------------------------------------------------------

#: Preferred order for temperature: plain (single-sensor or stage3-promoted),
#: then primary suffix, then secondary suffix, then old pre-rename name.
_TEMP_CANDIDATES = ("ctd_temperature", "ctd_temperature_1", "temperature_1")
_SAL_CANDIDATES = ("ctd_salinity", "ctd_salinity_1", "salinity_1")
_OXY_CANDIDATES = ("ctd_oxygen", "ctd_oxygen_1", "oxygen_1")
_OXSAT_CANDIDATES = ("oxygen_saturation", "oxsat_1")


def _resolve_var(ds: xr.Dataset, *candidates: str) -> str | None:
    """Return the first variable name in *candidates* present in *ds*, else None."""
    for name in candidates:
        if name in ds:
            return name
    return None


# ---------------------------------------------------------------------------
# SP from C/T/P
# ---------------------------------------------------------------------------


def derive_salinity(ds: xr.Dataset) -> xr.Dataset:
    """Re-compute practical salinity from conductivity, temperature, pressure.

    Uses ``gsw.SP_from_C`` with conductivity in mS/cm (stored in S/m;
    conversion: ``C_mS_cm = conductivity_1 * 10``).  Call this after any
    conductivity calibration so that salinity reflects the calibrated conductivity.

    Does nothing if ``conductivity_1`` or any temperature variable is absent.

    Writes output to ``ctd_salinity_1`` / ``ctd_salinity_2`` (CCHDO canonical
    names).  Records the conversion method in the variable's attrs.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) containing at minimum ``conductivity_1``,
        a temperature variable, and ``pressure`` in their expected units
        (conductivity in S/m, temperature in °C ITS-90, pressure in dbar).

    Returns
    -------
    xr.Dataset
        New Dataset with updated ``ctd_salinity_1`` (and ``ctd_salinity_2`` when
        ``conductivity_2`` is present); input is not mutated.
    """
    temp_var = _resolve_var(ds, *_TEMP_CANDIDATES)
    if "conductivity_1" not in ds or temp_var is None:
        return ds

    ds = ds.copy()
    p = ds["pressure"].values.astype(float)
    t = ds[temp_var].values.astype(float)

    # On single-sensor casts _normalise promotes ctd_salinity_1 → ctd_salinity;
    # write to whichever name is live in ds so the promoted plain name is kept current.
    _sal1_out = _resolve_var(ds, "ctd_salinity", "ctd_salinity_1") or "ctd_salinity_1"
    pairs = [
        ("conductivity_1", _sal1_out),
        ("conductivity_2", "ctd_salinity_2"),
    ]
    for c_var, s_out in pairs:
        if c_var not in ds:
            continue
        c_s_per_m = ds[c_var].values.astype(float)
        c_ms_cm = c_s_per_m * 10.0  # S/m → mS/cm for gsw.SP_from_C
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            sp = gsw.SP_from_C(c_ms_cm, t, p)

        existing_attrs = dict(ds[s_out].attrs) if s_out in ds else {}
        existing_attrs["derived_from"] = (
            f"{c_var}, {temp_var}, pressure via gsw.SP_from_C"
        )
        existing_attrs.setdefault("units", "1")
        existing_attrs.setdefault("standard_name", "sea_water_practical_salinity")
        existing_attrs.setdefault("reference_scale", "PSS-78")
        dim = ds["pressure"].dims[0]
        ds[s_out] = xr.DataArray(
            sp.astype(np.float32),
            dims=[dim],
            attrs=existing_attrs,
        )

    return ds


# ---------------------------------------------------------------------------
# TEOS-10 per-cast (1-D)
# ---------------------------------------------------------------------------


def derive_SA(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with Absolute Salinity (SA) added.

    Uses ``gsw.SA_from_SP`` with the first available salinity variable
    (``ctd_salinity``, ``ctd_salinity_1``, or ``salinity_1``), ``pressure``
    (dbar), and the cast's median latitude/longitude.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with a salinity variable, ``pressure``,
        ``latitude``, ``longitude``.

    Returns
    -------
    xr.Dataset
        New Dataset with ``ds["absolute_salinity"]`` added; input is not mutated.
    """
    sal_var = _resolve_var(ds, *_SAL_CANDIDATES)
    if sal_var is None:
        return ds
    ds = ds.copy()
    sp = ds[sal_var].values.astype(float)
    p = ds["pressure"].values.astype(float)
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sa = gsw.SA_from_SP(sp, p, lon, lat)
    dim = ds["pressure"].dims[0]
    ds["absolute_salinity"] = xr.DataArray(
        sa.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Absolute Salinity", "units": "g kg-1"},
    )
    return ds


def derive_CT(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with Conservative Temperature (CT) added.

    Requires ``ds["absolute_salinity"]`` to already be present (call
    :func:`derive_SA` first).  Uses ``gsw.CT_from_t`` with the first available
    temperature variable (``ctd_temperature``, ``ctd_temperature_1``, or
    ``temperature_1``) and ``pressure``.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with ``absolute_salinity``, a temperature
        variable, and ``pressure``.

    Returns
    -------
    xr.Dataset
        New Dataset with ``ds["conservative_temperature"]`` added; input is not mutated.
    """
    temp_var = _resolve_var(ds, *_TEMP_CANDIDATES)
    if temp_var is None:
        return ds
    if "absolute_salinity" not in ds:
        return ds
    ds = ds.copy()
    sa = ds["absolute_salinity"].values.astype(float)
    t = ds[temp_var].values.astype(float)
    p = ds["pressure"].values.astype(float)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        ct = gsw.CT_from_t(sa, t, p)
    dim = ds["pressure"].dims[0]
    ds["conservative_temperature"] = xr.DataArray(
        ct.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Conservative Temperature", "units": "degree_Celsius"},
    )
    return ds


def derive_sigma0(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with potential density anomaly (sigma0) added.

    Requires ``ds["absolute_salinity"]`` and ``ds["conservative_temperature"]`` to already be present.
    Uses ``gsw.sigma0``.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with ``absolute_salinity`` and ``conservative_temperature``.

    Returns
    -------
    xr.Dataset
        New Dataset with ``ds["sigma0"]`` added; input is not mutated.
    """
    ds = ds.copy()
    sa = ds["absolute_salinity"].values.astype(float)
    ct = ds["conservative_temperature"].values.astype(float)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sig0 = gsw.sigma0(sa, ct)
    dim = ds["absolute_salinity"].dims[0]
    ds["sigma0"] = xr.DataArray(
        sig0.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Potential density anomaly", "units": "kg m-3"},
    )
    return ds


def derive_teos10(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with SA, CT, sigma0 added (1-D per-cast Dataset, dim=time).

    Convenience function that calls :func:`derive_SA` → :func:`derive_CT` →
    :func:`derive_sigma0` in order.  Also derives ``oxygen_saturation`` (% sat)
    from the first available oxygen variable (``ctd_oxygen``, ``ctd_oxygen_1``,
    or ``oxygen_1``) when that variable carries molar units.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with a salinity variable, a temperature
        variable, ``pressure``, ``latitude``, ``longitude``.

    Returns
    -------
    xr.Dataset
        New Dataset with SA, CT, sigma0 added; input is not mutated.
    """
    ds = derive_SA(ds)
    ds = derive_CT(ds)
    ds = derive_sigma0(ds)
    oxy_var = _resolve_var(ds, *_OXY_CANDIDATES)
    if oxy_var is not None:
        units = ds[oxy_var].attrs.get("units", "")
        u_lower = units.lower()
        if "umol" in u_lower or "µmol" in u_lower:
            sa = ds["absolute_salinity"].values.astype(float)
            ct = ds["conservative_temperature"].values.astype(float)
            p = ds["pressure"].values.astype(float)
            lat = float(np.nanmedian(ds["latitude"].values))
            lon = float(np.nanmedian(ds["longitude"].values))
            ds = _derive_oxsat_from_oxygen(ds, oxy_var, sa, ct, p, lat, lon)
        elif "%" in u_lower or "sat" in u_lower or "percent" in u_lower:
            # Pre-rename NC files stored % saturation under "oxygen_1".
            # Rename to the canonical oxygen_saturation name.
            if oxy_var != "oxygen_saturation":
                ds = ds.rename({oxy_var: "oxygen_saturation"})
        else:
            warnings.warn(
                f"{oxy_var!r} has unrecognised units {units!r}; "
                "oxygen_saturation not derived. "
                "Expected 'umol', 'µmol', '%', 'sat', or 'percent'.",
                UserWarning,
                stacklevel=4,
            )
    return ds


# ---------------------------------------------------------------------------
# TEOS-10 profiles (2-D, dims N_PROF × pressure)
# ---------------------------------------------------------------------------


def derive_teos10_profiles(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with SA, CT, sigma0 added (2-D profiles Dataset).

    Expects ``pressure`` as a 1-D coordinate and a temperature variable,
    a salinity variable, ``latitude``, ``longitude`` with dims ``(N_PROF,)``
    or ``(N_PROF, pressure)``.  Returns *ds* unchanged if SA, CT, and sigma0
    are already present.

    Parameters
    ----------
    ds:
        Profiles Dataset (dims N_PROF × pressure).

    Returns
    -------
    xr.Dataset
        New Dataset with SA, CT, sigma0 added; input is not mutated.
    """
    if (
        "conservative_temperature" in ds
        and "absolute_salinity" in ds
        and "sigma0" in ds
    ):
        return ds
    temp_var = _resolve_var(ds, *_TEMP_CANDIDATES)
    sal_var = _resolve_var(ds, *_SAL_CANDIDATES)
    if temp_var is None or sal_var is None:
        return ds
    ds = ds.copy()
    p = ds["pressure"].values.astype(float)  # (N_P,)
    t = ds[temp_var].values.astype(float)  # (N_PROF, N_P)
    sp = ds[sal_var].values.astype(float)  # (N_PROF, N_P)
    lat = ds["latitude"].values.astype(float)  # (N_PROF,)
    lon = ds["longitude"].values.astype(float)  # (N_PROF,)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sa = gsw.SA_from_SP(
            sp, p[np.newaxis, :], lon[:, np.newaxis], lat[:, np.newaxis]
        )
        ct = gsw.CT_from_t(sa, t, p[np.newaxis, :])
        sig0 = gsw.sigma0(sa, ct)
    dims = tuple(ds[temp_var].dims)
    ds["absolute_salinity"] = xr.DataArray(
        sa.astype(np.float32),
        dims=dims,
        attrs={"long_name": "Absolute Salinity", "units": "g kg-1"},
    )
    ds["conservative_temperature"] = xr.DataArray(
        ct.astype(np.float32),
        dims=dims,
        attrs={"long_name": "Conservative Temperature", "units": "degree_Celsius"},
    )
    ds["sigma0"] = xr.DataArray(
        sig0.astype(np.float32),
        dims=dims,
        attrs={"long_name": "Potential density anomaly", "units": "kg m-3"},
    )
    return ds


# ---------------------------------------------------------------------------
# AOU
# ---------------------------------------------------------------------------


def derive_AOU(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with AOU added as 100 - oxygen_saturation (O₂ saturation deficit, % sat).

    Note: this is a saturation-deficit proxy, not the traditional AOU in
    µmol/kg, because it uses ``oxygen_saturation`` (% saturation) rather than
    dissolved O₂ in µmol/kg.

    Returns *ds* unchanged if no oxygen saturation variable is present or
    ``AOU`` already exists.  Accepts ``oxygen_saturation`` (canonical) or
    ``oxsat_1`` (pre-rename name).

    Parameters
    ----------
    ds:
        Dataset (any dimensionality) with ``oxygen_saturation`` or ``oxsat_1``
        in % saturation.

    Returns
    -------
    xr.Dataset
        New Dataset with ``AOU`` added; input is not mutated.
    """
    oxsat_var = _resolve_var(ds, *_OXSAT_CANDIDATES)
    if "AOU" in ds or oxsat_var is None:
        return ds
    ds = ds.copy()
    dims = ds[oxsat_var].dims
    ds["AOU"] = xr.DataArray(
        (100.0 - ds[oxsat_var].values).astype(np.float32),
        dims=dims,
        attrs={"long_name": "O₂ saturation deficit", "units": "% sat"},
    )
    return ds


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


def _derive_oxsat_from_oxygen(
    ds: xr.Dataset,
    oxy_var: str,
    sa: np.ndarray,
    ct: np.ndarray,
    p: np.ndarray,
    lat: float,
    lon: float,
) -> xr.Dataset:
    """Derive ``oxygen_saturation`` (% sat) from an oxygen variable in molar units.

    Adds ``oxygen_saturation`` to *ds*; leaves *oxy_var* unchanged.  Does
    nothing if *oxy_var* units do not indicate a molar concentration.  Records
    the conversion method in ``oxygen_saturation`` attributes for provenance.

    Parameters
    ----------
    ds:
        Dataset containing *oxy_var* in molar units; must already have SA/CT
        computed (i.e. call after :func:`derive_SA` / :func:`derive_CT`).
    oxy_var:
        Name of the oxygen variable in molar units (e.g. ``"ctd_oxygen"``).
    sa, ct, p:
        Absolute Salinity (g/kg), Conservative Temperature (°C), pressure (dbar)
        arrays matching the *oxy_var* dimension.
    lat, lon:
        Representative cast latitude and longitude for ``gsw.O2sol``.
    """
    units = ds[oxy_var].attrs.get("units", "")
    if not units:
        return ds
    u_lower = units.lower()
    if "umol" not in u_lower and "µmol" not in u_lower:
        return ds

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        o2_sat_umol_kg = gsw.O2sol(sa, ct, p, lat, lon)

    measured = ds[oxy_var].values.astype(float)

    if "/l" in u_lower or "l-1" in u_lower:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            rho = gsw.rho(sa, ct, p)  # kg/m³
        o2_sat_umol_l = o2_sat_umol_kg * rho / 1000.0
        pct_sat = measured / o2_sat_umol_l * 100.0
        method = f"derived from {oxy_var} ({units}) via gsw.O2sol + gsw.rho"
    else:
        pct_sat = measured / o2_sat_umol_kg * 100.0
        method = f"derived from {oxy_var} ({units}) via gsw.O2sol"

    new_attrs = {
        "units": "% saturation",
        "long_name": "O₂ saturation",
        "source_units": units,
        "oxygen_conversion": method,
    }
    dim = ds[oxy_var].dims[0]
    ds = ds.copy()
    ds["oxygen_saturation"] = xr.DataArray(
        pct_sat.astype(np.float32),
        dims=[dim],
        attrs=new_attrs,
    )
    return ds
