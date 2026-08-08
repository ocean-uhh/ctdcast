"""Stage 1 — CNV-to-netCDF conversion.

Defines the CtdBackend Protocol, concrete backend implementations, and
``stage1()``, the public function that converts a directory of CNV files
to per-cast netCDF.  To add a new backend implement CtdBackend and add a
branch in ``get_ctd_backend()`` — nothing else changes.

The ``converters`` module re-exports these names for backward compatibility.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import logging
import sys
import warnings
from pathlib import Path
from typing import Protocol

import xarray as xr

from ctdcast.config.parameters import CAST_TAG_WIDTH, CNV_ALIASES, VARIABLES
from ctdcast.writers.netcdf import write as write_nc


# Variables that the reader may produce but that ctdcast does not store.
# Dropped in _normalise() rather than reaching any downstream stage.
_DROP_VARS: frozenset[str] = frozenset(
    {
        "timeJ",  # Julian-day; time coordinate is sufficient
        "timeS",  # elapsed seconds
        "speed_of_sound",
        "density",  # SeaBird computed; ctdcast uses sigma0 via TEOS-10
        "depth",  # derived from pressure; not stored
        "flag",  # SeaBird processing flag; QARTOD _qc variables replace it
    }
)

# Variables with no CCHDO equivalent that ctdcast does not store (derived on demand).
# Also includes seasenselib's oxygen_1/oxygen_2, which are % saturation (from
# sbeox0PS/sbeox1PS), not µmol/kg.  The µmol/kg value (sbox0Mm/Kg) is kept and
# aliased to ctd_oxygen_1 via CNV_ALIASES.
_DERIVE_ON_DEMAND: frozenset[str] = frozenset(
    {"oxsat_1", "sbeox0PS", "sbeox0ps", "oxygen_1", "oxygen_2"}
)

# Variables to keep even if absent from VARIABLES: raw sensor channels useful
# for QC / sensor drift analysis but not plotted directly.  Listed in
# CCHDO_EXCLUDE so they are never written to CCHDO exchange output.
_KEEP_VARS: frozenset[str] = frozenset({"oxygen_raw_1", "oxygen_raw_2"})


def _normalise(ds: xr.Dataset) -> xr.Dataset:
    """Rename variables to ctdcast canonical names and drop non-standard columns.

    Applied between the reader (seasenselib or future hex reader) and the
    ctdcast netCDF writer.  Both readers must produce a Dataset that this
    function can normalise into the same output shape.

    Steps, in order:

    1. Rename variables using :data:`~ctdcast.config.parameters.CNV_ALIASES`
       (keys are lower-cased before lookup).
    2. Drop variables in ``_DROP_VARS`` (SeaBird bookkeeping) and
       ``_DERIVE_ON_DEMAND`` (quantities computed on demand, not stored).
    3. Drop any remaining variables not in
       :data:`~ctdcast.config.parameters.VARIABLES` and not a recognised
       coordinate (``latitude``, ``longitude``, ``time``).
    4. Apply the single-sensor naming rule: when only one sensor of a measured
       type is present, strip the ``_1`` suffix so the variable is plain
       (e.g. ``ctd_temperature_1`` → ``ctd_temperature`` when there is no
       ``ctd_temperature_2``).
    5. Append a ``history`` line recording the ctdcast version and stage.

    Parameters
    ----------
    ds:
        Dataset as returned by the reader (seasenselib or hex reader).

    Returns
    -------
    xr.Dataset
        Normalised Dataset ready for :func:`ctdcast.writers.netcdf.write`.
    """
    from ctdcast._version import __version__

    ds = ds.copy()

    # Step 1: rename via CNV_ALIASES (lowercase key lookup)
    rename_map: dict[str, str] = {}
    for var in list(ds.data_vars):
        target = CNV_ALIASES.get(var.lower())
        if target and target != var:
            rename_map[var] = target
    if rename_map:
        ds = ds.rename(rename_map)

    # Step 1b: handle seasenselib's oxygen_N vars, which may be % saturation,
    # volts, µmol/L, or µmol/kg depending on the CNV column the sensor was on.
    # % saturation and volts are derived-on-demand / discarded.
    # µmol/kg → rename to ctd_oxygen_N (step 4 will strip _1 if single-sensor).
    # µmol/L → convert to µmol/kg using density from the dataset, then rename.
    # Density is available here from seasenselib and is dropped in step 2.
    # Also handles the seasenselib hex-reader names ('oxygen', 'oxygen2') which
    # omit the _N suffix.  Suffix "1" = primary sensor, "2" = secondary.
    for _v in ("oxygen_1", "oxygen_2", "oxygen", "oxygen2"):
        if _v not in ds.data_vars:
            continue
        _suffix = "1" if _v in ("oxygen_1", "oxygen") else "2"
        _target = f"ctd_oxygen_{_suffix}"
        _units = ds[_v].attrs.get("units", "").lower().strip()
        if "umol/kg" in _units or "µmol/kg" in _units:
            ds = ds.rename({_v: _target})
        elif "umol/l" in _units or "µmol/l" in _units:
            if "density" in ds:
                # density from seasenselib is in kg/m³; divide by 1000 to get kg/L,
                # then µmol/L / (kg/L) = µmol/kg.
                rho = ds["density"] / 1000.0
                converted = ds[_v] / rho
                new_attrs = dict(ds[_v].attrs)
                new_attrs["units"] = "umol/kg"
                new_attrs["comment"] = (
                    "converted from umol/l to umol/kg using seasenselib density"
                )
                converted.attrs = new_attrs
                ds = ds.drop_vars([_v]).assign({_target: converted})
            else:
                import warnings

                warnings.warn(
                    f"Oxygen variable {_v!r} is in µmol/L but no density is available "
                    "for conversion.  Variable dropped; reprocess with density present.",
                    stacklevel=3,
                )
                ds = ds.drop_vars([_v])
        # else: % saturation, volts, or unknown — falls through to _DERIVE_ON_DEMAND drop

    # Step 2: drop bookkeeping and derive-on-demand variables
    to_drop = [v for v in ds.data_vars if v in _DROP_VARS or v in _DERIVE_ON_DEMAND]
    if to_drop:
        ds = ds.drop_vars(to_drop)

    # Step 3: drop anything not in VARIABLES, not a coordinate, and not in _KEEP_VARS
    _KEEP_COORDS = {"latitude", "longitude", "time"}
    unknown = [
        v
        for v in ds.data_vars
        if v not in VARIABLES and v not in _KEEP_COORDS and v not in _KEEP_VARS
    ]
    if unknown:
        ds = ds.drop_vars(unknown)

    # Step 4: single-sensor naming — strip _1 when no _2 sibling exists.
    # Only applies to scientific end-product variables (T/S/O); conductivity
    # is an intermediate quantity and keeps its _1 suffix regardless.
    _SUFFIXED_PAIRS = [
        ("ctd_temperature_1", "ctd_temperature_2", "ctd_temperature"),
        ("ctd_salinity_1", "ctd_salinity_2", "ctd_salinity"),
        ("ctd_oxygen_1", "ctd_oxygen_2", "ctd_oxygen"),
    ]
    for v1, v2, plain in _SUFFIXED_PAIRS:
        if v1 in ds.data_vars and v2 not in ds.data_vars:
            ds = ds.rename({v1: plain})

    # Step 5: append history
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"{stamp} ctdcast {__version__} stage1: normalise (CNV → canonical names)"
    prev = ds.attrs.get("history", "")
    ds.attrs["history"] = f"{prev}\n{entry}".lstrip("\n")

    return ds


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
        ds = _normalise(ds)
        write_nc(ds, nc_path)
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


def stage1(
    cnv_dir: Path,
    nc_dir: Path,
    *,
    backend: str = "seasenselib",
    force: bool = False,
    cast_filter: int | list[int] | None = None,
    pattern: str = "*.cnv",
) -> int:
    """Convert per-cast CNV files to netCDF using the specified backend.

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
        If given, convert only files whose stem contains the zero-padded cast number.
        Accepts a single int or a list of ints for multi-cast filtering.
    pattern:
        Filename glob pattern applied within ``cnv_dir`` (default: ``"*.cnv"``).

    Returns
    -------
    int
        Number of files written (skipped files not counted).

    Raises
    ------
    ImportError
        If the chosen backend's package is not installed.
    """
    nc_dir.mkdir(parents=True, exist_ok=True)
    b = get_ctd_backend(backend)

    cnv_files = sorted(cnv_dir.glob(pattern))
    if cast_filter is not None:
        tags = (
            {f"{cast_filter:0{CAST_TAG_WIDTH}d}"}
            if isinstance(cast_filter, int)
            else {f"{c:0{CAST_TAG_WIDTH}d}" for c in cast_filter}
        )
        cnv_files = [p for p in cnv_files if any(t in p.stem for t in tags)]

    n = 0
    for cnv_path in cnv_files:
        nc_path = nc_dir / (cnv_path.stem + ".nc")
        try:
            with warnings.catch_warnings():
                # GSW Nsquared() warns on dp=0 (stationary CTD between 1-second samples).
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


def run(
    cnv_dir: Path,
    nc_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> int:
    """Run stage1 (CNV → netCDF) for explicit input and output directories.

    Called by :func:`ctdcast.processors.process` with ``stage=1`` or
    ``stage="stage1"``.

    Parameters
    ----------
    cnv_dir:
        Directory containing raw SBE CNV files.
    nc_dir:
        Output directory for per-cast netCDF files (created if absent).
    force:
        Overwrite existing NC files.
    dry_run:
        Print what would be converted without writing any files.
    cast_tags:
        If given, process only files whose stem contains one of the zero-padded
        3-digit cast numbers (e.g. ``{"042", "043"}``).
    **kw:
        Passed to :func:`stage1` (e.g. ``backend``, ``pattern``).

    Returns
    -------
    int
        Number of files written (0 for dry_run).
    """
    pattern: str = kw.get("pattern", "*.cnv")  # type: ignore[assignment]
    cnv_files = sorted(cnv_dir.glob(pattern))
    if cast_tags is not None:
        cnv_files = [p for p in cnv_files if any(t in p.stem for t in cast_tags)]

    if dry_run:
        print(f"[dry-run] stage 1: {cnv_dir} → {nc_dir}  ({len(cnv_files)} file(s))")
        for p in cnv_files:
            print(f"  [dry-run] would convert: {p.name}")
        return 0

    cast_filter: list[int] | None = (
        [int(t) for t in sorted(cast_tags)] if cast_tags is not None else None
    )
    n = stage1(cnv_dir, nc_dir, force=force, cast_filter=cast_filter, **kw)
    print(f"stage 1: {n} file(s) written.")
    return n
