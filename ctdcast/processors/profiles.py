"""Cruise-level profile compiler: per-cast netCDF → profiles.nc.

Reads all per-cast netCDF files in a directory, splits each into downcast and
upcast halves, bins to a common 1-dbar grid, and writes a single
(N_PROF × pressure) netCDF.  The ``converters`` module re-exports
``build_profiles`` for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path

import warnings

import numpy as np
import xarray as xr

from ctdcast.analysis.bathymetry import interpolate_bathy_at_casts
from ctdcast.config.parameters import VARIABLES
from ctdcast.config.sensors import (
    SensorOverrides,
    SensorRegistry,
    catalog_var_name,
    resolve_sensor,
)
from ctdcast.identity import cast_id_from_name, format_cast_id
from ctdcast.readers.metadata import parse_sensor_channels
from ctdcast.writers.netcdf import write as _write_nc

# seasenselib time-bookkeeping columns that are not physical data
_SKIP_VARS: frozenset[str] = frozenset({"timeJ", "timeS", "pressure"})


def _build_sensor_catalog(
    cast_sensor_records: list[list[dict[str, str]]],
    cast_list: list[tuple[int, str, Path]],
    n_profiles: int,
    overrides: SensorOverrides,
) -> tuple[dict, dict]:
    """Build the sensor catalog and per-profile linkage variables.

    Attribute names follow OG1 conventions for interoperability, but this is
    shipboard CTD data and the per-profile linkage has no OG1 equivalent.

    *cast_sensor_records* is one :func:`parse_sensor_channels` result per cast,
    in the same rank order as *cast_list*.  Each cast contributes to two profiles
    (down, up), so a cast at rank ``r`` fills profile indices ``2r`` and ``2r+1``.

    Returns ``(catalog_vars, linkage_vars)`` as xarray-style
    ``{name: (dims, data, attrs)}`` mappings:

    - **catalog** — one dimensionless ``SENSOR_<TYPE>_<INDEX>_<SERIAL>`` variable
      per distinct physical sensor, carrying its resolved attributes.
    - **linkage** — ``sensor_<role>(N_PROF)`` naming the catalog variable in that
      role for each profile, and ``sensor_channel_<role>(N_PROF)`` recording the
      raw acquisition channel.
    """
    registry = SensorRegistry.load()
    catalog: dict[str, dict[str, str]] = {}
    serial_to_vars: dict[str, set[str]] = {}
    roles: list[str] = []  # first-appearance order
    link: dict[str, np.ndarray] = {}
    chan: dict[str, np.ndarray] = {}

    for rank, records in enumerate(cast_sensor_records):
        cast_num = cast_list[rank][0]
        for rec in records:
            role, serial = rec["role"], rec["serial"]
            if not role or not serial:  # skip Free/unused and serial-less slots
                continue
            canon = overrides.canonical_serial(serial)
            name = catalog_var_name(role, canon)
            prior = catalog.get(name)
            if prior is None:
                # Resolve (and warn on an unresolved model) once per distinct
                # device — not once per cast, which floods the log for a device
                # present on every cast (e.g. an un-overridden UVP6).
                catalog[name] = resolve_sensor(
                    sensor_id=rec["sensor_id"],
                    serial=serial,
                    role=role,
                    calibration_date=rec["calibration_date"],
                    element=rec["element"],
                    cast=cast_num,
                    registry=registry,
                    overrides=overrides,
                )
                serial_to_vars.setdefault(canon, set()).add(name)
            elif prior.get("sensor_calibration_date") != rec["calibration_date"]:
                # A serial cannot be recalibrated mid-cruise (that needs a return
                # to the manufacturer), so two calibration dates for one device
                # mean a parsing/data error — surface it rather than overwrite.
                warnings.warn(
                    f"Sensor catalog conflict for {name}: calibration date "
                    f"{prior.get('sensor_calibration_date')!r} then "
                    f"{rec['calibration_date']!r} (cast {cast_num}); a serial "
                    "cannot be recalibrated at sea — check CNV parsing.",
                    stacklevel=2,
                )
            if role not in link:
                roles.append(role)
                link[role] = np.array([""] * n_profiles, dtype=object)
                chan[role] = np.full(n_profiles, -1, dtype=np.int32)
            for k in (rank * 2, rank * 2 + 1):
                link[role][k] = name
                chan[role][k] = rec["channel"]

    # Cross-link catalog entries that resolve to the same physical serial
    # (e.g. one FLNTU serving both fluorometer and turbidity roles).
    for names in serial_to_vars.values():
        if len(names) > 1:
            for name in names:
                catalog[name]["sensor_shared_with"] = " ".join(sorted(names - {name}))

    catalog_vars: dict = {
        name: ((), np.int32(0), {k: v for k, v in attrs.items() if v != ""})
        for name, attrs in catalog.items()
    }
    linkage_vars: dict = {}
    for role in roles:
        linkage_vars[f"sensor_{role}"] = (
            ["N_PROF"],
            link[role].astype(str),
            {
                "long_name": f"catalog variable naming the {role} sensor per profile",
                "comment": (
                    "value is a SENSOR_* variable name in this file; "
                    "empty where no sensor filled this role"
                ),
            },
        )
        linkage_vars[f"sensor_channel_{role}"] = (
            ["N_PROF"],
            chan[role],
            {
                "long_name": f"raw CNV acquisition channel of the {role} sensor",
                "comment": "-1 where no sensor filled this role",
            },
        )
    return catalog_vars, linkage_vars


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


def _bin_to_grid(
    ds_half: xr.Dataset, p_grid: np.ndarray, dbar: int = 1
) -> dict[str, np.ndarray]:
    """Bin each data variable onto *p_grid* (``dbar``-spaced) by mean per bin.

    Uses numpy bincount — no pandas dependency required.  Each raw sample is
    assigned to its nearest grid centre and every variable becomes the mean of
    the samples in that bin.  With ``dbar=1`` this reproduces the 1-dbar grid
    exactly (``idx == p_bin - p0``); ``dbar=2`` averages each adjacent pressure
    pair, halving the number of levels and reducing per-level sample noise.
    """
    p_raw = ds_half["pressure"].values
    p_bin = np.round(p_raw).astype(int)
    p0 = int(p_grid[0])
    n = len(p_grid)
    # Uniform dbar-wide bins: grid level i collects p_bin in [p0+i*dbar, p0+(i+1)*dbar).
    # With dbar=1 this is exactly ``p_bin - p0`` (the original 1-dbar assignment).
    idx = (p_bin - p0) // dbar

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
    dbar: int = 1,
    sensor_overrides: SensorOverrides | None = None,
) -> bool:
    """Compile per-cast netCDF files into a single profiles.nc on a *dbar*-spaced grid.

    Reads all ``*.nc`` files in nc_dir, splits each cast into downcast and
    upcast halves, bins to a common *dbar*-dbar pressure grid (default 1 dbar),
    and writes a single (N_PROF × pressure) netCDF.  N_PROF is a plain integer
    index (0, 1, 2, …); cast identity is carried by ``cast_number``,
    ``cast_suffix``, and ``cast_direction`` variables.  The bin spacing is
    recorded in the ``pressure_spacing_dbar`` global attribute so the gridding
    can be reconstructed from the output file alone.

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
    dbar:
        Vertical bin spacing (dbar) of the output grid.  Default 1.  Use 2 (or
        more) to average adjacent pressure levels together, reducing per-level
        noise when the raw scan resolution does not justify a 1-dbar grid.

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

    if not isinstance(dbar, int) or dbar < 1:
        raise ValueError(f"dbar must be an integer >= 1, got {dbar!r}.")

    cast_list = _select_cast_files(nc_dir)
    if not cast_list:
        raise ValueError(f"No recognised cast netCDF files found in {nc_dir}.")

    # Pass 1: determine global pressure range for the shared grid
    p_max_global = 0.0
    for _, _suffix, path in cast_list:
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        p_max_global = max(p_max_global, float(ds["pressure"].max()))
        ds.close()
    # p_grid holds the bin LOWER EDGES used for the binning assignment in
    # _bin_to_grid (level i collects rounded pressures [1+i*dbar, 1+(i+1)*dbar)).
    p_grid = np.arange(1, int(p_max_global) + 1, dbar, dtype=np.float32)
    # The reported pressure coordinate is the bin CENTRE, so a binned value sits
    # at the mean depth of the samples it averages rather than (dbar-1)/2 dbar
    # shallow of it.  For dbar=1 the centre equals the edge (unchanged).
    pressure_coord = (p_grid + (dbar - 1) / 2.0).astype(np.float32)

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

    # Per-cast sensor descriptors, in rank order, for the sensor catalog below.
    cast_sensor_records: list[list[dict[str, str]]] = []

    # Pass 2: split and bin each cast
    for rank, (cast_num, cast_suffix, path) in enumerate(cast_list):
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        cast_sensor_records.append(parse_sensor_channels(ds))
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
            binned = _bin_to_grid(ds_half, p_grid, dbar)
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
        "pressure": ("pressure", pressure_coord),
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
    # Sensor catalog + per-profile linkage (dimensionless SENSOR_* variables
    # and sensor_<role>/sensor_channel_<role> on N_PROF).
    catalog_vars, linkage_vars = _build_sensor_catalog(
        cast_sensor_records,
        cast_list,
        n_profiles,
        sensor_overrides or SensorOverrides(),
    )
    data_vars.update(catalog_vars)
    data_vars.update(linkage_vars)

    attrs = {
        "title": f"{cruise} CTD profiles — all casts, downcast + upcast",
        "cruise": cruise,
        "source": f"{len(cast_list)} per-cast netCDF files compiled by ctdcast",
        "pressure_units": "dbar",
        "pressure_spacing_dbar": dbar,
        "pressure_binning": (
            f"mean of raw samples per {dbar}-dbar bin; pressure coordinate is the "
            "bin centre"
        ),
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
