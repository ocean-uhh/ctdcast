"""Backend protocol and dispatch for CTD data conversion.

Defines the CtdBackend Protocol, concrete backend implementations, and the
public API functions (convert_ctd_files, build_profiles) that cli/convert.py
calls. Adding a new backend means implementing CtdBackend and adding a branch
in get_ctd_backend() — nothing else changes.
"""

from __future__ import annotations

import contextlib
import io
import logging
import sys
import warnings
from pathlib import Path
from typing import Protocol

import numpy as np
import xarray as xr

from ctdcast.identity import cast_id_from_name

# seasenselib time-bookkeeping columns that are not physical data
_SKIP_VARS: frozenset[str] = frozenset({"timeJ", "timeS", "pressure"})


class CtdBackend(Protocol):
    """Protocol for per-cast CNV-to-netCDF converters."""

    def convert_cast(
        self,
        cnv_path: Path,
        nc_path: Path,
        *,
        force: bool = False,
    ) -> bool:
        """Convert one CNV file to netCDF.

        Parameters
        ----------
        cnv_path:
            Path to the raw SBE CNV input file.
        nc_path:
            Desired output netCDF path.
        force:
            If True, overwrite an existing nc_path.

        Returns
        -------
        bool
            True if the file was written; False if skipped.
        """
        ...


class _SeasenselibBackend:
    """CTD backend that delegates to the seasenselib package."""

    def __init__(self) -> None:
        """Initialise; raises ImportError if seasenselib is not installed."""
        try:
            import seasenselib as _sl
        except ImportError as exc:
            raise ImportError(
                "seasenselib backend requested but the package is not installed. "
                "Install it with: pip install seasenselib"
            ) from exc
        self._sl = _sl
        # Suppress verbose output from pycnv/seasenselib at the logger level.
        logging.getLogger("pycnv").setLevel(logging.ERROR)
        logging.getLogger("seasenselib").setLevel(logging.ERROR)

    def convert_cast(
        self,
        cnv_path: Path,
        nc_path: Path,
        *,
        force: bool = False,
    ) -> bool:
        """Convert one CNV file using seasenselib.

        Parameters
        ----------
        cnv_path:
            Path to the raw SBE CNV input file.
        nc_path:
            Desired output netCDF path.
        force:
            If True, overwrite an existing nc_path.

        Returns
        -------
        bool
            True if the file was written; False if skipped (already exists).
        """
        if nc_path.exists() and not force:
            return False
        with contextlib.redirect_stdout(io.StringIO()):
            ds = self._sl.read(str(cnv_path))
        self._sl.write(ds, str(nc_path), sanitize_names=True)
        return True


_BACKENDS: dict[str, type] = {
    "seasenselib": _SeasenselibBackend,
}


def get_ctd_backend(name: str) -> CtdBackend:
    """Return a CtdBackend instance for the given backend name.

    Parameters
    ----------
    name:
        Currently only ``"seasenselib"``.

    Raises
    ------
    ValueError
        If name is not a recognised backend.
    ImportError
        If the requested backend's package is not installed.
    """
    if name not in _BACKENDS:
        known = ", ".join(f"'{k}'" for k in _BACKENDS)
        raise ValueError(f"Unknown CTD backend: {name!r}. Known backends: {known}.")
    return _BACKENDS[name]()


def convert_ctd_files(
    cnv_dir: Path,
    nc_dir: Path,
    *,
    backend: str = "seasenselib",
    force: bool = False,
    cast_filter: int | None = None,
    pattern: str = "*.cnv",
) -> int:
    """Convert per-cast CNV files to netCDF using the specified backend.

    Public API — analogous to report() in index.py.

    Parameters
    ----------
    cnv_dir:
        Directory containing raw SBE CNV files.
    nc_dir:
        Output directory for per-cast netCDF files (created if absent).
    backend:
        Backend name (currently only ``"seasenselib"``).
    force:
        Overwrite existing netCDF files.
    cast_filter:
        If given, convert only files whose stem contains ``f"{cast_filter:03d}"``.
    pattern:
        Filename glob pattern applied within ``cnv_dir`` (default: ``"*.cnv"``).
        Use e.g. ``"msm*1sec.cnv"`` to select a subset of files.

    Returns
    -------
    int
        Number of files written (skipped files not counted).

    Raises
    ------
    NotImplementedError
        If the chosen backend has not been implemented yet.
    ImportError
        If the chosen backend's package is not installed.
    """
    nc_dir.mkdir(parents=True, exist_ok=True)
    b = get_ctd_backend(backend)

    cnv_files = sorted(cnv_dir.glob(pattern))
    if cast_filter is not None:
        tag = f"{cast_filter:03d}"
        cnv_files = [p for p in cnv_files if tag in p.stem]

    n = 0
    for cnv_path in cnv_files:
        nc_path = nc_dir / (cnv_path.stem + ".nc")
        try:
            with warnings.catch_warnings():
                # GSW Nsquared() warns on dp=0 (stationary CTD between 1-second samples).
                # The cast converts correctly; this is noise from the conversion backend.
                warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
                written = b.convert_cast(cnv_path, nc_path, force=force)
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED: {cnv_path.name}  ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
            continue
        if written:
            print(f"  ok: {cnv_path.name} → {nc_path.name}")
            n += 1
        else:
            print(f"  skip: {nc_path.name}")
    return n


