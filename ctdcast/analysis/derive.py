"""Derived physical quantities computed from raw CTD measurements.

All functions use GSW — the same library oceanographers use directly.

Per-cast (1-D, dim=time) functions
------------------------------------
derive_salinity   SP from conductivity/temperature/pressure
derive_SA         Absolute Salinity from SP/pressure/lat/lon
derive_CT         Conservative Temperature from SA/in-situ-T/pressure
derive_sigma0     Potential density anomaly from SA/CT
derive_AOU        Apparent Oxygen Utilization from oxsat_1 (% sat)
derive_teos10     Convenience: SA + CT + sigma0 + optional O2 unit conversion

Profiles (2-D, dims N_PROF × pressure) functions
--------------------------------------------------
derive_teos10_profiles   SA + CT + sigma0 for compiled profiles datasets

Output variable names match the VARIABLES registry in
``ctdcast.config.parameters``: ``absolute_salinity``,
``conservative_temperature``, ``sigma0``.
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
        New Dataset with ``ds["absolute_salinity"]`` added; input is not mutated.
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
    ds["absolute_salinity"] = xr.DataArray(
        sa.astype(np.float32),
        dims=[dim],
        attrs={"long_name": "Absolute Salinity", "units": "g kg-1"},
    )
    return ds


def derive_CT(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with Conservative Temperature (CT) added.

    Requires ``ds["absolute_salinity"]`` to already be present (call :func:`derive_SA` first).
    Uses ``gsw.CT_from_t`` with in-situ ``temperature_1`` and ``pressure``.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) with ``absolute_salinity``, ``temperature_1``,
        ``pressure``.

    Returns
    -------
    xr.Dataset
        New Dataset with ``ds["conservative_temperature"]`` added; input is not mutated.
    """
    ds = ds.copy()
    sa = ds["absolute_salinity"].values.astype(float)
    t = ds["temperature_1"].values.astype(float)
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
    :func:`derive_sigma0` in order.  Also handles ``oxygen_1`` in two cases:

    - If ``oxygen_1`` carries molar units (µmol/L or µmol/kg), derives
      ``oxsat_1`` (% saturation) and adds it; ``oxygen_1`` is left unchanged.
    - If ``oxygen_1`` already carries % saturation units (pre-Phase-3 NC files
      where the variable was stored under the wrong name), renames it to
      ``oxsat_1`` so the plotting pipeline finds it under the canonical name.

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
        units = ds["oxygen_1"].attrs.get("units", "")
        u_lower = units.lower()
        if "umol" in u_lower or "µmol" in u_lower:
            sa = ds["absolute_salinity"].values.astype(float)
            ct = ds["conservative_temperature"].values.astype(float)
            p = ds["pressure"].values.astype(float)
            lat = float(np.nanmedian(ds["latitude"].values))
            lon = float(np.nanmedian(ds["longitude"].values))
            ds = _derive_oxsat_from_oxygen(ds, sa, ct, p, lat, lon)
        elif "%" in u_lower or "sat" in u_lower or "percent" in u_lower:
            # Pre-Phase-3 NC files stored % saturation under "oxygen_1".
            # Rename to the canonical "oxsat_1" so panels find it.
            ds = ds.rename({"oxygen_1": "oxsat_1"})
        else:
            import warnings

            warnings.warn(
                f"oxygen_1 has unrecognised units {units!r}; oxsat_1 not derived. "
                "Biogeo panels will be absent. Expected 'umol', 'µmol', '%', "
                "'sat', or 'percent'.",
                UserWarning,
                stacklevel=4,
            )
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
    if (
        "conservative_temperature" in ds
        and "absolute_salinity" in ds
        and "sigma0" in ds
    ):
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
    """Return *ds* with AOU added as 100 - oxsat_1 (O₂ saturation deficit, % sat).

    Note: this is a saturation-deficit proxy, not the traditional AOU in
    µmol/kg, because it uses ``oxsat_1`` (% saturation) rather than
    dissolved O₂ in µmol/kg.  When ``oxygen_1`` (µmol/kg) is available,
    the traditional AOU is ``gsw.O2sol(SA, CT, p, lon, lat) - oxygen_1``.

    Returns *ds* unchanged if ``oxsat_1`` is absent or ``AOU`` already exists.

    Parameters
    ----------
    ds:
        Dataset (any dimensionality) with ``oxsat_1`` in % saturation.

    Returns
    -------
    xr.Dataset
        New Dataset with ``AOU`` added; input is not mutated.
    """
    if "AOU" in ds or "oxsat_1" not in ds:
        return ds
    ds = ds.copy()
    dims = ds["oxsat_1"].dims
    ds["AOU"] = xr.DataArray(
        (100.0 - ds["oxsat_1"].values).astype(np.float32),
        dims=dims,
        attrs={"long_name": "O₂ saturation deficit", "units": "% sat"},
    )
    return ds


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


def _derive_oxsat_from_oxygen(
    ds: xr.Dataset,
    sa: np.ndarray,
    ct: np.ndarray,
    p: np.ndarray,
    lat: float,
    lon: float,
) -> xr.Dataset:
    """Derive ``oxsat_1`` (% saturation) from ``oxygen_1`` (µmol/L or µmol/kg).

    Adds ``oxsat_1`` to *ds*; leaves ``oxygen_1`` unchanged.  Does nothing if
    ``oxygen_1`` units do not indicate a molar concentration.  Records the
    conversion method in ``oxsat_1`` attributes for provenance.

    Parameters
    ----------
    ds:
        Dataset containing ``oxygen_1`` in molar units; must already have SA/CT
        computed (i.e. call after :func:`derive_SA` / :func:`derive_CT`).
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
        method = f"derived from oxygen_1 ({units}) via gsw.O2sol + gsw.rho"
    else:
        pct_sat = measured / o2_sat_umol_kg * 100.0
        method = f"derived from oxygen_1 ({units}) via gsw.O2sol"

    new_attrs = {
        "units": "% saturation",
        "long_name": "O₂ saturation",
        "source_units": units,
        "oxygen_conversion": method,
    }
    dim = ds["oxygen_1"].dims[0]
    ds = ds.copy()
    ds["oxsat_1"] = xr.DataArray(
        pct_sat.astype(np.float32),
        dims=[dim],
        attrs=new_attrs,
    )
    return ds
