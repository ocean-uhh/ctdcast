"""Base64 PNG encoders — thin wrappers that render a Figure for a page.

Each ``_make_*_b64`` builds a figure via a ``draw_*_fig`` in one of the
``ctdcast.plotters`` figure modules and encodes it with :func:`render_b64`.
``_make_all_sections_map_b64`` uses a custom wrapper instead: it still delegates
drawing to its ``draw_*_fig`` but needs a post-``tight_layout`` adjustment.
``_make_ladcp_section_b64`` returns a list of :class:`RenderedPanel` (U and V), so
it calls :func:`render_b64` once per component against ``draw_ladcp_section_fig``.
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.plotters.ladcp import (
    draw_ladcp_bottomtrack_fig,
    draw_ladcp_overview_fig,
    draw_ladcp_section_fig,
    ladcp_overview_grid,
    ladcp_section_grid,
)
from ctdcast.plotters.maps import (
    draw_all_sections_map_fig,
    draw_cruise_map_fig,
    draw_section_map_fig,
    draw_station_map_fig,
)
from ctdcast.plotters.profiles import (
    draw_aux_profiles_fig,
    draw_ct_sa_sigma0_fig,
    draw_qc_histogram_fig,
    draw_stability_fig,
    draw_ts_density_fig,
    draw_ts_diagram_fig,
    draw_ts_updown_fig,
)
from ctdcast.plotters.sections import (
    draw_overview_panel_fig,
    draw_section_fig,
    draw_section_ts_histogram_fig,
    draw_section_ts_o2_fig,
    draw_section_ts_profiles_fig,
    draw_ts_diagram_timeseries_fig,
)
from ctdcast.plotters.timeseries import (
    draw_pressure_time_fig,
    draw_sensor_diff_fig,
    draw_timeseries_fig,
    draw_updown_diff_fig,
)

# render_b64 is imported from _figdebug (a package-local wrapper around the vendored
# encoder) so figures are geometry-recorded when CTDCAST_REPORT_DEBUG is set; it delegates
# straight to the encoder when off.
from ctdcast.reports._figdebug import record as _figdebug_record
from ctdcast.reports._figdebug import render_b64
from ctdcast.reports._vendored import design_tokens as report_tokens
from ctdcast.reports._vendored.figure_png import (
    _fig_to_base64,
    record_source,
    source_for,
)


def _width_kw(width_in: float | None) -> dict[str, float]:
    """Return ``{"width_in": width_in}``, or ``{}`` to keep the draw function's default width."""
    return {} if width_in is None else {"width_in": width_in}


def _slot_width(slot: str) -> float:
    """Return the width in inches of the display *slot* (a ``SLOTS`` key)."""
    return report_tokens.SLOTS[slot][1]


@dataclasses.dataclass(frozen=True)
class RenderedPanel:
    """A rendered figure plus the layout metadata the HTML template needs."""

    b64: str | None
    """Base64-encoded PNG string, or ``None`` when the figure could not be rendered."""
    title: str = ""
    """Long descriptive title (used in ``alt`` attributes and headings)."""
    short: str = ""
    """Short label used in ``<figcaption>`` elements (e.g. ``"CT"``, ``"U"``)."""
    figsize: tuple[float, float] | None = None
    """Figure dimensions ``(width, height)`` in inches, or ``None`` when not recorded."""
    slot: str | None = None
    """``SLOTS`` key (e.g. ``"full"``) the PNG was drawn for and is shown in, or ``None``."""


