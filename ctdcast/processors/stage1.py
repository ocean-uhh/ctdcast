"""Stage 1 — CNV-to-netCDF conversion.

Defines the CtdBackend Protocol, concrete backend implementations, and
``stage1()``, the public function that converts a directory of CNV files
to per-cast netCDF.  To add a new backend implement CtdBackend and add a
branch in ``get_ctd_backend()`` — nothing else changes.

The ``converters`` module re-exports these names for backward compatibility.
"""

from __future__ import annotations

import contextlib
import io
import logging
import sys
import warnings
from pathlib import Path
from typing import Protocol


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


def stage1(
    cnv_dir: Path,
    nc_dir: Path,
    *,
    backend: str = "seasenselib",
    force: bool = False,
    cast_filter: int | None = None,
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
        If given, convert only files whose stem contains ``f"{cast_filter:03d}"``.
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
        tag = f"{cast_filter:03d}"
        cnv_files = [p for p in cnv_files if tag in p.stem]

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


def run(proc_dir: Path, *, force: bool = False, **kw) -> int:
    """Run stage1 for a processing directory.

    Converts CNV files from ``proc_dir/cnv/`` to netCDF in ``proc_dir/nc/``.
    Called by :func:`ctdcast.processors.process` with ``stage=1`` or
    ``stage="stage1"``.

    Parameters
    ----------
    proc_dir:
        Base processing directory.  Input CNV files are read from
        ``proc_dir/cnv/``; NC output goes to ``proc_dir/nc/``.
    force:
        Overwrite existing NC files.
    **kw:
        Passed to :func:`stage1` (e.g. ``backend``, ``cast_filter``).

    Returns
    -------
    int
        Number of files written.
    """
    return stage1(proc_dir / "cnv", proc_dir / "nc", force=force, **kw)