# ---------------------------------------------------------------------------
# profiles.nc builder
# ---------------------------------------------------------------------------


def _select_cast_files(nc_dir: Path) -> list[tuple[int, Path]]:
    """Return sorted (cast_num, path) pairs from nc_dir, preferring _b variants.

    Recognises any ``*.nc`` file whose stem contains a 3+-digit cast number.
    The **last** such group is taken as the cast number, so cruise/leg numbers
    earlier in the name (e.g. ``142`` in ``msm_142_1_001_1sec``) are ignored.
    When both a plain and a ``_b`` variant exist for the same cast, ``_b`` wins.
    """
    chosen: dict[int, Path] = {}
    for p in sorted(nc_dir.glob("*.nc")):
        _id = cast_id_from_name(p.stem)
        if _id is None:
            continue
        cast_num, cast_suffix = _id
        is_b = cast_suffix == "b"
        if cast_num not in chosen or is_b:
            chosen[cast_num] = p
    return sorted(chosen.items())


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
    """Return (lat, lon, time_start, time_end) for a half-cast dataset."""
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
) -> bool:
    """Compile per-cast netCDF files into a single profiles.nc on a 1-dbar grid.

    Reads all ``<stem>_NNN[_b].nc`` files in nc_dir, splits each cast into
    downcast and upcast halves, bins onto a common 1-dbar pressure grid, and
    writes a single (N_PROF × pressure) netCDF.  Profile numbering: downcast of
    cast N → N + 1.0, upcast → N + 1.5 (1-indexed sequential rank).  When both
    a plain file and a ``_b`` repeat exist for the same cast number, the ``_b``
    file is used.

    Parameters
    ----------
    nc_dir:
        Directory containing per-cast netCDF files.
    profiles_path:
        Output path for the compiled profiles netCDF.
    force:
        Overwrite an existing profiles_path.

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
    for _, path in cast_list:
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        p_max_global = max(p_max_global, float(ds["pressure"].max()))
        ds.close()
    p_grid = np.arange(1, int(p_max_global) + 1, dtype=np.float32)

    # Get variable names and cruise attr from the first file
    ds0 = xr.open_dataset(cast_list[0][1], engine="netcdf4", decode_timedelta=False)
    var_names = [v for v in ds0.data_vars if v not in _SKIP_VARS]
    cruise = ds0.attrs.get("cruise", "UNK")
    ds0.close()

    n_profiles = len(cast_list) * 2
    n_pressure = len(p_grid)

    # Pre-allocate output arrays
    data_2d: dict[str, np.ndarray] = {
        v: np.full((n_profiles, n_pressure), np.nan, dtype=np.float32)
        for v in var_names
    }
    n_prof_vals = np.full(n_profiles, np.nan, dtype=np.float64)
    cast_nums = np.full(n_profiles, -1, dtype=np.int32)
    cast_types: list[str] = []
    lats = np.full(n_profiles, np.nan, dtype=np.float64)
    lons = np.full(n_profiles, np.nan, dtype=np.float64)
    time_starts = np.empty(n_profiles, dtype="datetime64[ns]")
    time_ends = np.empty(n_profiles, dtype="datetime64[ns]")

    # Pass 2: split and bin each cast
    for rank, (cast_num, path) in enumerate(cast_list, start=1):
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        pressure = ds["pressure"].values
        i_turn = _turnaround_index(pressure)

        for direction, sl in [
            ("down", slice(0, i_turn + 1)),
            ("up", slice(i_turn, None)),
        ]:
            prof_idx = (rank - 1) * 2 + (0 if direction == "down" else 1)
            ds_half = ds.isel(time=sl)
            binned = _bin_to_1dbar(ds_half, p_grid)
            lat, lon, t0, t1 = _cast_meta(ds_half)

            for v in var_names:
                if v in binned:
                    data_2d[v][prof_idx] = binned[v]

            n_prof_vals[prof_idx] = rank + (0.0 if direction == "down" else 0.5)
            cast_nums[prof_idx] = cast_num
            cast_types.append(direction)
            lats[prof_idx] = lat
            lons[prof_idx] = lon
            time_starts[prof_idx] = t0
            time_ends[prof_idx] = t1

        ds.close()

    # Build output dataset
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
                np.array(cast_types),
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
    ds_out["N_PROF"].attrs = {
        "long_name": "Profile number (integer = downcast, .5 = upcast)"
    }

    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = profiles_path.with_suffix(".nc.tmp")
    ds_out.to_netcdf(str(tmp))
    tmp.replace(profiles_path)
    return True
