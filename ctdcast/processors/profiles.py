"""Cruise-level profile compiler: per-cast netCDF → profiles.nc.

Reads all per-cast netCDF files in a directory, splits each into downcast and
upcast halves, bins to a common 1-dbar grid, and writes a single
(N_PROF × pressure) netCDF.  The ``converters`` module re-exports
``build_profiles`` for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast.analysis.bathymetry import interpolate_bathy_at_casts
from ctdcast.config.parameters import VARIABLES
from ctdcast.identity import cast_id_from_name, format_cast_id
from ctdcast.writers.netcdf import write as _write_nc

# seasenselib time-bookkeeping columns that are not physical data
_SKIP_VARS: frozenset[str] = frozenset({"timeJ", "timeS", "pressure"})


def _select_cast_files(nc_dir: Path) -> list[tuple[int, str, Path]]:
    """Return sorted ``(cast_num, cast_suffix, path)`` triples, one per distinct cast.

    Recognises any ``*.nc`` file whose stem contains a 3+-digit cast number.
    The **last** such group is taken as the cast number, so cruise/leg numbers
    earlier in the name (e.g. ``142`` in ``msm_142_1_001_1sec``) are ignored.
    A plain cast ``NNN`` and its lettered sibling ``NNNb``/``NNN_b`` are
    distinct events; identity is the ``(number, suffix)`` pair.  If the same
    pair appears in more than one file, the last in sorted order wins.
    """
    chosen: dict[tuple[int, str], Path] = {}
    for p in sorted(nc_dir.glob("*.nc")):
        _id = cast_id_from_name(p.stem)
        if _id is None:
            continue
        chosen[_id] = p
    return sorted((num, suffix, p) for (num, suffix), p in chosen.items())


def _turnaround_index(pressure: np.ndarray) -> int:
    """Return last index where pressure is within 2 dbar of its maximum."""
    p_max = float(np.nanmax(pressure))
    near_max = np.where(pressure >= p_max - 2)[0]
    return int(near_max[-1]) if len(near_max) else len(pressure) // 2


def _bin_to_1dbar(ds_half: xr.Dataset, p_grid: np.ndarray) -> dict[str, np.ndarray]:
    """Bin each data variable onto p_grid (1 dbar steps) by mean per bin.

    Uses numpy bincount — no pandas dependency required.
    """
    p_raw = ds_half["pressure"].values
    p_bin = np.round(p_raw).astype(int)
    p0 = int(p_grid[0])
    n = len(p_grid)
    idx = p_bin - p0  # index into p_grid for each raw sample

    result: dict[str, np.ndarray] = {}
    for v in ds_half.data_vars:
        if v in _SKIP_VARS:
            continue
        vals = ds_half[v].values.astype(float)
        out = np.full(n, np.nan, dtype=np.float32)
        in_range = (idx >= 0) & (idx < n) & ~np.isnan(vals)
        if in_range.any():
            vi = idx[in_range]
            vv = vals[in_range]
            sums = np.bincount(vi, weights=vv, minlength=n)
            counts = np.bincount(vi, minlength=n)
            nonzero = counts > 0
            out[nonzero] = np.float32(sums[nonzero] / counts[nonzero])
        result[v] = out
    return result


def _cast_meta(
    ds_half: xr.Dataset,
) -> tuple[float, float, np.datetime64, np.datetime64]:
    """Return (lat, lon, time_start, time_end) for a half-cast Dataset."""
    lat = float(np.nanmedian(ds_half["latitude"].values))
    lon = float(np.nanmedian(ds_half["longitude"].values))
    t0 = ds_half["time"].values[0].astype("datetime64[ns]")
    t1 = ds_half["time"].values[-1].astype("datetime64[ns]")
    return lat, lon, t0, t1


def build_profiles(
    nc_dir: Path,
    profiles_path: Path,
    *,
    force: bool = False,
    gebco_path: Path | None = None,
) -> bool:
    """Compile per-cast netCDF files into a single profiles.nc on a 1-dbar grid.

    Reads all ``*.nc`` files in nc_dir, splits each cast into downcast and
    upcast halves, bins to a common 1-dbar pressure grid, and writes a single
    (N_PROF × pressure) netCDF.  N_PROF is a plain integer index (0, 1, 2, …);
    cast identity is carried by ``cast_number``, ``cast_suffix``, and
    ``cast_direction`` variables.

    Per-cast scalar variables added to the output:

    - ``max_pressure_dbar`` — maximum pressure recorded over the full cast.
    - ``gebco_depth_m`` — GEBCO bathymetry depth (m, positive down) at the
      max-pressure lat/lon position; NaN when *gebco_path* is None or the file
      is unavailable.

    The ``altimeter`` channel (when present in the input files) is binned onto
    the 1-dbar grid as a standard 2-D variable.

    Parameters
    ----------
    nc_dir:
        Directory containing per-cast netCDF files.
    profiles_path:
        Output path for the compiled profiles netCDF.
    force:
        Overwrite an existing profiles_path.
    gebco_path:
        Path to a GEBCO_2025.nc file.  Used to look up water depth at each
        cast's max-pressure position.  Pass ``cfg.gebco_path`` when calling
        from report generation code.  Silently omitted when None.

    Returns
    -------
    bool
        True if profiles.nc was written; False if skipped (existed, force=False).

    Raises
    ------
    ValueError
        If no recognised cast files are found in nc_dir.
    """
    if profiles_path.exists() and not force:
        return False

    cast_list = _select_cast_files(nc_dir)
    if not cast_list:
        raise ValueError(f"No recognised cast netCDF files found in {nc_dir}.")

    # Pass 1: determine global pressure range for the shared grid
    p_max_global = 0.0
    for _, _suffix, path in cast_list:
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        p_max_global = max(p_max_global, float(ds["pressure"].max()))
        ds.close()
    p_grid = np.arange(1, int(p_max_global) + 1, dtype=np.float32)

    # Get variable names and cruise attr from the first file
    ds0 = xr.open_dataset(cast_list[0][2], engine="netcdf4", decode_timedelta=False)
    var_names = [v for v in ds0.data_vars if v not in _SKIP_VARS]
    cruise = ds0.attrs.get("cruise", "UNK")
    ds0.close()

    n_casts = len(cast_list)
    n_profiles = n_casts * 2
    n_pressure = len(p_grid)

    # Pre-allocate output arrays
    data_2d: dict[str, np.ndarray] = {
        v: np.full((n_profiles, n_pressure), np.nan, dtype=np.float32)
        for v in var_names
    }
    cast_nums = np.full(n_profiles, -1, dtype=np.int32)
    cast_suffixes: list[str] = []
    directions: list[str] = []
    lats = np.full(n_profiles, np.nan, dtype=np.float64)
    lons = np.full(n_profiles, np.nan, dtype=np.float64)
    time_starts = np.empty(n_profiles, dtype="datetime64[ns]")
    time_ends = np.empty(n_profiles, dtype="datetime64[ns]")

    # Per-cast scalars (indexed by rank, then expanded to N_PROF after Pass 2)
    max_pressures = np.full(n_casts, np.nan, dtype=np.float32)
    lats_at_max_p = np.full(n_casts, np.nan, dtype=np.float64)
    lons_at_max_p = np.full(n_casts, np.nan, dtype=np.float64)

    # Pass 2: split and bin each cast
    for rank, (cast_num, cast_suffix, path) in enumerate(cast_list):
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        pressure = ds["pressure"].values
        i_turn = _turnaround_index(pressure)

        i_max_p = int(np.nanargmax(pressure))
        max_pressures[rank] = float(pressure[i_max_p])
        lats_at_max_p[rank] = float(ds["latitude"].values[i_max_p])
        lons_at_max_p[rank] = float(ds["longitude"].values[i_max_p])

        for direction, sl in [
            ("down", slice(0, i_turn + 1)),
            ("up", slice(i_turn, None)),
        ]:
            prof_idx = rank * 2 + (0 if direction == "down" else 1)
            ds_half = ds.isel(time=sl)
            binned = _bin_to_1dbar(ds_half, p_grid)
            lat, lon, t0, t1 = _cast_meta(ds_half)

            for v in var_names:
                if v in binned:
                    data_2d[v][prof_idx] = binned[v]

            cast_nums[prof_idx] = cast_num
            cast_suffixes.append(cast_suffix)
            directions.append(direction)
            lats[prof_idx] = lat
            lons[prof_idx] = lon
            time_starts[prof_idx] = t0
            time_ends[prof_idx] = t1

        ds.close()

    # Expand per-cast scalars to per-profile (same value for down and up of each cast)
    max_pressure_prof = np.repeat(max_pressures, 2)
    gebco_per_cast = interpolate_bathy_at_casts(
        list(lats_at_max_p), list(lons_at_max_p), path=gebco_path
    )
    if gebco_per_cast is None:
        gebco_per_cast = np.full(n_casts, np.nan, dtype=np.float32)
    gebco_depth_prof = np.repeat(gebco_per_cast.astype(np.float32), 2)

    # Build output dataset
    # N_PROF is a plain sequential integer index — cast identity is in
    # cast_number + cast_suffix + cast_direction.
    n_prof_idx = np.arange(n_profiles, dtype=np.int32)
    coords = {
        "N_PROF": ("N_PROF", n_prof_idx),
        "pressure": ("pressure", p_grid),
    }
    # Science vars carry only the coordinates pointer here; write() supplies
    # units/long_name/standard_name/label_units from VARIABLES.  A var not in
    # VARIABLES keeps a placeholder long_name so it is not left wholly unlabelled.
    data_vars: dict = {
        v: (
            ["N_PROF", "pressure"],
            data_2d[v],
            {"coordinates": "latitude longitude"}
            if v in VARIABLES
            else {"long_name": v, "coordinates": "latitude longitude"},
        )
        for v in var_names
    }
    data_vars.update(
        {
            "cast_number": (
                ["N_PROF"],
                cast_nums,
                {"long_name": "original cast number from filename"},
            ),
            "cast_suffix": (
                ["N_PROF"],
                np.array(cast_suffixes),
                {
                    "long_name": "cast letter suffix from filename",
                    "comment": (
                        "empty for a plain cast; a letter (e.g. 'b') marks a "
                        "distinct sibling event at the same station number"
                    ),
                },
            ),
            "cast_id": (
                ["N_PROF"],
                np.array(
                    [
                        format_cast_id(n, s)
                        for n, s in zip(cast_nums, cast_suffixes, strict=True)
                    ]
                ),
                {
                    "long_name": "Cast identifier",
                    "comment": "Zero-padded cast number with optional letter suffix, e.g. '004' or '004b'.",
                },
            ),
            "cast_direction": (
                ["N_PROF"],
                np.array(directions),
                {
                    "long_name": "Profile direction",
                    "flag_values": "down up",
                    "comment": "replaces the N_PROF = cast + 0.5 float encoding",
                },
            ),
            # Keep cast_type as a deprecated alias until consumers are updated.
            "cast_type": (
                ["N_PROF"],
                np.array(directions),
                {
                    "long_name": "downcast or upcast (deprecated alias for cast_direction)",
                    "flag_values": "down up",
                },
            ),
            # long_name/units/standard_name come from VARIABLES via write(); the
            # comment records that the position is the per-profile median fix.
            "latitude": (
                ["N_PROF"],
                lats,
                {"comment": "median of the position fixes over the cast direction"},
            ),
            "longitude": (
                ["N_PROF"],
                lons,
                {"comment": "median of the position fixes over the cast direction"},
            ),
            "time_start": (
                ["N_PROF"],
                time_starts,
                {"long_name": "start time of cast direction"},
            ),
            "time_end": (
                ["N_PROF"],
                time_ends,
                {"long_name": "end time of cast direction"},
            ),
            "max_pressure_dbar": (
                ["N_PROF"],
                max_pressure_prof,
                {
                    "long_name": "Maximum pressure recorded during full cast",
                    "units": "dbar",
                    "comment": "Same value for downcast and upcast profiles of the same cast.",
                },
            ),
            "gebco_depth_m": (
                ["N_PROF"],
                gebco_depth_prof,
                {
                    "long_name": "GEBCO bathymetry depth at max-pressure position",
                    "units": "m",
                    "positive": "down",
                    "comment": (
                        "Bilinearly interpolated from GEBCO_2025 at the lat/lon "
                        "of maximum pressure. NaN when GEBCO file is unavailable."
                    ),
                },
            ),
        }
    )
    attrs = {
        "title": f"{cruise} CTD profiles — all casts, downcast + upcast",
        "cruise": cruise,
        "source": f"{len(cast_list)} per-cast netCDF files compiled by ctdcast",
        "pressure_units": "dbar",
        "pressure_spacing_dbar": 1,
        "Conventions": "CF-1.13",
    }

    ds_out = xr.Dataset(data_vars=data_vars, coords=coords, attrs=attrs)
    ds_out["pressure"].attrs = {
        "units": "dbar",
        "long_name": "Sea water pressure",
        "positive": "down",
        "axis": "Z",
    }
    ds_out["N_PROF"].attrs = {"long_name": "Profile index (0-based sequential)"}

    # Route through the CF writer so the binned science variables and the
    # latitude/longitude/pressure coordinates receive their VARIABLES metadata
    # (units, standard_name, long_name, label_units) — a plain to_netcdf here
    # would leave them unlabelled.  write() writes atomically.
    _write_nc(ds_out, profiles_path)
    return True


def run(
    nc_dir: Path,
    profiles_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    **kw: object,
) -> bool:
    """Build ``profiles.nc`` from NC files in *nc_dir*.

    Called by :func:`ctdcast.processors.process` with ``stage="profiles"``.

    Parameters
    ----------
    nc_dir:
        Directory of per-cast netCDF files.
    profiles_path:
        Output path for the compiled profiles netCDF.
    force:
        Overwrite an existing profiles.nc.
    dry_run:
        Print what would be built without writing any output.
    **kw:
        Passed to :func:`build_profiles` (e.g. ``gebco_path``).

    Returns
    -------
    bool
        True if profiles.nc was written; False if skipped (or dry_run).
    """
    if dry_run:
        print(f"[dry-run] profiles: {nc_dir} → {profiles_path}")
        return False
    result = build_profiles(nc_dir, profiles_path, force=force, **kw)
    if result:
        print(f"profiles: wrote {profiles_path}")
    else:
        print(
            f"profiles: skipped (already exists; use --force to overwrite):"
            f" {profiles_path}"
        )
    return result
