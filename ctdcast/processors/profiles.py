"""Cruise-level profile compiler: per-cast netCDF → profiles.nc.

Reads all per-cast netCDF files in a directory, splits each into downcast and
upcast halves, bins to a common 1-dbar grid, and writes a single
(N_PROF × pressure) netCDF.  The ``converters`` module re-exports
``build_profiles`` for backward compatibility.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast.analysis.bathymetry import interpolate_bathy_at_casts
from ctdcast.config.global_attrs import (
    CREATION_NOTE,
    aggregate_identity,
    cruise_global_attrs,
    cruise_name,
)
from ctdcast.config.parameters import VARIABLES
from ctdcast.identity import format_cast_id
from ctdcast.processors.history import append_history
from ctdcast.processors.qc import QARTOD_FAIL, QARTOD_SUSPECT
from ctdcast.processors.stage_layout import is_up_to_date, select_best_available
from ctdcast.writers.netcdf import write as _write_nc

# Non-profile columns: seasenselib time-bookkeeping, and per-cast provenance scalars a stage
# may add (``clock_offset_seconds`` from the stage-2 clock applier).  These carry no profile
# dimension, so they must not be treated as griddable channels.
_SKIP_VARS: frozenset[str] = frozenset(
    {"timeJ", "timeS", "pressure", "clock_offset_seconds"}
)


def _read_cast_sensor_catalog(ds: xr.Dataset) -> list[dict]:
    """Return one record per ``SENSOR_*`` catalog entry in a per-cast dataset.

    Reads the catalog stage 1 built: each dimensionless ``SENSOR_<TYPE>_<SERIAL>``
    variable, taking its ``sensor_role`` and ``sensor_channel`` off the entry itself
    (not off the data variables). A sensor with no stored variable — pH, a
    transmissometer — is therefore read exactly like one that has a variable, which
    is what lets the compile aggregate without re-parsing the CNV header. Returns
    ``[]`` when the cast carries no catalog.

    Each record has ``name`` (the catalog variable name, already resolved at stage
    1), ``role``, ``channel`` (int, or ``-1`` if unstated) and ``attrs`` (the full
    entry attributes, verbatim).
    """
    records: list[dict] = []
    for name in ds.variables:
        if not str(name).startswith("SENSOR_"):
            continue
        attrs = dict(ds[name].attrs)
        records.append(
            {
                "name": str(name),
                "role": attrs.get("sensor_role", ""),
                "channel": (
                    int(attrs["sensor_channel"]) if "sensor_channel" in attrs else -1
                ),
                "attrs": attrs,
            }
        )
    return records


# Header-native attributes are physically fixed for a serial: a mismatch across
# casts is a parsing or data error (a serial cannot be recalibrated at sea).
_HEADER_NATIVE_ATTRS: tuple[str, ...] = (
    "sensor_calibration_date",
    "sensor_calibration_slope",
    "sensor_calibration_offset",
)
# Config-resolved attributes are filled from the SensorID registry + overrides at
# stage 1: a mismatch across casts means the casts were stamped under different
# config versions — expected, and fixed by re-running stage 1 or `enrich`, not a
# data error.
_CONFIG_RESOLVED_ATTRS: tuple[str, ...] = (
    "sensor_model",
    "sensor_maker",
    "sensor_model_vocabulary",
    "sensor_maker_vocabulary",
    "sensor_type_vocabulary",
)


def _warn_on_catalog_conflict(
    name: str, prior: dict, attrs: dict, cast_num: int, warned: set
) -> None:
    """Warn when a later cast disagrees with the first on a catalog entry's attributes.

    Two provenances, two meanings: a header-native mismatch (calibration date,
    slope, offset) is a data error; a config-resolved mismatch (model, maker,
    vocabularies) means the casts were stamped under different config versions and
    points at a re-stamp. Each ``(name, attr)`` conflict warns once via *warned*, so
    a persistent disagreement does not re-warn on every cast.
    """
    for a in _HEADER_NATIVE_ATTRS:
        if prior.get(a, "") != attrs.get(a, "") and (name, a) not in warned:
            warned.add((name, a))
            warnings.warn(
                f"Sensor catalog conflict for {name}: {a} {prior.get(a, '')!r} then "
                f"{attrs.get(a, '')!r} (cast {cast_num}); a serial's calibration "
                "cannot change at sea — check CNV parsing.",
                stacklevel=2,
            )
    for a in _CONFIG_RESOLVED_ATTRS:
        if prior.get(a, "") != attrs.get(a, "") and (name, a) not in warned:
            warned.add((name, a))
            warnings.warn(
                f"Sensor catalog for {name}: {a} differs across casts "
                f"({prior.get(a, '')!r} then {attrs.get(a, '')!r}, cast {cast_num}); "
                "casts were stamped under different config versions — re-run stage 1 "
                "or enrich to restamp. Keeping the first cast's value.",
                stacklevel=2,
            )


def _build_sensor_catalog(
    cast_catalogs: list[list[dict]],
    cast_list: list[tuple[int, str, Path, int]],
    n_profiles: int,
) -> tuple[dict, dict]:
    """Aggregate per-cast sensor catalogs into the compiled catalog and linkage.

    Attribute names follow OG1 conventions for interoperability, but this is
    shipboard CTD data and the per-profile linkage has no OG1 equivalent.

    *cast_catalogs* is one :func:`_read_cast_sensor_catalog` result per cast, in the
    same rank order as *cast_list*. Each cast contributes to two profiles (down,
    up), so a cast at rank ``r`` fills profile indices ``2r`` and ``2r+1``. Sensor
    identity, model and calibration were all resolved at stage 1, so this is a merge
    — not a resolver: it reads role and channel off each entry, needs no SensorID
    registry or overrides, and aggregates a variable-less sensor (pH, a
    transmissometer) exactly like one with a variable.

    Returns ``(catalog_vars, linkage_vars)`` as xarray-style
    ``{name: (dims, data, attrs)}`` mappings:

    - **catalog** — one dimensionless ``SENSOR_<TYPE>_<SERIAL>`` variable per
      distinct physical sensor, carrying the entry's attributes (role and channel
      excepted — those become the linkage below).
    - **linkage** — ``sensor_<role>(N_PROF)`` naming the catalog variable in that
      role for each profile, and ``sensor_channel_<role>(N_PROF)`` recording the
      raw acquisition channel.
    """
    catalog: dict[str, dict] = {}
    roles: list[str] = []  # first-appearance order
    link: dict[str, np.ndarray] = {}
    chan: dict[str, np.ndarray] = {}
    warned: set = set()  # (name, attr) conflicts already reported

    for rank, records in enumerate(cast_catalogs):
        cast_num = cast_list[rank][0]
        for rec in records:
            name, role = rec["name"], rec["role"]
            if not role:  # an entry with no role cannot fill a linkage slot
                continue
            attrs = rec["attrs"]
            prior = catalog.get(name)
            if prior is None:
                # role and channel become linkage variables, not entry attributes;
                # sensor_shared_with was cross-linked at stage 1 and is preserved.
                catalog[name] = {
                    k: v
                    for k, v in attrs.items()
                    if k not in ("sensor_role", "sensor_channel")
                }
            else:
                _warn_on_catalog_conflict(name, prior, attrs, cast_num, warned)
            if role not in link:
                roles.append(role)
                link[role] = np.array([""] * n_profiles, dtype=object)
                chan[role] = np.full(n_profiles, -1, dtype=np.int32)
            for k in (rank * 2, rank * 2 + 1):
                link[role][k] = name
                chan[role][k] = rec["channel"]

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


def _select_cast_files(root: Path) -> list[tuple[int, str, Path, int]]:
    """Return sorted ``(cast_num, cast_suffix, path, source_stage)`` per cast.

    Each cast is compiled from its **best-available** stage file — stage 3 if
    present, else stage 2, else stage 1 — so a mixed-stage directory early in a
    cruise compiles honestly, and ``source_stage`` records the stage each profile
    came from.  A plain cast ``NNN`` and its lettered sibling ``NNNb`` are
    distinct events; identity is the ``(number, suffix)`` pair.  An old flat
    ``nc_dir`` (unsuffixed files under the root) is read as stage 1 via the shim
    in :mod:`ctdcast.processors.stage_layout`.
    """
    return [
        (num, suffix, path, stage)
        for (num, suffix), path, stage in select_best_available(root)
    ]


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
        if v in _SKIP_VARS or v.endswith("_qc"):
            continue
        if ds_half[v].shape != ds_half["pressure"].shape:
            continue  # not a per-sample column (e.g. a SENSOR_<type>_<serial> scalar)
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
    cruise_info: dict | None = None,
    refuse_catalog_less: bool = False,
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

    Samples carrying a QARTOD suspect (3) or fail (4) flag on their ``{var}_qc``
    companion are NaN-masked before binning, so flagged data does not enter the bin
    means.  Each science variable records how many finite input samples it carried
    (``qc_input_samples``) and how many were excluded (``qc_excluded_samples``).

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
    cruise_info:
        The ``cruise_info:`` mapping from the cruise config.  Supplies the cruise
        id (so the compiled file is not labelled ``UNK``), the authored discovery
        fields, people, embargo, and the ``ship``/``start_date`` from which the
        EXPOCODE coordinate is derived.  Coverage bounds and creation time are
        computed from the data, not taken from here.
    refuse_catalog_less:
        Policy for a CTD cast whose per-cast file carries no ``SENSOR_*`` catalog
        (it predates sensor provenance).  The default ``False`` is the library
        behaviour: warn once, name the files, and stamp the admission into the
        output so the gap is visible in the file itself.  The pipeline driver
        (``ctdcast process --stage profiles`` and ``ctdcast run``) passes ``True``
        so the compile refuses instead — at the point a product is shipped,
        re-running stage 1 to build the catalog is the actionable fix.

    Returns
    -------
    bool
        True if profiles.nc was written; False if skipped (existed, force=False).

    Raises
    ------
    ValueError
        If no recognised cast files are found in nc_dir, or if
        *refuse_catalog_less* is True and any cast carries no sensor catalog.
    """
    if not isinstance(dbar, int) or dbar < 1:
        raise ValueError(f"dbar must be an integer >= 1, got {dbar!r}.")

    cast_list = _select_cast_files(nc_dir)
    if not cast_list:
        raise ValueError(f"No recognised cast netCDF files found in {nc_dir}.")

    # Skip only if profiles.nc exists AND is newer than every source cast file, so
    # a re-processed cast (a newer stage file) rebuilds the product rather than
    # leaving a stale compile in place.
    if not force and is_up_to_date(profiles_path, [p for _n, _s, p, _st in cast_list]):
        return False

    # Pass 1: determine global pressure range for the shared grid
    p_max_global = 0.0
    for _num, _suffix, path, _stage in cast_list:
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

    # Get variable names and cruise attr from the first file.  The config's
    # cruise_id wins over the per-cast file attr (OdB per-cast files carry no
    # cruise attr, which is why the compiled file used to read "UNK").
    ds0 = xr.open_dataset(cast_list[0][2], engine="netcdf4", decode_timedelta=False)
    # Exclude QARTOD _qc flags: they are per-cast integer flags, not griddable
    # science, so binning would average them into meaningless floats.  profiles.nc
    # carries no _qc today; this keeps that true now that best-available can pick a
    # stage-3 file.  Flag 4 (soak/deck) is honoured per cast in the binning loop
    # below, where the flagged samples are NaN-masked before the bin means.
    # Exclude non-per-sample columns by shape as well as by name: the stage-1
    # SENSOR_<type>_<serial> scalars are dynamic (serial-keyed) so _SKIP_VARS cannot list
    # them.  Without this they would be allocated an (N_PROF, pressure) all-NaN array and
    # written to profiles.nc as bogus variables (only masked today by the catalog being
    # rebuilt under the same names — a coincidence that breaks if stage-1 and compile-time
    # serial-alias resolution disagree).  The compiled catalog is built separately below.
    var_names = [
        v
        for v in ds0.data_vars
        if v not in _SKIP_VARS
        and not v.endswith("_qc")
        and ds0[v].shape == ds0["pressure"].shape
    ]
    _ci = cruise_info or {}
    # The cruise name is resolved later, from the aggregated identity — not here
    # from the first file, and not from config.  `attrs.update(identity)` is what
    # decides the `cruise` attribute, so anything derived from a different source
    # (the title) would disagree with it.
    _cfg_cruise = cruise_name(_ci)
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
    # Which processing stage each cast was compiled from (1/2/3) — casts are at
    # mixed stages early in a cruise, so the compiled file states it per profile.
    source_stages = np.zeros(n_casts, dtype=np.int8)
    # The actual per-cast filename each profile came from — provenance that
    # cast_number+suffix+stage alone cannot reconstruct, and the one thing that
    # distinguishes casts sharing a number (a plain cast vs its lettered sibling).
    source_files: list[str] = [""] * n_casts
    # Lineage: the tracking_id of each per-cast file compiled here (empty for a legacy file
    # that predates the id), so the chain back from profiles.nc is readable per profile.
    source_tracking_ids: list[str] = [""] * n_casts

    # Per-cast sensor catalogs, in rank order, aggregated by _build_sensor_catalog.
    cast_catalogs: list[list[dict]] = []
    # CTD casts whose per-cast file carries no SENSOR_* catalog (predate the catalog).
    catalog_less: list[str] = []

    # Per-cast global attrs, for lifting cruise identity strictly (§4d).
    per_cast_attrs: list[dict[str, str]] = []

    # Pass 2: split and bin each cast
    qc_excluded = False  # did any input carry suspect/fail records to exclude?
    # Per-variable tally of pre-binning samples excluded and the finite-sample
    # denominator they were drawn from, reported at the top of the inventory page.
    # The denominator is the count of finite input samples (not binned points), so
    # the fraction is not distorted by binning's own reduction in point count.
    qc_input_counts: dict[str, int] = {v: 0 for v in var_names}
    qc_dropped_counts: dict[str, int] = {v: 0 for v in var_names}
    for rank, (cast_num, cast_suffix, path, source_stage) in enumerate(cast_list):
        ds = xr.open_dataset(path, engine="netcdf4", decode_timedelta=False)
        per_cast_attrs.append(dict(ds.attrs))
        cast_catalog = _read_cast_sensor_catalog(ds)
        cast_catalogs.append(cast_catalog)
        if not cast_catalog:
            catalog_less.append(path.name)
        # Honour QARTOD flags 3 (suspect) and 4 (fail) from stage 2 (soak/deck) AND
        # stage 3 (gross-range and spike): NaN the flagged samples so they do not
        # enter the bin means.  pressure is in _SKIP_VARS and carries no _qc, so the
        # binning coordinate is untouched; stage-1-only files have no _qc and are
        # unaffected — qc_excluded stays False and the history line does not claim
        # an exclusion that never happened.  Suspect/fail flags are only raised on
        # finite samples, so the excluded count is a subset of the finite count.
        for _v in var_names:
            if _v in ds:
                qc_input_counts[_v] += int(np.isfinite(ds[_v].values).sum())
            _qc = f"{_v}_qc"
            if _qc in ds and _v in ds:
                _is_bad = (ds[_qc] == QARTOD_SUSPECT) | (ds[_qc] == QARTOD_FAIL)
                _n_bad = int(_is_bad.values.sum())
                if _n_bad:
                    qc_excluded = True
                    qc_dropped_counts[_v] += _n_bad
                ds[_v] = ds[_v].where(~_is_bad)
        source_stages[rank] = source_stage
        source_files[rank] = path.name
        source_tracking_ids[rank] = str(ds.attrs.get("tracking_id", ""))
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

    # Refuse early (before the GEBCO lookup and grid expansion) when the caller is
    # the pipeline driver and any cast predates the sensor catalog.  The library
    # default (refuse_catalog_less=False) instead warns and stamps the admission
    # into the output further below; the two paths share the same file list.
    if catalog_less and refuse_catalog_less:
        raise ValueError(
            f"{len(catalog_less)} of {len(cast_list)} cast file(s) carry no sensor "
            f"catalog ({', '.join(catalog_less)}); re-run stage 1 for this cruise "
            "before compiling profiles, so the compiled file records sensor "
            "provenance for every cast."
        )

    # Expand per-cast scalars to per-profile (same value for down and up of each cast)
    max_pressure_prof = np.repeat(max_pressures, 2)
    gebco_per_cast = interpolate_bathy_at_casts(
        list(lats_at_max_p), list(lons_at_max_p), path=gebco_path
    )
    if gebco_per_cast is None:
        gebco_per_cast = np.full(n_casts, np.nan, dtype=np.float32)
    gebco_depth_prof = np.repeat(gebco_per_cast.astype(np.float32), 2)
    source_stage_prof = np.repeat(source_stages, 2)
    source_file_prof = np.repeat(np.array(source_files), 2)
    source_tid_prof = np.repeat(np.array(source_tracking_ids), 2)

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
            {
                **(
                    {"coordinates": "latitude longitude"}
                    if v in VARIABLES
                    else {"long_name": v, "coordinates": "latitude longitude"}
                ),
                # Provenance of the soak/deck + gross-range/spike exclusion: how many
                # finite input samples this variable carried and how many were dropped
                # (flag 3 or 4) before binning.  Denominator is pre-binning samples so
                # the fraction is not confounded by binning's own point reduction.
                "qc_input_samples": np.int64(qc_input_counts[v]),
                "qc_excluded_samples": np.int64(qc_dropped_counts[v]),
            },
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
            "source_stage": (
                ["N_PROF"],
                source_stage_prof,
                {
                    "long_name": "processing stage of the source file for this profile",
                    # int8 + flag_values/flag_meanings matches the QARTOD idiom in
                    # processors/qc.py that writers/netcdf.py already emits.
                    "flag_values": np.array([0, 1, 2, 3], dtype=np.int8),
                    "flag_meanings": "unknown converted soak_flagged qc_calibrated",
                    "comment": (
                        "Best-available stage for this cast at compile time: "
                        "1 = raw converted, 2 = soak/deck flagged, 3 = QC and "
                        "calibration. 0 = unknown: an unsuffixed flat file assumed "
                        "to be stage 1 by the compatibility shim, which does not "
                        "state its own stage. Casts can be at mixed stages early "
                        "in a cruise."
                    ),
                },
            ),
            "source_file": (
                ["N_PROF"],
                source_file_prof,
                {
                    "long_name": "source per-cast filename this profile was compiled from",
                    "comment": (
                        "Filename only (see the global 'source' attribute for the "
                        "naming convention); the absolute root is deliberately not "
                        "recorded, as it is a local, perishable path. Distinguishes "
                        "casts that share a number — e.g. a plain cast and its "
                        "lettered sibling."
                    ),
                },
            ),
            "source_tracking_id": (
                ["N_PROF"],
                source_tid_prof,
                {
                    "long_name": "tracking_id of the per-cast file this profile was compiled from",
                    "comment": (
                        "The compiled file has its own tracking_id (global attr); this "
                        "names the specific instance of each source cast file, so the "
                        "lineage back to the CNV is readable per profile. Empty for a "
                        "source file that predates the tracking_id."
                    ),
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
    # and sensor_<role>/sensor_channel_<role> on N_PROF).  Sensor provenance is
    # resolved at stage 1 now, so this aggregates the per-cast catalogs rather
    # than re-resolving from headers.
    catalog_vars, linkage_vars = _build_sensor_catalog(
        cast_catalogs,
        cast_list,
        n_profiles,
    )
    data_vars.update(catalog_vars)
    data_vars.update(linkage_vars)

    # Identity (cruise, platform_*, expocode) lifted from the per-cast files,
    # strictly: constant across casts → lifted; varying → error (two cruises in
    # one directory); absent → cruise_info fallback with a warning.  This is the
    # authority for identity at compile — config is no longer re-derived here.
    identity = aggregate_identity(per_cast_attrs, _ci)
    # `identity` is authoritative — it is what lands in `attrs` below — so the
    # title is built from it, not from config.  Deriving the two separately is how
    # a file ended up titled for one cruise and attributed to another, behind a
    # warning that announced the opposite resolution.
    _lifted_cruise = identity.get("cruise")
    if _cfg_cruise and _lifted_cruise and str(_cfg_cruise) != str(_lifted_cruise):
        warnings.warn(
            f"the per-cast files say this is cruise {str(_lifted_cruise)!r}, but "
            f"cruise_info says {str(_cfg_cruise)!r}; using the files' value, "
            f"because a stage file records the cruise the cast was actually taken "
            f"on. If the config is the correct one, re-run stage 1 to restamp "
            f"the per-cast files.",
            stacklevel=2,
        )
    cruise = str(_lifted_cruise or _cfg_cruise or "UNK")

    # Base provenance attrs, then the ACDD/derived/authored layer on top (which
    # upgrades Conventions to include ACDD-1.3 and adds coverage bounds, people,
    # embargo, and platform fields).  Coverage is computed from the data here so
    # the bounding box brackets every station rather than copying one cast up.
    attrs = {
        "title": f"{cruise} CTD profiles — all casts, downcast + upcast",
        "cruise": cruise,
        "source": (
            f"{len(cast_list)} per-cast netCDF files compiled by ctdcast from "
            "stageN/<stem>_stageN.nc (per-profile source_file records each name)"
        ),
        "pressure_units": "dbar",
        "pressure_spacing_dbar": dbar,
        "Conventions": "CF-1.13",
    }
    # Guard the reductions: an empty grid or all-NaN max-pressure would make
    # np.nanmin/nanmax warn and emit a NaN bound; pass None so it is omitted.
    _v_min = (
        float(np.nanmin(pressure_coord))
        if pressure_coord.size and np.isfinite(pressure_coord).any()
        else None
    )
    _v_max = (
        float(np.nanmax(max_pressure_prof))
        if np.isfinite(max_pressure_prof).any()
        else None
    )
    attrs.update(
        cruise_global_attrs(
            _ci,
            lats=lats,
            lons=lons,
            vertical_min=_v_min,
            vertical_max=_v_max,
            vertical_units=VARIABLES["pressure"]["units"],
            times=time_starts,
            source="ctd",
            # The identifier's grid token must reflect the ACTUAL bin spacing used
            # here (build_profiles' own `dbar`), not the config default — otherwise
            # a 2-dbar file is labelled `..._ctd_1dbar` while pressure_spacing_dbar
            # correctly says 2.  grid_token reads processing.profiles_dbar.
            config={"processing": {"profiles_dbar": dbar}},
        )
    )
    # Per-cast-sourced identity is authoritative over the config `cruise` set
    # above and over the identity cruise_global_attrs still emits, so a compiled
    # file states the cruise its casts actually came from (and errors if they
    # disagree).
    attrs.update(identity)

    # Provenance: what wrote the file, then what it did.  Both go through
    # `append_history`, so neither can be clobbered by a layer that returns a
    # `history` key of its own — `cruise_global_attrs` no longer emits one.
    append_history(attrs, CREATION_NOTE, stage="create")

    # Record the binning operation in history (pressure_spacing_dbar
    # keeps the machine-readable scalar), so the treatment is reconstructable from
    # the compiled file alone.  Only claim the soak/deck exclusion when it actually
    # removed something — stage-1-only inputs carry no flags to exclude.
    _note = (
        f"compiled {len(cast_list)} casts; mean of raw samples per {dbar}-dbar "
        "bin, pressure coordinate is the bin centre"
    )
    if qc_excluded:
        _note += (
            "; excluded QARTOD flag 3 (suspect) and flag 4 (fail) records "
            "(soak/deck and gross-range/spike) before binning"
        )
    append_history(attrs, _note, stage="profiles")

    # A per-cast file with no SENSOR_* catalog predates sensor provenance.  With
    # refuse_catalog_less=False (the library default) build_profiles does not
    # refuse — it warns once, names the files, and stamps the admission into the
    # output so the gap is visible in the file itself, not only in a log.  The
    # process/run CLI passes refuse_catalog_less=True and so raised above instead:
    # re-running stage 1 is the actionable fix at the point a product is shipped.
    if catalog_less:
        warnings.warn(
            f"{len(catalog_less)} of {len(cast_list)} cast file(s) carry no sensor "
            f"catalog ({', '.join(catalog_less)}); their sensor provenance is absent "
            "from profiles.nc. Re-run stage 1 for this cruise to build it.",
            stacklevel=2,
        )
        attrs["sensor_catalog"] = (
            f"absent for {len(catalog_less)} of {len(cast_list)} casts — those "
            "per-cast files predate the catalog; re-run stage 1"
        )

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
            f"profiles: skipped (up to date; use --force to rebuild): {profiles_path}"
        )
    return result
