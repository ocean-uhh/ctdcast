"""LADCP processing: LDEO ``.mat`` → per-cast netCDF → compiled ``ladcp_profiles.nc``.

Mirrors the CTD pipeline (stage1 ``convert_cast`` → ``build_profiles``):
:func:`convert_ladcp_cast` translates one LDEO ``.mat`` solution to a per-cast
``ladcp_<cast_id>.nc`` on the native 10 m depth grid, with storage dtypes reduced
for file size; the compiler (added in :func:`build_ladcp_profiles`) concatenates
those per-cast files onto a common depth axis.  Schema and rationale:
``.claude/notes/2026-08-17-ladcp-compiled-dataset.md``.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast.config.global_attrs import cruise_global_attrs, expocode_coordinate
from ctdcast.identity import cast_id_from_name, format_cast_id
from ctdcast.processors._warnings import summarise_warnings
from ctdcast.readers.ladcp import read_ladcp_cast
from ctdcast.writers.dtypes import cast_output_dtypes
from ctdcast.writers.netcdf import write as write_nc

#: Bare LADCP stem: zero-padded cast number + optional letter suffix (``004b``).
#: The shared ``cast_id_from_name`` needs a ``_``-prefixed group (CTD names), so
#: LADCP's prefix-less ``NNN.mat`` convention needs this fallback.
_BARE_CAST_RE = re.compile(r"^(\d+)([a-z]*)$")


def _ladcp_cast_id(stem: str) -> tuple[int, str] | None:
    """Return ``(cast_num, cast_suffix)`` from a LADCP ``.mat`` stem, or None.

    Tries the shared prefixed parser first (``*_NNN`` cruise-prefixed names), then
    falls back to a bare ``NNN``/``NNNb`` stem.
    """
    ident = cast_id_from_name(stem)
    if ident is not None:
        return ident
    m = _BARE_CAST_RE.match(stem)
    return (int(m.group(1)), m.group(2)) if m else None


def convert_ladcp_cast(
    mat_path: Path,
    nc_path: Path,
    *,
    cast_num: int,
    cast_suffix: str = "",
    force: bool = False,
) -> bool:
    """Convert one LDEO ``.mat`` to a per-cast LADCP netCDF.

    Parameters
    ----------
    mat_path:
        Path to the LDEO IXv14 ``.mat`` solution.
    nc_path:
        Output ``ladcp_<cast_id>.nc`` path.
    cast_num, cast_suffix:
        Cast identity written into the file (and used to join to ``profiles.nc``).
    force:
        Overwrite an existing *nc_path* if True.

    Returns
    -------
    bool
        True if the file was written; False if skipped (already exists, not forced).
    """
    if nc_path.exists() and not force:
        return False
    ds = read_ladcp_cast(mat_path, cast_num=cast_num, cast_suffix=cast_suffix)
    ds = cast_output_dtypes(ds)
    write_nc(ds, nc_path)
    return True


# ---------------------------------------------------------------------------
# Convert stage — the LADCP parallel of stage1 (raw → per-cast netCDF).
# ---------------------------------------------------------------------------


def run_convert(
    ladcp_dir: Path,
    ladcp_nc_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> int:
    """Convert every LADCP ``.mat`` in *ladcp_dir* to a per-cast netCDF.

    The LADCP parallel of :func:`ctdcast.processors.stage1.run`: discovers the
    ``.mat`` files, derives each cast's identity from its filename, and writes
    ``ladcp_nc_dir/ladcp_<cast_id>.nc``.  Files with no cast number in the stem
    are skipped.  Returns the number of files written (0 for *dry_run*).
    """
    pattern: str = kw.get("ladcp_pattern") or "*.mat"  # type: ignore[assignment]
    mats = [
        (ident, p)
        for p in sorted(ladcp_dir.glob(pattern))
        if (ident := _ladcp_cast_id(p.stem)) is not None
    ]
    if cast_tags is not None:
        mats = [(i, p) for (i, p) in mats if any(t in p.stem for t in cast_tags)]

    if dry_run:
        print(
            f"[dry-run] ladcp convert: {ladcp_dir} → {ladcp_nc_dir}  ({len(mats)} file(s))"
        )
        for _ident, p in mats:
            print(f"  [dry-run] would convert: {p.name}")
        return 0

    ladcp_nc_dir.mkdir(parents=True, exist_ok=True)
    n_written = 0
    # Per-cast data-quality warnings (e.g. blank instrument serials) are captured
    # across the batch and collapsed into one counted summary line per message,
    # so a whole-cruise convert does not emit the same warning hundreds of times.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for (cast_num, cast_suffix), mat_path in mats:
            nc_path = ladcp_nc_dir / f"ladcp_{format_cast_id(cast_num, cast_suffix)}.nc"
            if convert_ladcp_cast(
                mat_path,
                nc_path,
                cast_num=cast_num,
                cast_suffix=cast_suffix,
                force=force,
            ):
                n_written += 1
    summarise_warnings(caught)
    return n_written


# ---------------------------------------------------------------------------
# Compile stage — the LADCP parallel of processors/profiles.py.
# ---------------------------------------------------------------------------


def _select_ladcp_files(ladcp_nc_dir: Path) -> list[Path]:
    """Return the per-cast ``ladcp_*.nc`` files in *ladcp_nc_dir*, sorted."""
    return sorted(ladcp_nc_dir.glob("ladcp_*.nc"))


def build_ladcp_profiles(
    ladcp_nc_dir: Path,
    ladcp_profiles_path: Path,
    *,
    force: bool = False,
    cruise_info: dict | None = None,
) -> bool:
    """Compile per-cast ``ladcp_*.nc`` into ``ladcp_profiles.nc``.

    The LADCP parallel of :func:`ctdcast.processors.profiles.build_profiles`.
    Because each cast is already on a uniform 10 m grid, this is a common-axis
    *alignment* (not a regrid): every profile is reindexed onto the deepest cast's
    depth axis (NaN below its own bottom) and stacked on a new ``N_PROF``
    dimension.  Per-cast scalars become ``N_PROF`` vectors; cruise-common
    provenance is kept in attrs, per-cast-varying provenance is already stored as
    variables.  Returns True if written, False if skipped (existed, not forced).

    ``cruise_info`` (the config ``cruise_info:`` block) supplies discovery
    metadata, people, embargo, and the ship/date for the EXPOCODE coordinate.
    Coverage bounds (lat/lon from the per-cast positions, vertical from the depth
    axis in metres) and the creation time are computed from the data.
    """
    if ladcp_profiles_path.exists() and not force:
        return False
    files = _select_ladcp_files(ladcp_nc_dir)
    if not files:
        return False

    dss = [xr.open_dataset(p, engine="netcdf4").load() for p in files]
    try:
        depth = max((d["depth"] for d in dss), key=lambda x: x.size).values
        nbt = max((d.sizes.get("bottom_track", 0) for d in dss), default=0)
        aligned = []
        for d in dss:
            d = d.reindex(depth=depth)
            if nbt and d.sizes.get("bottom_track", 0) < nbt:
                d = d.reindex(bottom_track=np.arange(nbt))
            aligned.append(d)
        ds_out = xr.concat(aligned, dim="N_PROF", combine_attrs="drop_conflicts")
    finally:
        for d in dss:
            d.close()

    ds_out.attrs["source"] = (
        f"{len(files)} per-cast LADCP netCDF files compiled by ctdcast"
    )

    # EXPOCODE as an N_PROF coordinate (see the CTD builder for the rationale).
    ci = cruise_info or {}
    n_profiles = ds_out.sizes["N_PROF"]
    _expocode_coord = expocode_coordinate(ci, n_profiles)
    if _expocode_coord is not None:
        ds_out["expocode"] = _expocode_coord

    # Derived coverage + authored/provenance/people/platform globals.  The LADCP
    # product is gridded on a depth axis (metres, positive down), not pressure;
    # take the units from the depth variable's own declared units.
    _depth = np.asarray(ds_out["depth"].values, dtype="float64")
    _depth_units = str(ds_out["depth"].attrs.get("units", "m"))
    _depth_ok = _depth.size and bool(np.isfinite(_depth).any())
    ds_out.attrs.update(
        cruise_global_attrs(
            ci,
            lats=ds_out["latitude"].values if "latitude" in ds_out else None,
            lons=ds_out["longitude"].values if "longitude" in ds_out else None,
            vertical_min=float(np.nanmin(_depth)) if _depth_ok else None,
            vertical_max=float(np.nanmax(_depth)) if _depth_ok else None,
            vertical_units=_depth_units,
            times=ds_out["time"].values if "time" in ds_out else None,
            source="ladcp",
        )
    )

    write_nc(cast_output_dtypes(ds_out), ladcp_profiles_path)
    return True


# ---------------------------------------------------------------------------
# Stage entry points — registered in ctdcast.processors.STAGES.
# ---------------------------------------------------------------------------


def run_compile(
    ladcp_nc_dir: Path,
    ladcp_profiles_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cruise_info: dict | None = None,
    **kw: object,  # noqa: ARG001
) -> bool:
    """Build ``ladcp_profiles.nc`` from ``ladcp_*.nc`` in *ladcp_nc_dir*.

    The LADCP parallel of :func:`ctdcast.processors.profiles.run`.
    """
    if dry_run:
        n = len(_select_ladcp_files(ladcp_nc_dir))
        print(
            f"[dry-run] ladcp-profiles: {ladcp_nc_dir} → {ladcp_profiles_path}  ({n} cast(s))"
        )
        return False
    return build_ladcp_profiles(
        ladcp_nc_dir, ladcp_profiles_path, force=force, cruise_info=cruise_info
    )
