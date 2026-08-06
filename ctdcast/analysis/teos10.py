"""TEOS-10 derived quantities: CT, SA, sigma0, AOU, and oxygen conversion.

Pure computation — no matplotlib, no HTML.  All conversions use GSW; never the
linear density or depth approximations.
"""

from __future__ import annotations

import warnings

import gsw
import numpy as np
import xarray as xr


def add_teos10(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with CT, SA, sigma0 added (1-D per-cast Dataset, dim=time).

    Also converts ``oxygen_1`` from µmol/L or µmol/kg to % saturation when the
    variable's ``units`` attribute indicates a molar concentration.  The
    conversion uses ``gsw.O2sol`` and the cast's in-situ SA/CT/p/lat/lon, so
    TEOS-10 variables are always computed first even when they already exist.
    """
    ds = ds.copy()
    p = ds["pressure"].values.astype(float)
    t = ds["temperature_1"].values.astype(float)
    sp = ds["salinity_1"].values.astype(float)
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    # gsw warns on NaN / out-of-range inputs (common in raw CTD data before
    # QC).  The computation returns NaN where invalid, which is correct behaviour.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sa = gsw.SA_from_SP(sp, p, lon, lat)
        ct = gsw.CT_from_t(sa, t, p)
        sig0 = gsw.sigma0(sa, ct)
    dim = ds["pressure"].dims[0]
    ds["SA"] = xr.DataArray(
        sa.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Absolute Salinity", "units": "g kg-1"},
    )
    ds["CT"] = xr.DataArray(
        ct.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Conservative Temperature", "units": "degC"},
    )
    ds["sigma0"] = xr.DataArray(
        sig0.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Potential density anomaly", "units": "kg m-3"},
    )
    if "oxygen_1" in ds:
        ds = _convert_oxygen_to_pct_sat(ds, sa, ct, p, lat, lon)
    return ds


def _convert_oxygen_to_pct_sat(
    ds: xr.Dataset,
    sa: np.ndarray,
    ct: np.ndarray,
    p: np.ndarray,
    lat: float,
    lon: float,
) -> xr.Dataset:
    """Convert ``oxygen_1`` from µmol/L or µmol/kg to % saturation in-place.

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
        # O2 saturation in µmol/kg at in-situ T, S, p.
        o2_sat_umol_kg = gsw.O2sol(sa, ct, p, lat, lon)

    measured = ds["oxygen_1"].values.astype(float)

    if "/l" in u_lower or "l-1" in u_lower:
        # µmol/L → µmol/kg requires density (kg/m³ → g/mL = kg/L).
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            rho = gsw.rho(sa, ct, p)  # kg/m³
        o2_sat_umol_l = o2_sat_umol_kg * rho / 1000.0
        pct_sat = measured / o2_sat_umol_l * 100.0
        method = f"converted from {units} via gsw.O2sol + gsw.rho"
    else:
        # Assume µmol/kg.
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


def add_teos10_profiles(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with CT, SA, sigma0 added (2-D profiles Dataset, dims N_PROF × pressure).

    Expects pressure as a 1-D coordinate and temperature_1/salinity_1/latitude/longitude
    as variables with dims (N_PROF,) or (N_PROF, pressure).
    """
    if "CT" in ds and "SA" in ds and "sigma0" in ds:
        return ds
    ds = ds.copy()
    p = ds["pressure"].values.astype(float)  # (N_P,)
    t = ds["temperature_1"].values.astype(float)  # (N_PROF, N_P)
    sp = ds["salinity_1"].values.astype(float)  # (N_PROF, N_P)
    lat = ds["latitude"].values.astype(float)  # (N_PROF,)
    lon = ds["longitude"].values.astype(float)  # (N_PROF,)
    # Broadcast pressure along axis-1, lat/lon along axis-0
    sa = gsw.SA_from_SP(sp, p[np.newaxis, :], lon[:, np.newaxis], lat[:, np.newaxis])
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


def add_aou(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with AOU added as 100 - oxygen_1 (O₂ saturation deficit, % sat).

    Note: this is a saturation-deficit proxy, not the traditional AOU in µmol/kg,
    because the input data contains only oxygen_1 in % saturation.  When dissolved
    O₂ in µmol/kg becomes available, replace with
    ``gsw.O2sol(SA, CT, p, lon, lat) - O2_measured``.
    Returns *ds* unchanged if ``oxygen_1`` is absent or ``AOU`` already exists.
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
