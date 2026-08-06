"""GEBCO bathymetry loading and interpolation.

Pure computation — no matplotlib, no HTML.  GEBCO stores elevation as negative
below sea level; this module returns depth as positive below sea level
(``depth = -elevation``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

# Module-level numpy cache: populated by preload_gebco() at report start.
# Maps str(path) → (all_lons, all_lats, all_depth) numpy arrays for the cruise area.
# Once populated, load_gebco subsets with numpy (zero disk I/O).
_GEBCO_CACHE: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def preload_gebco(
    path: Path,
    lat_lo: float,
    lat_hi: float,
    lon_lo: float,
    lon_hi: float,
    margin: float = 1.0,
) -> bool:
    """Load a GEBCO region into memory once for the cruise area.

    Call this at report-generation start with the full lat/lon extent of all
    casts.  Subsequent ``load_gebco`` calls then subset from numpy arrays
    (no disk I/O) instead of reopening the file for every map figure.

    Parameters
    ----------
    path:
        Path to GEBCO netCDF file.
    lat_lo, lat_hi, lon_lo, lon_hi:
        Bounding box of the cruise area.
    margin:
        Extra degrees around the bounding box.  Default 1.0 deg.

    Returns
    -------
    bool
        True if the file was found and cached successfully.
    """
    if not Path(path).exists():
        return False
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
        lons = sub[lon_dim].values.copy()
        lats = sub[lat_dim].values.copy()
        depth = -sub["elevation"].values.copy()  # GEBCO: negative = below sea level
        bathy.close()
        _GEBCO_CACHE[str(path)] = (lons, lats, depth)
        return True
    except Exception:  # noqa: BLE001
        return False


def load_gebco(
    lat_lo: float,
    lat_hi: float,
    lon_lo: float,
    lon_hi: float,
    margin: float = 0.05,
    path: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Return a GEBCO subset as (lons, lats, depth_m) or None if unavailable.

    If ``preload_gebco`` has been called for *path*, subsets from the in-memory
    numpy cache (fast).  Otherwise opens the file from disk (slow).

    Parameters
    ----------
    path:
        Path to GEBCO_2025.nc. Pass ``plots.GEBCO_PATH`` from the caller.
        Returns None if not provided or file not found.
    """
    if path is None or not Path(path).exists():
        return None
    path_str = str(path)
    try:
        if path_str in _GEBCO_CACHE:
            all_lons, all_lats, all_depth = _GEBCO_CACHE[path_str]
            lon_mask = (all_lons >= lon_lo - margin) & (all_lons <= lon_hi + margin)
            lat_mask = (all_lats >= lat_lo - margin) & (all_lats <= lat_hi + margin)
            lons = all_lons[lon_mask]
            lats = all_lats[lat_mask]
            if lons.size == 0 or lats.size == 0:
                return None
            depth = all_depth[lat_mask][:, lon_mask]
            return lons, lats, depth
        # Fallback when preload_gebco was not called: open file directly.
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


def interpolate_bathy_at_casts(
    lats: list[float],
    lons: list[float],
    path: Path | None = None,
) -> np.ndarray | None:
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
        gebco = load_gebco(lat_lo, lat_hi, lon_lo, lon_hi, margin=0.1, path=path)
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


def dense_bathy_along_track(
    lats: list[float],
    lons: list[float],
    x_vals: np.ndarray,
    path: Path | None = None,
    n_per_segment: int = 20,
) -> tuple[np.ndarray | None, np.ndarray | None]:
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

        depths = interpolate_bathy_at_casts(dense_lats, dense_lons, path=path)
        if depths is None:
            return None, None
        return np.array(dense_x), depths
    except Exception:  # noqa: BLE001
        return None, None
