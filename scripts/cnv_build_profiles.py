"""Build a 2D (N_PROF × pressure) netCDF from per-cast netCDF files.

Reads all files in cnv_nc/, splits each cast into downcast and upcast,
bins onto a common 1 dbar pressure grid, and writes a single file where
every physical variable has shape (N_PROF, pressure).

Profile numbering (N_PROF coordinate, float64):
  downcast of cast N  →  N + 1.0   (1-indexed sequential rank)
  upcast   of cast N  →  N + 1.5

For cast numbers with a '_b' repeat, the _b file is used and the plain
file is discarded.

Usage
-----
    python cnv_build_profiles.py
    python cnv_build_profiles.py --in-dir /path/cnv_nc --out /path/profiles.nc
"""

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

NC_DIR = Path("/Volumes/T9ifmeo/odb2026/CTD/cnv_nc")
OUT_PATH = Path("/Volumes/T9ifmeo/odb2026/CTD/profiles.nc")

# Variables to skip — time bookkeeping columns, not physical data
_SKIP_VARS = {"timeJ", "timeS", "pressure"}


def _select_files(nc_dir: Path) -> list[tuple[int, Path]]:
    """Return sorted [(cast_num, path)] using _b version when both exist."""
    pattern = re.compile(r"^mixsed2_(\d+)(_b)?$")
    chosen: dict[int, Path] = {}
    for p in sorted(nc_dir.glob("*.nc")):
        m = pattern.match(p.stem)
        if not m:
            continue
        cast_num = int(m.group(1))
        is_b = m.group(2) is not None
        if cast_num not in chosen or is_b:
            chosen[cast_num] = p
    return sorted(chosen.items())


def _turnaround_index(pressure: np.ndarray) -> int:
    """Return last index where pressure is within 2 dbar of its maximum."""
    p_max = np.nanmax(pressure)
    near_max = np.where(pressure >= p_max - 2)[0]
    return int(near_max[-1]) if len(near_max) else len(pressure) // 2


def _bin_cast(ds_cast: xr.Dataset, p_grid: np.ndarray) -> dict[str, np.ndarray]:
    """Bin all data variables onto p_grid (1 dbar steps) via mean per bin."""
    p_raw = ds_cast["pressure"].values
    p_bin = np.round(p_raw).astype(int)

    data_cols = {v: ds_cast[v].values for v in ds_cast.data_vars if v not in _SKIP_VARS}
    df = pd.DataFrame(data_cols)
    df["_p"] = p_bin
    grouped = df.groupby("_p").mean()

    p0 = int(p_grid[0])
    result: dict[str, np.ndarray] = {}
    for var in data_cols:
        arr = np.full(len(p_grid), np.nan, dtype=np.float32)
        for p_val, row_val in zip(
            grouped.index.values, grouped[var].values, strict=True
        ):
            idx = p_val - p0
            if 0 <= idx < len(p_grid):
                arr[idx] = np.float32(row_val)
        result[var] = arr
    return result


def _profile_meta(ds_cast: xr.Dataset) -> dict:
    """Extract scalar metadata for one cast direction."""
    return {
        "latitude": float(np.nanmedian(ds_cast["latitude"].values)),
        "longitude": float(np.nanmedian(ds_cast["longitude"].values)),
        "time_start": pd.Timestamp(ds_cast["time"].values[0]),
        "time_end": pd.Timestamp(ds_cast["time"].values[-1]),
    }


