"""Public reader shim for SBE CNV files.

Delegates to the active CtdBackend so callers are insulated from which
library does the actual parsing.  A future hexadecimal-reader backend
will be swappable here without touching any caller.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import xarray as xr

from ctdcast.processors.stage1 import get_ctd_backend


def read(cnv_path: Path, *, backend: str = "seasenselib") -> xr.Dataset:
    """Read a single SBE CNV file and return an xarray Dataset.

    The Dataset is loaded into memory before the temporary netCDF file is
    removed; the returned object has no open file handles.

    Parameters
    ----------
    cnv_path:
        Path to the raw SBE CNV file.
    backend:
        Backend name (currently only ``"seasenselib"``).

    Returns
    -------
    xr.Dataset
        In-memory Dataset with variables as produced by the backend.

    Raises
    ------
    ImportError
        If the requested backend package is not installed.
    FileNotFoundError
        If cnv_path does not exist.
    """
    if not cnv_path.exists():
        raise FileNotFoundError(cnv_path)
    b = get_ctd_backend(backend)
    with tempfile.TemporaryDirectory() as tmpdir:
        nc_path = Path(tmpdir) / (cnv_path.stem + ".nc")
        b.convert_cast(cnv_path, nc_path, force=True)
        ds = xr.open_dataset(nc_path, engine="netcdf4").load()
    return ds