def _make_ts_density_b64(
    ds: xr.Dataset,
    ladcp_path: Path | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.profiles.draw_ts_density_fig` (CT/SA/σ₀, with LADCP U/V when *ladcp_path* is given)."""
    return render_b64(draw_ts_density_fig, ds, ladcp_path, cfg=cfg)


def _make_ts_diagram_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of a T-S diagram colored by O₂ saturation."""
    return render_b64(draw_ts_diagram_fig, ds, cfg=cfg, **_width_kw(width_in))


def _make_stability_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of N² and Turner angle (2-panel)."""
    return render_b64(draw_stability_fig, ds, cfg=cfg, **_width_kw(width_in))


def _make_qc_histogram_b64(
    nc_path: Path,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of per-variable data-value distributions with QC thresholds."""
    return render_b64(
        draw_qc_histogram_fig, nc_path, optional=True, cfg=cfg, **_width_kw(width_in)
    )


def _make_aux_profiles_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of O₂ sat, fluorescence, turbidity profiles (downcast + pale upcast)."""
    return render_b64(
        draw_aux_profiles_fig, ds, optional=True, cfg=cfg, **_width_kw(width_in)
    )


def _make_ct_sa_sigma0_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.profiles.draw_ct_sa_sigma0_fig`."""
    return render_b64(draw_ct_sa_sigma0_fig, ds, cfg=cfg, **_width_kw(width_in))


def _make_ts_updown_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of CT–SA scatter: downcast in blue, upcast in red, σ₀ contours."""
    return render_b64(draw_ts_updown_fig, ds, cfg=cfg, **_width_kw(width_in))


def _make_station_map_b64(
    lat: float,
    lon: float,
    all_meta: list[dict],
    target_h: float = 4.5,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.maps.draw_station_map_fig`; *target_h* is accepted for call-site compatibility and ignored."""
    return render_b64(
        draw_station_map_fig,
        lat,
        lon,
        all_meta,
        target_h,
        cfg=cfg,
        **_width_kw(width_in),
    )


def _make_cruise_map_b64(
    all_meta: list[dict],
    *,
    target_h: float = 4.0,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.maps.draw_cruise_map_fig`."""
    return render_b64(
        draw_cruise_map_fig, all_meta, target_h=target_h, cfg=cfg, **_width_kw(width_in)
    )


def _make_section_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    x_vals: np.ndarray,
    x_label: str,
    title: str = "",
    style: str = "pcolormesh",
    bathy_depths: np.ndarray | None = None,
    bathy_x: np.ndarray | None = None,
    cast_labels: list | None = None,
    vmin: float | None = None,
    vmax: float | None = None,
    figsize: tuple[float, float] | None = None,
    optional: bool = False,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.sections.draw_section_fig`; *optional* marks a variable that may be absent."""
    return render_b64(
        draw_section_fig,
        ds_prof,
        var,
        label,
        x_vals,
        x_label,
        title=title,
        style=style,
        bathy_depths=bathy_depths,
        bathy_x=bathy_x,
        cast_labels=cast_labels,
        vmin=vmin,
        vmax=vmax,
        figsize=figsize,
        optional=optional,
        cfg=cfg,
    )


def _make_ladcp_section_b64(
    cast_nums: list[int],
    x_vals: np.ndarray,
    x_label: str,
    ladcp_dir: Path,
    lats: list[float] | None = None,
    lons: list[float] | None = None,
    figsize: tuple[float, float] | None = None,
    ladcp_pattern: str | None = None,
    style: str = "pcolormesh",
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> list[RenderedPanel]:
    """Grid the section's LADCP casts once and encode its U and V panels; ``[]`` when fewer than two casts have LADCP."""
    try:
        grid = ladcp_section_grid(
            cast_nums,
            x_vals,
            ladcp_dir,
            lats=lats,
            lons=lons,
            ladcp_pattern=ladcp_pattern,
            cfg=cfg,
        )
    except Exception as exc:
        if report_tokens.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            "ladcp_section_grid failed; LADCP section panels omitted: "
            f"{type(exc).__name__}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return []
    if grid is None:
        return []
    panels: list[RenderedPanel] = []
    for component, panel_title, panel_short in (
        ("U", "U velocity (east +)", "U"),
        ("V", "V velocity (north +)", "V"),
    ):
        b64 = render_b64(
            draw_ladcp_section_fig,
            cast_nums,
            x_vals,
            x_label,
            ladcp_dir,
            component=component,
            lats=lats,
            lons=lons,
            figsize=figsize,
            ladcp_pattern=ladcp_pattern,
            style=style,
            cfg=cfg,
            grid=grid,
            optional=True,
        )
        if b64 is not None:
            panels.append(RenderedPanel(b64=b64, title=panel_title, short=panel_short))
    return panels


def _make_ladcp_overview_b64(
    ds_ladcp: xr.Dataset,
    cast_groups: dict[str, list[int]] | None = None,
    style: str = "pcolormesh",
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> list[RenderedPanel]:
    """Grid ``ladcp_profiles.nc`` once and encode the cruise U and V overview panels; ``[]`` when fewer than two casts have velocity."""
    try:
        grid = ladcp_overview_grid(ds_ladcp, cfg=cfg)
    except Exception as exc:
        if report_tokens.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            "ladcp_overview_grid failed; LADCP overview panels omitted: "
            f"{type(exc).__name__}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return []
    if grid is None:
        return []
    panels: list[RenderedPanel] = []
    for component, panel_title in (
        ("U", "U velocity (east +)"),
        ("V", "V velocity (north +)"),
    ):
        b64 = render_b64(
            draw_ladcp_overview_fig,
            grid,
            component,
            cast_groups,
            style,
            cfg=cfg,
            **_width_kw(width_in),
        )
        if b64 is not None:
            panels.append(RenderedPanel(b64=b64, title=panel_title, short=component))
    return panels


def _make_section_ts_profiles_b64(
    ds_prof: xr.Dataset,
    x_vals: np.ndarray,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.sections.draw_section_ts_profiles_fig`."""
    return render_b64(
        draw_section_ts_profiles_fig, ds_prof, x_vals, cfg=cfg, **_width_kw(width_in)
    )


def _make_ts_diagram_timeseries_b64(
    ds_ts: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.sections.draw_ts_diagram_timeseries_fig`."""
    return render_b64(
        draw_ts_diagram_timeseries_fig, ds_ts, cfg=cfg, **_width_kw(width_in)
    )


def _make_section_ts_histogram_b64(
    ds_prof: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of a CT–SA 2-D count histogram (log₁₀ colour) for section profiles."""
    return render_b64(
        draw_section_ts_histogram_fig, ds_prof, cfg=cfg, **_width_kw(width_in)
    )


def _make_section_ts_o2_b64(
    ds_prof: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of CT–SA histogram coloured by median O₂ saturation per bin."""
    return render_b64(
        draw_section_ts_o2_fig, ds_prof, optional=True, cfg=cfg, **_width_kw(width_in)
    )


def _make_section_map_b64(
    lats: list[float],
    lons: list[float],
    cast_nums: list[int],
    title: str = "",
    min_margin: float = 0.03,
    min_margin_lon: float | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.maps.draw_section_map_fig`; *width_in* is the slot's width."""
    return render_b64(
        draw_section_map_fig,
        lats,
        lons,
        cast_nums,
        title=title,
        min_margin=min_margin,
        min_margin_lon=min_margin_lon,
        cfg=cfg,
        **_width_kw(width_in),
    )


def _make_overview_panel_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    bathy_depths: np.ndarray | None = None,
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    cast_groups: dict[str, list[int]] | None = None,
    optional: bool = False,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.sections.draw_overview_panel_fig`; *optional* marks a variable that may be absent."""
    return render_b64(
        draw_overview_panel_fig,
        ds_prof,
        var,
        label,
        bathy_depths=bathy_depths,
        style=style,
        vmin=vmin,
        vmax=vmax,
        cast_groups=cast_groups,
        optional=optional,
        cfg=cfg,
        **_width_kw(width_in),
    )


def _make_all_sections_map_b64(
    sections_data: list[dict[str, Any]],
    all_lats: list[float],
    all_lons: list[float],
    legend_outside: bool = False,
    *,
    target_h: float = 4.5,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.maps.draw_all_sections_map_fig` without ``tight_layout`` or cropping (the map lays itself out at a fixed width)."""
    fig_result = None
    try:
        with plt.style.context(str(report_tokens.MPLSTYLE_PATH)):
            fig_result = draw_all_sections_map_fig(
                sections_data,
                all_lats,
                all_lons,
                legend_outside,
                target_h=target_h,
                cfg=cfg,
                **_width_kw(width_in),
            )
            if fig_result is None:
                return None
            # draw_all_sections_map_fig lays the figure out deterministically
            # (fixed slot width, colorbar + south legend in reserved space), so save
            # the full canvas — no tight_layout (which would warn and re-flow the
            # hand-placed axes) and no bbox crop (which would break the slot width).
            b64 = _fig_to_base64(fig_result)
            _figdebug_record(b64, "_make_all_sections_map_b64", fig_result)
            record_source(b64, source_for(draw_all_sections_map_fig))
            return b64
    except Exception:
        if report_tokens.RAISE_ON_PLOT_ERROR:
            raise
        warnings.warn(
            "_make_all_sections_map_b64 failed; panel omitted",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    finally:
        if fig_result is not None:
            plt.close(fig_result)


def _make_timeseries_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    width_in: float | None = None,
    optional: bool = False,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.timeseries.draw_timeseries_fig`; *optional* marks a variable that may be absent."""
    return render_b64(
        draw_timeseries_fig,
        ds_prof,
        var,
        label,
        style=style,
        vmin=vmin,
        vmax=vmax,
        width_in=width_in,
        optional=optional,
        cfg=cfg,
    )


def _make_sensor_diff_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.timeseries.draw_sensor_diff_fig`; None without a secondary sensor."""
    return render_b64(
        draw_sensor_diff_fig, ds, optional=True, cfg=cfg, **_width_kw(width_in)
    )


def _make_pressure_time_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Return a base64 PNG of pressure vs elapsed time (cast trajectory + bottle stops)."""
    return render_b64(draw_pressure_time_fig, ds, cfg=cfg, **_width_kw(width_in))


def _make_updown_diff_b64(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.timeseries.draw_updown_diff_fig`; None when the down/up overlap is under 10 dbar."""
    return render_b64(draw_updown_diff_fig, ds, cfg=cfg, **_width_kw(width_in))


def _make_ladcp_bottomtrack_b64(
    ladcp_path: Path | None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float | None = None,
) -> str | None:
    """Encode :func:`~ctdcast.plotters.ladcp.draw_ladcp_bottomtrack_fig`; None without a bottom-track solution."""
    if ladcp_path is None:
        return None
    return render_b64(
        draw_ladcp_bottomtrack_fig,
        ladcp_path,
        optional=True,
        cfg=cfg,
        **_width_kw(width_in),
    )
