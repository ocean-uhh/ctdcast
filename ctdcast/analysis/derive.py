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

from ctdcast.config.preferred_sensors import index_of as _OXY_INDEX_OF

# ---------------------------------------------------------------------------
# Variable-resolution helpers
# ---------------------------------------------------------------------------

#: Preferred order for temperature: plain (single-sensor or stage3-promoted),
#: then primary suffix, then secondary suffix, then old pre-rename name.
_TEMP_CANDIDATES = ("ctd_temperature", "ctd_temperature_1", "temperature_1")
_SAL_CANDIDATES = ("ctd_salinity", "ctd_salinity_1", "salinity_1")
_OXY_CANDIDATES = ("ctd_oxygen", "ctd_oxygen_1", "oxygen_1")
_OXSAT_CANDIDATES = ("oxygen_saturation", "oxsat_1")

#: Map the preferred-oxygen word to its line index (single source in preferred_sensors).
_OXY_INDEX = {
    "primary": _OXY_INDEX_OF("primary"),
    "secondary": _OXY_INDEX_OF("secondary"),
}


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

    Uses ``gsw.SP_from_C``, which expects conductivity in mS/cm.  Stored
    conductivity is mS/cm since stage1; a file still carrying S/m (``units``
    not mS/cm) is converted by ×10.  Call this after any conductivity
    calibration so that salinity reflects the calibrated conductivity.

    Does nothing if ``conductivity_1`` or any temperature variable is absent.

    Writes output to ``ctd_salinity_1`` / ``ctd_salinity_2`` (CCHDO canonical
    names).  Records the conversion method in the variable's attrs.

    Parameters
    ----------
    ds:
        Per-cast Dataset (dim=time) containing at minimum ``conductivity_1``,
        a temperature variable, and ``pressure`` in their expected units
        (conductivity in mS/cm, temperature in °C ITS-90, pressure in dbar).

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

    # On single-sensor casts _normalise promotes ctd_salinity_1 → ctd_salinity;
    # write to whichever name is live in ds so the promoted plain name is kept current.
    _sal1_out = _resolve_var(ds, "ctd_salinity", "ctd_salinity_1") or "ctd_salinity_1"
    # Salinity needs a *matched* T/C pair, so each conductivity line pairs with its OWN
    # temperature line (never the other line's): conductivity_1 with ctd_temperature_1,
    # conductivity_2 with ctd_temperature_2. A single-T cast falls back to the resolved temp.
    _t1 = (
        _resolve_var(ds, "ctd_temperature_1", "ctd_temperature", "temperature_1")
        or temp_var
    )
    _t2 = _resolve_var(ds, "ctd_temperature_2") or _t1
    pairs = [
        ("conductivity_1", _sal1_out, _t1),
        ("conductivity_2", "ctd_salinity_2", _t2),
    ]
    for c_var, s_out, t_var in pairs:
        if c_var not in ds:
            continue
        c = ds[c_var].values.astype(float)
        t = ds[t_var].values.astype(float)
        # gsw.SP_from_C wants conductivity in mS/cm.  Stored conductivity is
        # mS/cm since stage1; convert only when a file still carries S/m.
        _cu = ds[c_var].attrs.get("units", "").lower().replace(" ", "")
        c_ms_cm = c if _cu in ("mscm-1", "ms/cm") else c * 10.0
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            sp = gsw.SP_from_C(c_ms_cm, t, p)

        existing_attrs = dict(ds[s_out].attrs) if s_out in ds else {}
        existing_attrs["derived_from"] = f"{c_var}, {t_var}, pressure via gsw.SP_from_C"
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
    :func:`derive_sigma0` in order.  Also derives ``oxygen_saturation`` (% sat) via
    :func:`_derive_oxygen_saturation` — per oxygen line, from that line's own T/S, with the
    composite selected by the ``preferred_oxygen`` attribute (never pairing the oxygen with
    the pair composite, which may be the other line).

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
    return _derive_oxygen_saturation(ds)


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
    out_name: str = "oxygen_saturation",
    ts_vars: tuple[str, str] | None = None,
) -> xr.Dataset:
    """Derive an oxygen-saturation variable (% sat) from an oxygen variable in molar units.

    Adds *out_name* to *ds*; leaves *oxy_var* unchanged.  Does nothing if *oxy_var* units do
    not indicate a molar concentration.  Records the conversion method and the source oxygen
    and T/S variables in the output's attributes for provenance.

    Parameters
    ----------
    ds:
        Dataset containing *oxy_var* in molar units.
    oxy_var:
        Name of the oxygen variable in molar units (e.g. ``"ctd_oxygen"`` / ``"ctd_oxygen_2"``).
    sa, ct, p:
        Absolute Salinity (g/kg), Conservative Temperature (°C), pressure (dbar) arrays — of
        the oxygen sensor's **own line**, matching the *oxy_var* dimension.
    lat, lon:
        Representative cast latitude and longitude for ``gsw.O2sol``.
    out_name:
        Name to store the result under (``oxygen_saturation`` for a single/plain sensor,
        ``oxygen_saturation_1`` / ``_2`` per line).
    ts_vars:
        The ``(temperature, salinity)`` variable names SA/CT were computed from, recorded in
        ``oxygen_conversion`` so the pairing (which line's T/S) is reconstructable from the file.
    """
    units = ds[oxy_var].attrs.get("units", "")
    if not units:
        return ds
    u_lower = units.lower()
    if "umol" not in u_lower and "µmol" not in u_lower:
        return ds

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        # gsw.O2sol signature is (SA, CT, p, lon, lat) — longitude before latitude, as
        # gsw.SA_from_SP above. Passing them in the wrong order evaluates solubility at the
        # wrong position (a small but systematic saturation bias).
        o2_sat_umol_kg = gsw.O2sol(sa, ct, p, lon, lat)

    measured = ds[oxy_var].values.astype(float)

    ts_note = f" with T/S from {ts_vars[0]}/{ts_vars[1]}" if ts_vars else ""
    if "/l" in u_lower or "l-1" in u_lower:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            rho = gsw.rho(sa, ct, p)  # kg/m³
        o2_sat_umol_l = o2_sat_umol_kg * rho / 1000.0
        pct_sat = measured / o2_sat_umol_l * 100.0
        method = f"derived from {oxy_var} ({units}) via gsw.O2sol + gsw.rho{ts_note}"
    else:
        pct_sat = measured / o2_sat_umol_kg * 100.0
        method = f"derived from {oxy_var} ({units}) via gsw.O2sol{ts_note}"

    new_attrs = {
        "units": "% saturation",
        "long_name": "O₂ saturation",
        "source_units": units,
        "oxygen_conversion": method,
    }
    dim = ds[oxy_var].dims[0]
    ds = ds.copy()
    ds[out_name] = xr.DataArray(
        pct_sat.astype(np.float32),
        dims=[dim],
        attrs=new_attrs,
    )
    return ds


