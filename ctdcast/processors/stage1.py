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

from ctdcast.config.parameters import CAST_TAG_WIDTH


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
