"""Tier-0: pure computation — TEOS-10, cast geometry, bathymetry loading.

No matplotlib. No HTML. Imported by _plots.py (Tier 1) and Tier-2 orchestrators.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import gsw
import numpy as np
import xarray as xr


def _add_teos10(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with CT, SA, sigma0 added (1-D per-cast Dataset, dim=time)."""
    if "CT" in ds and "SA" in ds and "sigma0" in ds:
        return ds
    ds = ds.copy()
    p = ds["pressure"].values.astype(float)
    t = ds["temperature_1"].values.astype(float)
    sp = ds["salinity_1"].values.astype(float)
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
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
    return ds


def _add_teos10_profiles(ds: xr.Dataset) -> xr.Dataset:
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


def _split_cast(ds: xr.Dataset) -> tuple[xr.Dataset, xr.Dataset]:
    """Split *ds* (individual cast file, dim=time) into (downcast, upcast).

    Uses the turnaround convention: last index where pressure is within 2 dbar
    of its maximum.
    """
    p = ds["pressure"].values
    p_max = float(np.nanmax(p))
    near = np.where(p >= p_max - 2)[0]
    i_turn = int(near[-1]) if len(near) else len(p) // 2
    return ds.isel(time=slice(0, i_turn + 1)), ds.isel(time=slice(i_turn, None))


def _load_gebco(
    lat_lo: float,
    lat_hi: float,
    lon_lo: float,
    lon_hi: float,
    margin: float = 0.05,
    path: Optional[Path] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Load a GEBCO subset; return (lons, lats, depth_m) or None if unavailable.

    Parameters
    ----------
    path:
        Path to GEBCO_2025.nc. Pass ``_plots.GEBCO_PATH`` from the caller.
        Returns None if not provided or file not found.
    """
    if path is None or not Path(path).exists():
        return None
    try:
        bathy = xr.open_dataset(path, engine="netcdf4")
        lon_dim = "lon" if "lon" in bathy.coords else "longitude"
        lat_dim = "lat" if "lat" in bathy.coords else "latitude"
        sub = bathy.sel(
            {
                lon_dim: slice(lon_lo - margin, lon_hi + margin),
                lat_dim: slice(lat_lo - margin, lat_hi + margin),
            }
        )
        lons = sub[lon_dim].values
        lats = sub[lat_dim].values
        depth = -sub["elevation"].values  # GEBCO: negative = below sea level
        bathy.close()
        return lons, lats, depth
    except Exception:  # noqa: BLE001
        return None


def _along_track_km(lats: list[float], lons: list[float]) -> tuple[np.ndarray, str]:
    """Return (cumulative_distance_km, x_axis_label) for a list of positions."""
    if len(lats) < 2:
        return np.arange(len(lats), dtype=float), "Cast index"
    try:
        dists_m = gsw.distance(np.array(lons), np.array(lats))
        x_km = np.concatenate([[0.0], np.cumsum(dists_m / 1000.0)])
        return x_km, "Along-track distance (km)"
    except Exception:  # noqa: BLE001
        return np.arange(len(lats), dtype=float), "Cast index"


def _add_aou(ds: xr.Dataset) -> xr.Dataset:
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


def _interpolate_bathy_at_casts(
    lats: list[float],
    lons: list[float],
    path: Optional[Path] = None,
) -> Optional[np.ndarray]:
    """Return GEBCO water depth (m, positive below sea level) at each cast position.

    Uses bilinear interpolation via xarray.  Returns ``None`` if GEBCO is not
    available or on any error.  Land points (elevation > 0) are clamped to 0.
    """
    if path is None or not Path(path).exists():
        return None
    try:
        lats_arr = np.asarray(lats, dtype=float)
        lons_arr = np.asarray(lons, dtype=float)
        finite = np.isfinite(lats_arr) & np.isfinite(lons_arr)
        if not finite.any():
            return None
        lat_lo = float(lats_arr[finite].min())
        lat_hi = float(lats_arr[finite].max())
        lon_lo = float(lons_arr[finite].min())
        lon_hi = float(lons_arr[finite].max())
        gebco = _load_gebco(lat_lo, lat_hi, lon_lo, lon_hi, margin=0.1, path=path)
        if gebco is None:
            return None
        lons_g, lats_g, depth_g = gebco
        # depth_g shape: (N_lat, N_lon) — positive = below sea level
        da = xr.DataArray(
            depth_g,
            dims=["lat", "lon"],
            coords={"lat": lats_g, "lon": lons_g},
        )
        da = da.sortby("lat").sortby("lon")
        result = da.interp(
            lat=xr.DataArray(lats_arr, dims="n"),
            lon=xr.DataArray(lons_arr, dims="n"),
            method="linear",
        )
        return np.maximum(result.values.astype(float), 0.0)
    except Exception:  # noqa: BLE001
        return None


def _dense_bathy_along_track(
    lats: list[float],
    lons: list[float],
    x_vals: np.ndarray,
    path: Optional[Path] = None,
    n_per_segment: int = 20,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Return ``(dense_x, dense_depths)`` interpolated between cast positions.

    Generates *n_per_segment* equally-spaced points along each segment between
    consecutive casts, giving a smooth GEBCO bathymetry fill rather than the
    stepped appearance produced by one sample per cast.  Returns ``(None, None)``
    when GEBCO is unavailable or fewer than two cast positions are supplied.
    """
    if path is None or not Path(path).exists() or len(lats) < 2:
        return None, None
    try:
        dense_lats: list[float] = []
        dense_lons: list[float] = []
        dense_x: list[float] = []
        for i in range(len(lats) - 1):
            t = np.linspace(0.0, 1.0, n_per_segment, endpoint=False)
            dense_lats.extend((lats[i] + t * (lats[i + 1] - lats[i])).tolist())
            dense_lons.extend((lons[i] + t * (lons[i + 1] - lons[i])).tolist())
            dense_x.extend((x_vals[i] + t * (x_vals[i + 1] - x_vals[i])).tolist())
        dense_lats.append(lats[-1])
        dense_lons.append(lons[-1])
        dense_x.append(float(x_vals[-1]))

        depths = _interpolate_bathy_at_casts(dense_lats, dense_lons, path=path)
        if depths is None:
            return None, None
        return np.array(dense_x), depths
    except Exception:  # noqa: BLE001
        return None, None


def _compact_cast_list(nums: list[int]) -> str:
    """Format a cast number list compactly, collapsing consecutive runs into ranges.

    Example: [131, 133, 134, 136, 163] → "131, 133–134, 136, 163".
    """
    if not nums:
        return "—"
    nums = sorted(set(nums))
    parts: list[str] = []
    start = end = nums[0]
    for n in nums[1:]:
        if n == end + 1:
            end = n
        else:
            parts.append(str(start) if start == end else f"{start}–{end}")
            start = end = n
    parts.append(str(start) if start == end else f"{start}–{end}")
    return ", ".join(parts)
