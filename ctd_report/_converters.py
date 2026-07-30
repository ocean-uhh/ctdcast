"""Backend protocol and dispatch for CTD data conversion.

Defines the CtdBackend Protocol, concrete backend implementations, and the
public API functions (convert_ctd_files, build_profiles) that cli/convert.py
calls. Adding a new backend means implementing CtdBackend and adding a branch
in get_ctd_backend() — nothing else changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol


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


class _BuiltinBackend:
    """Built-in CNV to netCDF converter (not yet implemented)."""

    def convert_cast(
        self,
        cnv_path: Path,
        nc_path: Path,
        *,
        force: bool = False,
    ) -> bool:
        """Convert one CNV file using the built-in converter."""
        raise NotImplementedError(
            "Built-in CNV converter is not yet implemented. "
            "Use --backend seasenselib if it is installed, or convert files "
            "manually and point data.nc_dir at the result directory."
        )


class _SeasenselibBackend:
    """CTD backend that delegates to the seasenselib package."""

    def __init__(self) -> None:
        """Initialise; raises ImportError if seasenselib is not installed."""
        try:
            import seasenselib as _sl  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "seasenselib backend requested but the package is not installed. "
                "Install it with: pip install seasenselib"
            ) from exc
        import seasenselib as _sl

        self._sl = _sl

    def convert_cast(
        self,
        cnv_path: Path,
        nc_path: Path,
        *,
        force: bool = False,
    ) -> bool:
        """Convert one CNV file using seasenselib.

        TODO: replace the placeholder call below with the confirmed seasenselib
        API once its interface has been verified against the installed version.
        """
        if nc_path.exists() and not force:
            return False
        # Placeholder — fill in once seasenselib's convert API is confirmed.
        raise NotImplementedError(
            "seasenselib backend: the API call has not been confirmed yet. "
            "Implement _SeasenselibBackend.convert_cast() once the "
            "seasenselib interface is verified."
        )


_BACKENDS: dict[str, type] = {
    "builtin": _BuiltinBackend,
    "seasenselib": _SeasenselibBackend,
}


def get_ctd_backend(name: str) -> CtdBackend:
    """Return a CtdBackend instance for the given backend name.

    Parameters
    ----------
    name:
        ``"builtin"`` or ``"seasenselib"``.

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
    backend: str = "builtin",
    force: bool = False,
    cast_filter: Optional[int] = None,
) -> int:
    """Convert per-cast CNV files to netCDF using the specified backend.

    Public API — analogous to generate_ctd_report() in _index.py.

    Parameters
    ----------
    cnv_dir:
        Directory containing raw SBE CNV files.
    nc_dir:
        Output directory for per-cast netCDF files (created if absent).
    backend:
        Backend name: ``"builtin"`` (default) or ``"seasenselib"``.
    force:
        Overwrite existing netCDF files.
    cast_filter:
        If given, convert only files whose stem contains ``f"{cast_filter:03d}"``.

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

    cnv_files = sorted(cnv_dir.glob("*.cnv"))
    if cast_filter is not None:
        tag = f"{cast_filter:03d}"
        cnv_files = [p for p in cnv_files if tag in p.stem]

    n = 0
    for cnv_path in cnv_files:
        nc_path = nc_dir / (cnv_path.stem + ".nc")
        if b.convert_cast(cnv_path, nc_path, force=force):
            n += 1
    return n


def build_profiles(
    nc_dir: Path,
    profiles_path: Path,
    *,
    force: bool = False,
) -> bool:
    """Compile per-cast netCDF files into a single profiles.nc on a 1-dbar grid.

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
    NotImplementedError
        This function is not yet implemented; the logic lives in the cruise repo.
    """
    if profiles_path.exists() and not force:
        return False
    raise NotImplementedError(
        "build_profiles() is not yet implemented in this package. "
        "Run cnv_build_profiles.py from the cruise repo to build profiles.nc."
    )
