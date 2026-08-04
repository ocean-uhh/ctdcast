"""Tier-0: pure computation — TEOS-10, cast geometry, bathymetry loading.

No matplotlib. No HTML. Imported by _plots.py (Tier 1) and Tier-2 orchestrators.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import gsw
import numpy as np
import xarray as xr


def _add_teos10(ds: xr.Dataset) -> xr.Dataset:
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


# Module-level numpy cache: populated by preload_gebco() at report start.
# Maps str(path) → (all_lons, all_lats, all_depth) numpy arrays for the cruise area.
# Once populated, _load_gebco subsets with numpy (zero disk I/O).
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
    casts.  Subsequent ``_load_gebco`` calls then subset from numpy arrays
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


def _load_gebco(
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


def _section_orientation(lats: list[float], lons: list[float]) -> bool:
    """Return True if the section x-axis should be flipped for geographic convention.

    Convention: west on the left for E–W-dominant sections; north on the left for
    N–S-dominant sections.  Dominance is determined by comparing the end-to-end
    longitude span against the latitude span.

    Parameters
    ----------
    lats:
        Latitude of each cast in the section, in cast order.
    lons:
        Longitude of each cast in the section, in cast order.

    Returns
    -------
    bool
        True if ``x_vals`` (cumulative along-track distance from first cast)
        should be replaced by ``x_total - x_vals`` before plotting.
    """
    if len(lats) < 2:
        return False
    delta_lon = lons[-1] - lons[0]
    delta_lat = lats[-1] - lats[0]
    if abs(delta_lon) >= abs(delta_lat):  # E–W dominant
        return delta_lon < 0  # first cast is east → flip so west is left
    else:  # N–S dominant
        return delta_lat > 0  # first cast is south → flip so north is left


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

        depths = _interpolate_bathy_at_casts(dense_lats, dense_lons, path=path)
        if depths is None:
            return None, None
        return np.array(dense_x), depths
    except Exception:  # noqa: BLE001
        return None, None


def _find_soak_end(
    pressure: np.ndarray,
    times: np.ndarray,
    near_surface_dbar: float = 10.0,
    search_seconds: float = 20.0,
) -> int:
    """Return the index at which the real downcast begins (exclusive end of soak).

    Algorithm (three steps):

    1. Find ``i_max``, the index of the global pressure maximum (deepest point
       of the cast).  Searching only in ``pressure[0:i_max+1]`` keeps the
       upcast recovery — when the CTD returns to the surface at the end of the
       cast — from being confused with the pre-soak position.
    2. Within ``pressure[0:i_max+1]``, find the **last** index where
       ``pressure < near_surface_dbar``.  For a typical MSM-style cast this
       falls on the early real descent, just as the CTD passes
       ``near_surface_dbar`` going downward.
    3. Crawl **backward** from that index within ``search_seconds`` to find the
       **minimum pressure** — the shallowest point (closest to the surface) just
       before the real descent began.  Return the index immediately after that
       minimum as the start of the real downcast.

    In bad-weather conditions where the CTD soaks at depth and is never raised
    back to the surface, step 3 finds the minimum within the soak window and
    removes only the first ``search_seconds`` of the soak.  The operator-
    visible effect is a truncation of the pre-soak data, not a clean removal.

    Parameters
    ----------
    pressure:
        Pressure array in dbar (1-D, same length as *times*).
    times:
        Time coordinate array.  May be ``numpy.datetime64`` or numeric seconds;
        elapsed time is computed relative to ``times[0]``.
    near_surface_dbar:
        Pressure threshold used to find the last near-surface crossing before
        the main descent.  Default is 10 dbar (≈10 m), safely below the
        typical soak depth of 8–10 m.
    search_seconds:
        Width of the backward-crawl window (seconds) used to find the
        pre-descent surface minimum.  Default is 20 s.

    Returns
    -------
    int
        Index of the first record to keep; slice with
        ``ds.isel(time=slice(idx, None))``.  Returns 0 if the cast never
        reaches below ``near_surface_dbar`` (no trim applied).

    """
    n = len(pressure)
    if n == 0:
        return 0

    p_arr = np.asarray(pressure, dtype=float)
    times_arr = np.asarray(times)
    if np.issubdtype(times_arr.dtype, np.datetime64):
        elapsed = (times_arr - times_arr[0]) / np.timedelta64(1, "s")
    else:
        elapsed = times_arr.astype(float) - float(times_arr[0])

    # Step 1: deepest point (also limits search to downcast only)
    i_max = int(np.nanargmax(p_arr))

    # Step 2: last near-surface crossing before the deepest point
    pre_max_mask = p_arr[: i_max + 1] < near_surface_dbar
    near_indices = np.where(pre_max_mask)[0]
    if len(near_indices) == 0:
        return 0  # cast never came within near_surface_dbar of the surface

    i_last_near = int(near_indices[-1])

    # Step 3: within search_seconds before i_last_near, find the pressure minimum
    t_last = float(elapsed[i_last_near])
    i_win_start = int(np.searchsorted(elapsed, t_last - search_seconds))
    i_win_start = max(0, i_win_start)
    window_p = p_arr[i_win_start : i_last_near + 1]
    if len(window_p) == 0:
        return i_last_near + 1

    i_min_local = int(np.nanargmin(window_p))
    i_min = i_win_start + i_min_local

    return i_min + 1


def _find_cast_end(
    pressure: np.ndarray,
    times: np.ndarray,
    deck_window_seconds: float = 20.0,
    margin_dbar: float = 0.5,
    max_deck_dbar: float = 20.0,
) -> int:
    """Return the exclusive end index, trimming post-recovery deck records.

    Algorithm:

    1. Take the median pressure of the last *deck_window_seconds* seconds as
       the on-deck reference pressure.  Using a median handles sensor offset
       (the pressure sensor may not read exactly 0 dbar when the CTD is in
       the air) and is robust to brief oscillations on deck.
    2. Find the **first** index after the pressure maximum where pressure falls
       at or below ``p_deck_median + margin_dbar``.  Trim from that index
       onward.

    Returns ``len(pressure)`` (no trim) if:
    - the record is empty or the CTD never returned near the surface
      (``p_deck_median > max_deck_dbar``), or
    - pressure never drops to the threshold on the upcast.

    Parameters
    ----------
    pressure:
        Pressure array in dbar.
    times:
        Time coordinate array (``numpy.datetime64`` or numeric seconds).
    deck_window_seconds:
        Duration of the tail window used to estimate on-deck pressure.
    margin_dbar:
        Added to the on-deck median to form the cut threshold.
    max_deck_dbar:
        If the on-deck median exceeds this value the CTD is considered not to
        have returned to the surface and no trim is applied.

    Returns
    -------
    int
        Exclusive end index; slice with ``ds.isel(time=slice(None, idx))``.

    """
    n = len(pressure)
    if n == 0:
        return n

    p_arr = np.asarray(pressure, dtype=float)
    times_arr = np.asarray(times)
    if np.issubdtype(times_arr.dtype, np.datetime64):
        elapsed = (times_arr - times_arr[0]) / np.timedelta64(1, "s")
    else:
        elapsed = times_arr.astype(float) - float(times_arr[0])

    i_max = int(np.nanargmax(p_arr))

    # On-deck reference: median of final deck_window_seconds.
    t_end = float(elapsed[-1])
    i_win_start = int(np.searchsorted(elapsed, t_end - deck_window_seconds))
    i_win_start = max(i_max + 1, i_win_start)
    if i_win_start >= n:
        return n

    p_deck = float(np.nanmedian(p_arr[i_win_start:]))
    if p_deck > max_deck_dbar:
        return n

    threshold = p_deck + margin_dbar

    upcast = p_arr[i_max:]
    below = np.where(upcast <= threshold)[0]
    if len(below) == 0:
        return n

    return i_max + int(below[0])


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


def _find_ladcp_file(
    ladcp_dir: Path,
    cast_num: int,
    cast_suffix: str = "",
    ladcp_pattern: str | None = None,
) -> Path | None:
    """Return the .mat file for *cast_num* in *ladcp_dir*, or ``None`` if absent.

    If *ladcp_pattern* is given (e.g. ``"msm_142_1_*.mat"``), the ``*``
    wildcard is replaced with the zero-padded cast number (and optional suffix)
    and that name is tried first.  Falls back to standard names (``NNN.mat``,
    ``NNNb.mat``) then a ``*_NNN.mat`` glob for cruise-prefixed filenames.
    The first glob match (lexicographic) is returned when multiple files match.
    """
    if ladcp_pattern:
        for cast_str in (f"{cast_num:03d}{cast_suffix}", f"{cast_num:03d}"):
            p = ladcp_dir / ladcp_pattern.replace("*", cast_str)
            if p.exists():
                return p
    for name in (f"{cast_num:03d}{cast_suffix}.mat", f"{cast_num:03d}.mat"):
        p = ladcp_dir / name
        if p.exists():
            return p
    for glob_pat in (
        f"*_{cast_num:03d}{cast_suffix}.mat",
        f"*_{cast_num:03d}.mat",
    ):
        found = sorted(ladcp_dir.glob(glob_pat))
        if found:
            return found[0]
    return None
