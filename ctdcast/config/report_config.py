"""Frozen per-run report configuration, built once and threaded to the plotters.

``ReportConfig`` replaces the runtime-mutable display globals that used to live on
the plotting module (``GEBCO_PATH``, ``CLEAN_SPINES``, the figsizes, the
map bounds, and the colormap overrides).  Building it once in :func:`ctdcast.report`
and passing it down makes rendering order-independent and safe to parallelise —
nothing mutates module state between figures.

``DEFAULT_REPORT_CONFIG`` reproduces the previous module-global defaults exactly, so
a drawer called without a config renders byte-identically to before.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType


def _default_var_cmaps() -> Mapping[str, str]:
    """Return the resolved default ``variable -> colormap`` lookup, read-only.

    The resolver lives in the owned design layer (``reports/design.py``), which
    maps each variable's quantity through the vendored family defaults and
    ctdcast's overrides.  It is imported inside the factory, not at module top, so
    ``config/report_config`` carries no module-level dependency on the reports
    layer.  The returned mapping is read-only so the frozen config cannot be
    mutated through its ``var_cmaps`` field.
    """
    from ctdcast.reports.design import VAR_CMAPS

    return MappingProxyType(dict(VAR_CMAPS))


@dataclasses.dataclass(frozen=True)
class ReportConfig:
    """Immutable display settings for one report render.

    Attributes
    ----------
    gebco_path : Path or None
        GEBCO bathymetry netCDF used for map backgrounds and cast-depth lookups.
        ``None`` renders maps without bathymetry (not an error).
    clean_spines : bool
        Hide the top and right axis spines on profile/scatter axes when ``True``.
    profile_figsize : tuple of float
        Figure size in inches for the T–S density profile figure.
    overview_figsize : tuple of float
        Figure size in inches for the cruise-overview panel figure.
    map_lat_min, map_lat_max, map_lon_min, map_lon_max : float or None
        Explicit map bounds; ``None`` falls back to a data-driven extent.
    var_cmaps : Mapping[str, str]
        Variable-name to colormap-name lookup for discrete colorbars.
    """

    gebco_path: Path | None = None
    clean_spines: bool = True
    profile_figsize: tuple[float, float] = (7.0, 10.0)
    overview_figsize: tuple[float, float] = (9.0, 4.5)
    map_lat_min: float | None = None
    map_lat_max: float | None = None
    map_lon_min: float | None = None
    map_lon_max: float | None = None
    var_cmaps: Mapping[str, str] = dataclasses.field(default_factory=_default_var_cmaps)

    @property
    def map_bounds(
        self,
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """Return ``(lat_min, lat_max, lon_min, lon_max)`` for the map drawers."""
        return (self.map_lat_min, self.map_lat_max, self.map_lon_min, self.map_lon_max)


#: The render defaults — byte-identical to the former ``plots.py`` module globals.
DEFAULT_REPORT_CONFIG = ReportConfig()