def _line_ts_vars(ds: xr.Dataset, idx: int) -> tuple[str | None, str | None]:
    """Return the (temperature, salinity) variable names for oxygen line *idx*.

    Prefers the indexed channel (``ctd_temperature_{idx}``) — the oxygen sensor's own line —
    and falls back to the plain/first-available T/S for a fully single-sensor cast.
    """
    temp = f"ctd_temperature_{idx}"
    sal = f"ctd_salinity_{idx}"
    if temp not in ds:
        temp = _resolve_var(ds, *_TEMP_CANDIDATES)
    if sal not in ds:
        sal = _resolve_var(ds, *_SAL_CANDIDATES)
    return temp, sal


def _sa_ct_p(
    ds: xr.Dataset, temp_var: str, sal_var: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Return (SA, CT, p, lat, lon) computed from *temp_var*/*sal_var* for a 1-D cast."""
    p = ds["pressure"].values.astype(float)
    sp = ds[sal_var].values.astype(float)
    t = ds[temp_var].values.astype(float)
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        sa = gsw.SA_from_SP(sp, p, lon, lat)
        ct = gsw.CT_from_t(sa, t, p)
    return sa, ct, p, lat, lon


def _derive_oxygen_saturation(ds: xr.Dataset) -> xr.Dataset:
    """Derive ``oxygen_saturation`` per oxygen line, then select the composite by preference.

    Each oxygen line's saturation is computed from **its own line's** T/S (never the pair
    composite, which may be the other line): ``oxygen_saturation_1`` from
    ``(ctd_oxygen_1, ctd_temperature_1, ctd_salinity_1)`` and ``_2`` from line 2 (``oxygen_1``
    is the primary line — the plumbing assumption).  A single oxygen line (plain
    ``ctd_oxygen``, or just one of ``ctd_oxygen_1`` / ``ctd_oxygen_2``) gives the plain
    ``oxygen_saturation`` directly.

    When both lines are present the composite ``oxygen_saturation`` is the line named by the
    ``preferred_oxygen`` attribute — the same per-cast selection as the ``ctd_oxygen``
    composite.  ``oxygen_saturation`` is an on-the-fly **report** quantity (never stored), so
    an undeclared dual cast falls back to the primary line for the figure (recorded in the
    ``preferred_oxygen`` attribute of the result) — matching how the report resolves raw
    oxygen; unlike the stored ``ctd_oxygen`` composite, which is absent when undeclared.  A
    ``%``-saturation oxygen variable (legacy pre-rename files) is copied under the saturation
    name with saturation metadata, not recomputed.
    """
    # Collect whichever indexed oxygen lines are present; a lone _1 or _2 is a single line.
    lines = [(f"ctd_oxygen_{i}", i) for i in (1, 2) if f"ctd_oxygen_{i}" in ds]
    if not lines:
        plain = _resolve_var(ds, *_OXY_CANDIDATES)
        lines = [(plain, 1)] if plain is not None else []
    dual = len(lines) == 2

    for oxy_var, idx in lines:
        out_name = f"oxygen_saturation_{idx}" if dual else "oxygen_saturation"
        units = ds[oxy_var].attrs.get("units", "")
        u_lower = units.lower()
        if "umol" in u_lower or "µmol" in u_lower:
            if dual:
                # Each oxygen line must use its OWN line's T/S — never fall back to the
                # other line, which would silently cross-pair. If this line's indexed T/S
                # is absent (e.g. dual oxygen but single T/C), skip it with a warning
                # rather than compute a wrong saturation.
                temp_var = (
                    f"ctd_temperature_{idx}" if f"ctd_temperature_{idx}" in ds else None
                )
                sal_var = f"ctd_salinity_{idx}" if f"ctd_salinity_{idx}" in ds else None
                if temp_var is None or sal_var is None:
                    warnings.warn(
                        f"oxygen line {idx} ({oxy_var}) has no matching ctd_temperature_{idx}"
                        f"/ctd_salinity_{idx}; skipping its saturation to avoid pairing it "
                        f"with the other line's T/S.",
                        UserWarning,
                        stacklevel=3,
                    )
                    continue
            else:
                temp_var, sal_var = _line_ts_vars(ds, idx)
                if temp_var is None or sal_var is None:
                    continue
            sa, ct, p, lat, lon = _sa_ct_p(ds, temp_var, sal_var)
            ds = _derive_oxsat_from_oxygen(
                ds,
                oxy_var,
                sa,
                ct,
                p,
                lat,
                lon,
                out_name=out_name,
                ts_vars=(temp_var, sal_var),
            )
        elif "%" in u_lower or "sat" in u_lower or "percent" in u_lower:
            # Already % saturation: copy under the saturation name with saturation metadata
            # (not the source's oxygen-concentration long_name), and drop the source when it
            # held the plain single oxygen so a stale %-under-oxygen var cannot be re-read as
            # molar oxygen downstream.
            ds = ds.copy()
            src_attrs = dict(ds[oxy_var].attrs)
            ds[out_name] = xr.DataArray(
                ds[oxy_var].values,
                dims=ds[oxy_var].dims,
                attrs={
                    "units": "% saturation",
                    "long_name": "O₂ saturation",
                    "source_units": src_attrs.get("units", ""),
                    "oxygen_conversion": f"copied from {oxy_var} (already % saturation)",
                },
            )
            if not dual and oxy_var != out_name:
                ds = ds.drop_vars(oxy_var)
        else:
            warnings.warn(
                f"{oxy_var!r} has unrecognised units {units!r}; "
                f"{out_name} not derived. Expected 'umol', 'µmol', '%', 'sat', or 'percent'.",
                UserWarning,
                stacklevel=4,
            )

    # Composite for a dual cast: the preferred line if it was derived, else whichever line is
    # available (prefer the primary).  Guarded so a cast where one line failed still shows the
    # other rather than nothing.  The source line's provenance travels with the copy; the
    # chosen line is recorded in the composite's ``preferred_oxygen`` attribute.
    if dual:
        present = [i for i in (1, 2) if f"oxygen_saturation_{i}" in ds]
        if present:
            pref = ds.attrs.get("preferred_oxygen")
            chosen = _OXY_INDEX.get(pref) if pref in _OXY_INDEX else None
            if chosen not in present:
                chosen = present[0]
            ds = ds.copy()
            ds["oxygen_saturation"] = ds[f"oxygen_saturation_{chosen}"]
            # Provenance on the composite: which line it came from, and whether that was a
            # declared preference or the undeclared-fallback to the primary line. Read by the
            # deferred report display (a rep/ follow-up) to label an undeclared cast distinctly
            # from a declared one; carried now so the figure's source is reconstructable.
            ds["oxygen_saturation"].attrs["oxygen_line"] = chosen
            ds["oxygen_saturation"].attrs["preferred_oxygen"] = (
                pref if pref in _OXY_INDEX else "undeclared"
            )
    return ds
