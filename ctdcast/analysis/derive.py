"""Derived physical quantities computed from raw CTD measurements.

All functions use GSW — the same library oceanographers use directly.
Naming follows GSW conventions (SA = Absolute Salinity, CT = Conservative
Temperature, SP = Practical Salinity) so the origin of each quantity is
unambiguous.

Per-cast (1-D, dim=time) functions
------------------------------------
derive_salinity   SP from conductivity/temperature/pressure
derive_SA         Absolute Salinity from SP/pressure/lat/lon
derive_CT         Conservative Temperature from SA/in-situ-T/pressure
derive_sigma0     Potential density anomaly from SA/CT
derive_AOU        Apparent Oxygen Utilization from oxygen_1 (% sat)
derive_teos10     Convenience: SA + CT + sigma0 + optional O2 unit conversion

Profiles (2-D, dims N_PROF × pressure) functions
--------------------------------------------------
derive_teos10_profiles   SA + CT + sigma0 for compiled profiles datasets
"""

from __future__ import annotations

import warnings

import gsw
import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# SP from C/T/P
# ---------------------------------------------------------------------------


def derive_salinity(ds: xr.Dataset) -> xr.Dataset:
    """Re-compute practical salinity from conductivity, temperature, pressure.

    Uses ``gsw.SP_from_C`` with conductivity in mS/cm (seasenselib stores in
    S/m; conversion: ``C_mS_cm = conductivity_1 * 10``).  Call this after any
    conductivity calibration so that ``salinity_1`` (and ``salinity_2`` if
    ``conductivity_2`` is present) reflects the calibrated conductivity.

    Does nothing if ``conductivity_1`` or ``temperature_1`` are absent.
    Records the conversion method in ``salinity_1.attrs``.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) containing at minimum ``conductivity_1``,
        ``temperature_1``, and ``pressure`` in their expected units
        (conductivity in S/m, temperature in °C ITS-90, pressure in dbar).

    Returns
    -------
    xr.Dataset
        New Dataset with updated ``salinity_1`` (and ``salinity_2`` when
        ``conductivity_2`` is present); input is not mutated.
    """
    if "conductivity_1" not in ds or "temperature_1" not in ds:
        return ds

    ds = ds.copy()
    p = ds["pressure"].values.astype(float)
    t = ds["temperature_1"].values.astype(float)

    for c_var, s_var in [
        ("conductivity_1", "salinity_1"),
        ("conductivity_2", "salinity_2"),
    ]:
        if c_var not in ds:
            continue
        c_s_per_m = ds[c_var].values.astype(float)
        c_ms_cm = c_s_per_m * 10.0  # S/m → mS/cm for gsw.SP_from_C
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            sp = gsw.SP_from_C(c_ms_cm, t, p)

        existing_attrs = dict(ds[s_var].attrs) if s_var in ds else {}
        existing_attrs["derived_from"] = (
            f"{c_var}, temperature_1, pressure via gsw.SP_from_C"
        )
        existing_attrs.setdefault("units", "1")
        existing_attrs.setdefault("standard_name", "sea_water_practical_salinity")
        existing_attrs.setdefault("reference_scale", "PSS-78")
        dim = ds["pressure"].dims[0]
        ds[s_var] = xr.DataArray(
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

    Uses ``gsw.SA_from_SP`` with ``salinity_1`` (practical salinity, PSS-78),
    ``pressure`` (dbar), and the cast's median latitude/longitude.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with ``salinity_1``, ``pressure``,
        ``latitude``, ``longitude``.

    Returns
    -------
    xr.Dataset
        New Dataset with ``ds["SA"]`` added; input is not mutated.
    """
    ds = ds.copy()
    sp = ds["salinity_1"].values.astype(float)
    p = ds["pressure"].values.astype(float)
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sa = gsw.SA_from_SP(sp, p, lon, lat)
    dim = ds["pressure"].dims[0]
    ds["SA"] = xr.DataArray(
        sa.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Absolute Salinity", "units": "g kg-1"},
    )
    return ds


def derive_CT(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with Conservative Temperature (CT) added.

    Requires ``ds["SA"]`` to already be present (call :func:`derive_SA` first).
    Uses ``gsw.CT_from_t`` with in-situ ``temperature_1`` and ``pressure``.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with ``SA``, ``temperature_1``,
        ``pressure``.

    Returns
    -------
    xr.Dataset
        New Dataset with ``ds["CT"]`` added; input is not mutated.
    """
    ds = ds.copy()
    sa = ds["SA"].values.astype(float)
    t = ds["temperature_1"].values.astype(float)
    p = ds["pressure"].values.astype(float)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        ct = gsw.CT_from_t(sa, t, p)
    dim = ds["pressure"].dims[0]
    ds["CT"] = xr.DataArray(
        ct.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Conservative Temperature", "units": "degC"},
    )
    return ds


def derive_sigma0(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with potential density anomaly (sigma0) added.

    Requires ``ds["SA"]`` and ``ds["CT"]`` to already be present.
    Uses ``gsw.sigma0``.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with ``SA`` and ``CT``.

    Returns
    -------
    xr.Dataset
        New Dataset with ``ds["sigma0"]`` added; input is not mutated.
    """
    ds = ds.copy()
    sa = ds["SA"].values.astype(float)
    ct = ds["CT"].values.astype(float)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sig0 = gsw.sigma0(sa, ct)
    dim = ds["SA"].dims[0]
    ds["sigma0"] = xr.DataArray(
        sig0.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Potential density anomaly", "units": "kg m-3"},
    )
    return ds


def derive_teos10(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with SA, CT, sigma0 added (1-D per-cast Dataset, dim=time).

    Convenience function that calls :func:`derive_SA` → :func:`derive_CT` →
    :func:`derive_sigma0` in order.  Also converts ``oxygen_1`` from µmol/L
    or µmol/kg to % saturation when the variable's ``units`` attribute
    indicates a molar concentration.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with ``salinity_1``, ``temperature_1``,
        ``pressure``, ``latitude``, ``longitude``.

    Returns
    -------
    xr.Dataset
        New Dataset with SA, CT, sigma0 added; input is not mutated.
    """
    ds = derive_SA(ds)
    ds = derive_CT(ds)
    ds = derive_sigma0(ds)
    if "oxygen_1" in ds:
        sa = ds["SA"].values.astype(float)
        ct = ds["CT"].values.astype(float)
        p = ds["pressure"].values.astype(float)
        lat = float(np.nanmedian(ds["latitude"].values))
        lon = float(np.nanmedian(ds["longitude"].values))
        ds = _convert_oxygen_to_pct_sat(ds, sa, ct, p, lat, lon)
    return ds


# ---------------------------------------------------------------------------
# TEOS-10 profiles (2-D, dims N_PROF × pressure)
# ---------------------------------------------------------------------------


def derive_teos10_profiles(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with SA, CT, sigma0 added (2-D profiles Dataset).

    Expects ``pressure`` as a 1-D coordinate and ``temperature_1``,
    ``salinity_1``, ``latitude``, ``longitude`` as variables with dims
    ``(N_PROF,)`` or ``(N_PROF, pressure)``.  Returns *ds* unchanged if
    SA, CT, and sigma0 are already present.

    Parameters
    ----------
    ds:
        Profiles Dataset (dims N_PROF × pressure).

    Returns
    -------
    xr.Dataset
        New Dataset with SA, CT, sigma0 added; input is not mutated.
    """
    if "CT" in ds and "SA" in ds and "sigma0" in ds:
        return ds
    ds = ds.copy()
    p = ds["pressure"].values.astype(float)  # (N_P,)
    t = ds["temperature_1"].values.astype(float)  # (N_PROF, N_P)
    sp = ds["salinity_1"].values.astype(float)  # (N_PROF, N_P)
    lat = ds["latitude"].values.astype(float)  # (N_PROF,)
    lon = ds["longitude"].values.astype(float)  # (N_PROF,)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sa = gsw.SA_from_SP(
            sp, p[np.newaxis, :], lon[:, np.newaxis], lat[:, np.newaxis]
        )
        ct = gsw.CT_from_t(sa, t, p[np.newaxis, :])
        sig0 = gsw.sigma0(sa, ct)
    dims = tuple(ds["temperature_1"].dims)
    ds["SA"] = xr.DataArray(
        sa.astype(np.float32),
        dims=dims,
        attrs={"long_name": "Absolute Salinity", "units": "g kg-1"},
    )
    ds["CT"] = xr.DataArray(
        ct.astype(np.float32),
        dims=dims,
        attrs={"long_name": "Conservative Temperature", "units": "degC"},
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
    """Return *ds* with AOU added as 100 - oxygen_1 (O₂ saturation deficit, % sat).

    Note: this is a saturation-deficit proxy, not the traditional AOU in
    µmol/kg, because the input data contains oxygen_1 in % saturation.
    When dissolved O₂ in µmol/kg becomes available, replace with
    ``gsw.O2sol(SA, CT, p, lon, lat) - O2_measured``.

    Returns *ds* unchanged if ``oxygen_1`` is absent or ``AOU`` already exists.

    Parameters
    ----------
    ds:
        Dataset (any dimensionality) with ``oxygen_1`` in % saturation.

    Returns
    -------
    xr.Dataset
        New Dataset with ``AOU`` added; input is not mutated.
    """
    if "AOU" in ds or "oxygen_1" not in ds:
        return ds
    ds = ds.copy()
    dims = ds["oxygen_1"].dims
    ds["AOU"] = xr.DataArray(
        (100.0 - ds["oxygen_1"].values).astype(np.float32),
        dims=dims,
        attrs={"long_name": "O₂ saturation deficit", "units": "% sat"},
    )
    return ds


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


def _convert_oxygen_to_pct_sat(
    ds: xr.Dataset,
    sa: np.ndarray,
    ct: np.ndarray,
    p: np.ndarray,
    lat: float,
    lon: float,
) -> xr.Dataset:
    """Convert ``oxygen_1`` from µmol/L or µmol/kg to % saturation.

    Does nothing if ``oxygen_1`` units already indicate % saturation or if the
    units attribute is absent.  Records the original units and the conversion
    method in ``oxygen_1`` attributes for provenance.

    Parameters
    ----------
    ds:
        Dataset containing ``oxygen_1``; must already have SA/CT computed.
    sa, ct, p:
        Absolute Salinity (g/kg), Conservative Temperature (°C), pressure (dbar)
        arrays matching the ``oxygen_1`` dimension.
    lat, lon:
        Representative cast latitude and longitude for ``gsw.O2sol``.
    """
    units = ds["oxygen_1"].attrs.get("units", "")
    if not units:
        return ds
    u_lower = units.lower()
    if "umol" not in u_lower and "µmol" not in u_lower:
        return ds

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        o2_sat_umol_kg = gsw.O2sol(sa, ct, p, lat, lon)

    measured = ds["oxygen_1"].values.astype(float)

    if "/l" in u_lower or "l-1" in u_lower:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            rho = gsw.rho(sa, ct, p)  # kg/m³
        o2_sat_umol_l = o2_sat_umol_kg * rho / 1000.0
        pct_sat = measured / o2_sat_umol_l * 100.0
        method = f"converted from {units} via gsw.O2sol + gsw.rho"
    else:
        pct_sat = measured / o2_sat_umol_kg * 100.0
        method = f"converted from {units} via gsw.O2sol"

    warnings.warn(
        f"oxygen_1: {method}; values overwritten in-place.",
        stacklevel=3,
    )
    new_attrs = dict(ds["oxygen_1"].attrs)
    new_attrs["units"] = "% saturation"
    new_attrs["original_units"] = units
    new_attrs["oxygen_conversion"] = method
    dim = ds["oxygen_1"].dims[0]
    ds["oxygen_1"] = xr.DataArray(
        pct_sat.astype(np.float32),
        dims=[dim],
        attrs=new_attrs,
    )
    return ds