def main() -> None:
    """Run cast splitting and 2D profile assembly."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--in-dir", type=Path, default=NC_DIR)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    cast_list = _select_files(args.in_dir)
    if not cast_list:
        print(f"No recognised files in {args.in_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(cast_list)} casts (after _b selection)")

    # ---- First pass: determine common pressure grid -------------------------
    p_max_global = 0
    for _, path in cast_list:
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        p_max_global = max(p_max_global, float(ds["pressure"].max()))
        ds.close()
    p_grid = np.arange(1, int(p_max_global) + 1, dtype=np.float32)
    print(f"Pressure grid: 1–{int(p_max_global)} dbar ({len(p_grid)} levels)")

    # ---- Second pass: split and bin each cast --------------------------------
    n_profiles = len(cast_list) * 2  # downcast + upcast each
    n_pressure = len(p_grid)

    # Collect variable names from the first file
    ds0 = xr.open_dataset(cast_list[0][1], engine="netcdf4", decode_timedelta=False)
    var_names = [v for v in ds0.data_vars if v not in _SKIP_VARS]
    ds0.close()

    # Pre-allocate output arrays
    data_2d: dict[str, np.ndarray] = {
        v: np.full((n_profiles, n_pressure), np.nan, dtype=np.float32)
        for v in var_names
    }
    n_prof_vals = np.full(n_profiles, np.nan, dtype=np.float64)
    cast_nums = np.full(n_profiles, -1, dtype=np.int32)
    cast_types = np.empty(n_profiles, dtype="U4")
    lats = np.full(n_profiles, np.nan, dtype=np.float64)
    lons = np.full(n_profiles, np.nan, dtype=np.float64)
    time_starts = np.empty(n_profiles, dtype="datetime64[ns]")
    time_ends = np.empty(n_profiles, dtype="datetime64[ns]")

    prof_idx = 0
    for rank, (cast_num, path) in enumerate(cast_list, start=1):
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        pressure = ds["pressure"].values
        i_turn = _turnaround_index(pressure)

        for direction, sl in [
            ("down", slice(0, i_turn + 1)),
            ("up", slice(i_turn, None)),
        ]:
            ds_half = ds.isel(time=sl)
            binned = _bin_cast(ds_half, p_grid)
            meta = _profile_meta(ds_half)

            for v in var_names:
                if v in binned:
                    data_2d[v][prof_idx] = binned[v]

            n_prof_vals[prof_idx] = rank + (0.0 if direction == "down" else 0.5)
            cast_nums[prof_idx] = cast_num
            cast_types[prof_idx] = direction
            lats[prof_idx] = meta["latitude"]
            lons[prof_idx] = meta["longitude"]
            time_starts[prof_idx] = np.datetime64(meta["time_start"], "ns")
            time_ends[prof_idx] = np.datetime64(meta["time_end"], "ns")
            prof_idx += 1

        ds.close()
        print(
            f"  [{rank:3d}/{len(cast_list)}] cast {cast_num:03d} "
            f"({path.name}): {i_turn + 1} down + {len(pressure) - i_turn} up samples"
        )

    # ---- Build xarray Dataset -----------------------------------------------
    coords = {
        "N_PROF": ("N_PROF", n_prof_vals),
        "pressure": ("pressure", p_grid),
    }
    data_vars: dict = {
        v: (
            ["N_PROF", "pressure"],
            data_2d[v],
            {"long_name": v, "coordinates": "latitude longitude"},
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
            "cast_type": (
                ["N_PROF"],
                cast_types,
                {"long_name": "downcast or upcast", "flag_values": "down up"},
            ),
            "latitude": (
                ["N_PROF"],
                lats,
                {"units": "degrees_north", "long_name": "median latitude"},
            ),
            "longitude": (
                ["N_PROF"],
                lons,
                {"units": "degrees_east", "long_name": "median longitude"},
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
        }
    )
    attrs = {
        "title": "MIXSED-2 CTD profiles — all casts, downcast + upcast",
        "cruise": "odb2026",
        "source": f"{len(cast_list)} CNV files converted via seasenselib",
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
    ds_out["N_PROF"].attrs = {"long_name": "Profile number (int=downcast, .5=upcast)"}

    tmp = Path(str(args.out) + ".tmp")
    ds_out.to_netcdf(tmp)
    tmp.replace(args.out)
    print(f"\nWrote {n_profiles} profiles × {n_pressure} pressure levels → {args.out}")


if __name__ == "__main__":
    main()
