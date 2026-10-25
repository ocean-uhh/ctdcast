"""Map figure builders and the shared map scaffolding (limits, layout, GEBCO panel, ticks)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter, MultipleLocator

from ctdcast.analysis.bathymetry import (
    load_gebco,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.plotters.primitives import (
    nice_colorbar_bounds,
)
from ctdcast.reports._vendored.design_tokens import (
    ANNOT_FS,
    CAST_LABEL_FS,
    pen,
)
from ctdcast.reports._vendored.design_tokens import (
    W_HALF as _W_HALF,
)
from ctdcast.reports._vendored.design_tokens import (
    W_TWO_FIFTHS as _W_TWO_FIFTHS,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes


#: Extra margin (degrees) added when loading GEBCO for map rendering, so
#: downsampled pcolormesh edge cells extend past the axis limits and no white
#: gap shows at the map border.
GEBCO_RENDER_PAD: float = 0.5

# Land fill on cruise maps.  GEBCO cells above sea level fall below the depth
# BoundaryNorm and render transparent, so a light-grey axes background shows
# land as landmass rather than the white page colour.
_LAND_COLOR: str = "#d9d9d9"


def _map_lim(
    lat_lo: float,
    lat_hi: float,
    lon_lo: float,
    lon_hi: float,
    margin: float,
    bounds: tuple[float | None, float | None, float | None, float | None],
) -> tuple[float, float, float, float]:
    """Return (lat_lo, lat_hi, lon_lo, lon_hi) with *bounds* overrides applied."""
    lat_min, lat_max, lon_min, lon_max = bounds
    return (
        lat_min if lat_min is not None else lat_lo - margin,
        lat_max if lat_max is not None else lat_hi + margin,
        lon_min if lon_min is not None else lon_lo - margin,
        lon_max if lon_max is not None else lon_hi + margin,
    )


def square_map_limits(
    yl0: float,
    yl1: float,
    xl0: float,
    xl1: float,
    cos_lat: float,
) -> tuple[float, float, float, float]:
    """Widen longitude so the map is ~square in Mercator proportion.

    Mercator-equivalent width is ``lon_span * cos(lat)``; if the map would be
    taller than wide, longitude is expanded symmetrically to make it roughly
    square.  Shared aspect principle for all cruise maps.

    Parameters
    ----------
    yl0, yl1 : float
        Southern and northern latitude limits (degrees north).
    xl0, xl1 : float
        Western and eastern longitude limits (degrees east).
    cos_lat : float
        Cosine of the map's central latitude.

    Returns
    -------
    tuple of float
        ``(yl0, yl1, xl0, xl1)``; latitudes unchanged, longitudes widened if needed.
    """
    lon_span = xl1 - xl0
    lat_span = yl1 - yl0
    x_width = lon_span * cos_lat
    if lat_span > x_width:
        lon_span_sq = lat_span / cos_lat
        extra = (lon_span_sq - lon_span) / 2
        xl0, xl1 = xl0 - extra, xl1 + extra
    return yl0, yl1, xl0, xl1


def _downsample_gebco_for_map(
    lons: np.ndarray,
    lats: np.ndarray,
    depth: np.ndarray,
    max_pts: int = 400,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Subsample GEBCO arrays to at most *max_pts* per dimension for map rendering.

    Only for use in pcolormesh map backgrounds — not for section bathymetry extraction.
    """
    stride = max(1, max(len(lons) // max_pts, len(lats) // max_pts))
    return lons[::stride], lats[::stride], depth[::stride, ::stride]


# Fixed inch reservations for the deterministic map layout (independent of figure
# width): y-tick labels on the left; gap + bar + tick/label text for the east depth
# colorbar; x-tick labels and each south legend row at the bottom.
_MAP_LEFT_IN: float = 0.55

_MAP_CBAR_GAP_IN: float = 0.12

_MAP_CBAR_W_IN: float = 0.16

_MAP_CBAR_TXT_IN: float = 0.42

_MAP_TOP_IN: float = 0.30  # room for the depth colorbar's "m" title above the bar

_MAP_XTICK_IN: float = 0.30

_MAP_LEGEND_ROW_IN: float = 0.24

_MAP_MARKER_S: float = 18.0  # scatter marker area (pt^2) — every map cast marker

_MAP_MARKER_MS: float = 4.5  # plot marker size (pt), visually matched to _MAP_MARKER_S


def _map_layout(
    fig_w: float,
    xl0: float,
    xl1: float,
    yl0: float,
    yl1: float,
    cos_lat: float,
    *,
    legend_rows: int = 0,
) -> tuple[Any, Any, Any, float]:
    """Lay a cruise map out deterministically; return ``(fig, ax, cax, legend_top)``.

    ``legend_top`` is the figure-fraction y at the top of the reserved south legend
    strip, so a caller can anchor a bottom legend snug under the x-ticks.

    Width is fixed to the display slot (``fig_w`` inches).  Fixed inch margins are
    reserved for the y-tick labels, the east depth colorbar (gap + bar + text), the
    x-tick labels, and any south legend rows.  The map fills the remaining width and its
    height is computed from the (already-framed) extent so it is undistorted — the axes
    and colorbar are then placed by hand, so every map lays out identically regardless of
    legend/colorbar rather than letting matplotlib renegotiate and shrink the map.
    """
    lon_span = max(xl1 - xl0, 1e-6)
    lat_span = max(yl1 - yl0, 1e-6)
    right_in = _MAP_CBAR_GAP_IN + _MAP_CBAR_W_IN + _MAP_CBAR_TXT_IN
    bottom_in = _MAP_XTICK_IN + legend_rows * _MAP_LEGEND_ROW_IN
    map_w_in = max(fig_w - _MAP_LEFT_IN - right_in, 1.0)
    map_h_in = map_w_in * lat_span / (lon_span * cos_lat)  # undistorted
    fig_h = _MAP_TOP_IN + map_h_in + bottom_in
    fig = plt.figure(figsize=(fig_w, fig_h))
    # Explicit add_axes layout — tell the encoder to skip tight_layout (which would
    # both warn and fight these hand-placed axes).
    fig._manual_layout = True
    ax = fig.add_axes(
        [_MAP_LEFT_IN / fig_w, bottom_in / fig_h, map_w_in / fig_w, map_h_in / fig_h]
    )
    cax = fig.add_axes(
        [
            (_MAP_LEFT_IN + map_w_in + _MAP_CBAR_GAP_IN) / fig_w,
            bottom_in / fig_h,
            _MAP_CBAR_W_IN / fig_w,
            map_h_in / fig_h,
        ]
    )
    legend_top = (legend_rows * _MAP_LEGEND_ROW_IN) / fig_h
    return fig, ax, cax, legend_top


def map_panel(
    ax: Axes,
    cax: Axes,
    xl0: float,
    xl1: float,
    yl0: float,
    yl1: float,
    *,
    cfg: ReportConfig,
) -> None:
    """Draw the GEBCO depth field into *ax* and its 'Depth (m)' colorbar into *cax*.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        Map axes to draw the depth field into.
    cax : matplotlib.axes.Axes
        Pre-placed colorbar axes from the map layout; hidden when there is no
        GEBCO to draw, so no empty box remains.
    xl0, xl1 : float
        Western and eastern longitude limits (degrees east).
    yl0, yl1 : float
        Southern and northern latitude limits (degrees north).
    cfg : ReportConfig
        Report configuration; ``gebco_path`` supplies the bathymetry.
    """
    gebco = load_gebco(yl0, yl1, xl0, xl1, margin=GEBCO_RENDER_PAD, path=cfg.gebco_path)
    if gebco is None:
        cax.set_visible(False)
        return
    ax.set_facecolor(_LAND_COLOR)  # masked land cells show this behind the ocean field
    lons_b, lats_b, depth_b = gebco
    lons_b, lats_b, depth_b = _downsample_gebco_for_map(lons_b, lats_b, depth_b)
    d_fin = depth_b[depth_b > 0]
    if not len(d_fin):
        cax.set_visible(False)
        return
    bounds_b = nice_colorbar_bounds(
        float(d_fin.min()), float(np.percentile(d_fin, 98)), n=12, hard_min=0.0
    )
    cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
    norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
    LON2, LAT2 = np.meshgrid(lons_b, lats_b)
    # Mask land (depth <= 0) so those cells are transparent and the grey land
    # facecolor shows through, rather than the colormap's shallowest (near-white)
    # colour that BoundaryNorm otherwise gives values below its first bound.
    depth_ocean = np.ma.masked_less_equal(depth_b, 0.0)
    bathy_pc = ax.pcolormesh(
        LON2,
        LAT2,
        depth_ocean,
        cmap=cmap_b,
        norm=norm_b,
        shading="nearest",
        rasterized=True,
    )
    cb = ax.get_figure().colorbar(bathy_pc, cax=cax, ticks=bounds_b[::2])
    cb.ax.set_title("m", fontsize=ANNOT_FS)  # depth units, above the bar (saves width)
    cb.ax.invert_yaxis()


def _fmt_lon(x: float, _pos: int | None) -> str:
    """Format a longitude tick as degrees East/West (no negative °E)."""
    return f"{abs(x):g}°W" if x < 0 else f"{x:g}°E"


def _fmt_lat(y: float, _pos: int | None) -> str:
    """Format a latitude tick as degrees North/South."""
    return f"{abs(y):g}°S" if y < 0 else f"{y:g}°N"


def _deg_tick_step(lo: float, hi: float, max_ticks: int = 6) -> float:
    """Return a 'nice' degree step (>= 0.1) giving 2..*max_ticks* ticks within [lo, hi].

    Counts ticks that actually land inside the range (not just span/step), so a coarse
    step whose multiples fall only once in-range is rejected — there are always at least
    two ticks.  Prefers the finest step that fits the width cap; if none does, falls back
    to the coarsest step that still yields two ticks.
    """
    max_ticks = max(2, max_ticks)
    steps = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0)

    def _count(step: float) -> int:
        return math.floor(hi / step + 1e-9) - math.ceil(lo / step - 1e-9) + 1

    for step in steps:
        if 2 <= _count(step) <= max_ticks:
            return step
    best = steps[0]
    for step in steps:
        if _count(step) >= 2:
            best = step
        else:
            break
    return best


def _finish_map_axes(
    ax: Axes,
    xl0: float,
    xl1: float,
    yl0: float,
    yl1: float,
    title: str = "",
) -> None:
    """Set hemisphere-formatted lon/lat ticks, limits, grid (no axis labels needed).

    The ``°W``/``°N`` tick suffixes carry the axis meaning, so no x/y label is set.
    """
    ax.xaxis.set_major_formatter(FuncFormatter(_fmt_lon))
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_lat))
    # Tick at "nice" degree multiples no finer than 0.1° (one decimal max), and cap the
    # count to what physically fits: a wide "45.2°W" label clobbers on a narrow (1/3-width)
    # map, so scale the max tick count by the axes' actual inch size.
    fig_w_in, fig_h_in = ax.get_figure().get_size_inches()
    pos = ax.get_position()
    max_x = max(2, int(pos.width * fig_w_in / 0.62))  # ~0.62 in per lon label
    max_y = max(2, int(pos.height * fig_h_in / 0.30))  # ~0.30 in per lat label
    ax.xaxis.set_major_locator(MultipleLocator(_deg_tick_step(xl0, xl1, max_x)))
    ax.yaxis.set_major_locator(MultipleLocator(_deg_tick_step(yl0, yl1, max_y)))
    ax.set_xlim(xl0, xl1)
    ax.set_ylim(yl0, yl1)
    if title:
        ax.set_title(title)
    ax.grid(True)


def draw_station_map_fig(
    lat: float,
    lon: float,
    all_meta: list[dict],
    target_h: float = 4.5,  # noqa: ARG001
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_TWO_FIFTHS,
) -> plt.Figure | None:
    """Return a GEBCO map Figure with all casts and this cast highlighted.

    Parameters
    ----------
    lat, lon : float
        Position of this cast (degrees north, degrees east).
    all_meta : list of dict
        Every cast of the cruise, each with ``lat`` and ``lon``; non-finite
        positions are skipped.
    target_h : float
        Accepted for call-site compatibility and ignored; the layout sets the height.
    cfg : ReportConfig
        Report configuration; ``gebco_path`` supplies the bathymetry and
        ``map_bounds`` can fix the extent.
    width_in : float, default ``W_TWO_FIFTHS``
        Figure width in inches (two-fifths slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when no cast in *all_meta* has a finite position.
    """
    all_lats = [m["lat"] for m in all_meta if np.isfinite(m.get("lat", np.nan))]
    all_lons = [m["lon"] for m in all_meta if np.isfinite(m.get("lon", np.nan))]

    if not all_lats:
        return None

    lat_lo, lat_hi = min(all_lats), max(all_lats)
    lon_lo, lon_hi = min(all_lons), max(all_lons)
    margin = max(0.05, (lat_hi - lat_lo) * 0.1)
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))
    yl0, yl1, xl0, xl1 = _map_lim(
        lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
    )
    yl0, yl1, xl0, xl1 = square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    fig, ax, cax, _ = _map_layout(width_in, xl0, xl1, yl0, yl1, cos_lat)

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    ax.scatter(
        all_lons,
        all_lats,
        s=_MAP_MARKER_S,
        facecolors="white",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=3,
        label="all casts",
    )
    ax.scatter(
        [lon],
        [lat],
        s=_MAP_MARKER_S,
        facecolors="#ff2a2a",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=5,
        label="this cast",
    )
    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    return fig


def draw_cruise_map_fig(
    all_meta: list[dict],
    *,
    target_h: float = 4.0,  # noqa: ARG001
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_HALF,
) -> plt.Figure | None:
    """Return a GEBCO map Figure of all cast positions, without a highlighted cast.

    Parameters
    ----------
    all_meta : list of dict
        Every cast of the cruise, each with ``lat``, ``lon`` and ``cast_num``;
        non-finite positions are skipped.
    target_h : float
        Accepted for call-site compatibility and ignored; the layout sets the height.
    cfg : ReportConfig
        Report configuration; ``gebco_path`` supplies the bathymetry and
        ``map_bounds`` can fix the extent.
    width_in : float, default ``W_HALF``
        Figure width in inches (half slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when no cast in *all_meta* has a finite position.
    """
    lats = [m["lat"] for m in all_meta if np.isfinite(m.get("lat", np.nan))]
    lons = [m["lon"] for m in all_meta if np.isfinite(m.get("lon", np.nan))]
    nums = [
        m["cast_num"]
        for m in all_meta
        if np.isfinite(m.get("lat", np.nan)) and np.isfinite(m.get("lon", np.nan))
    ]
    if not lats:
        return None

    lat_lo, lat_hi = min(lats), max(lats)
    lon_lo, lon_hi = min(lons), max(lons)
    margin = max(0.05, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.12)
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))
    yl0, yl1, xl0, xl1 = _map_lim(
        lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
    )
    yl0, yl1, xl0, xl1 = square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    fig, ax, cax, _ = _map_layout(width_in, xl0, xl1, yl0, yl1, cos_lat)

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    ax.scatter(
        lons,
        lats,
        s=_MAP_MARKER_S,
        facecolors="white",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=3,
    )
    n = len(nums)
    # Label the first and last cast plus every cast number divisible by 10.
    label_idx = sorted(
        set([0, n - 1] + [i for i, cn in enumerate(nums) if int(cn) % 10 == 0])
    )
    for i in label_idx:
        ax.annotate(
            str(nums[i]),
            (lons[i], lats[i]),
            fontsize=CAST_LABEL_FS,
            xytext=(3, 3),
            textcoords="offset points",
        )

    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    return fig


def draw_section_map_fig(
    lats: list[float],
    lons: list[float],
    cast_nums: list[int],
    title: str = "",  # noqa: ARG001  (no longer drawn on the map; kept for callers)
    min_margin: float = 0.03,
    min_margin_lon: float | None = None,
    *,
    fig_w: float = _W_HALF,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a GEBCO map Figure with the section track.

    Parameters
    ----------
    lats, lons : list of float
        Cast positions along the section; non-finite positions are skipped.
    cast_nums : list of int
        Cast numbers, same length as *lats*.
    title : str
        Accepted for call-site compatibility and ignored.
    min_margin : float, default 0.03
        Minimum margin (degrees) around the track; the margin is otherwise a
        fraction of the track extent.
    min_margin_lon : float, optional
        Separate minimum longitude margin (degrees).  When given, latitude and
        longitude margins are set independently and a minimum 0.2° latitude span
        is enforced — used for the co-located time-series location map.
    fig_w : float, default ``W_HALF``
        Figure width in inches.
    cfg : ReportConfig
        Report configuration; ``gebco_path`` supplies the bathymetry and
        ``map_bounds`` can fix the extent.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when no position is finite.
    """
    lats_arr = np.array(lats)
    lons_arr = np.array(lons)
    mask = np.isfinite(lats_arr) & np.isfinite(lons_arr)
    if not mask.any():
        return None
    lats_arr, lons_arr = lats_arr[mask], lons_arr[mask]

    lat_lo, lat_hi = lats_arr.min(), lats_arr.max()
    lon_lo, lon_hi = lons_arr.min(), lons_arr.max()
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))

    if min_margin_lon is not None:
        # Independent lat/lon margins — used for co-located clusters.
        # N-S guard not applied; caller is responsible for aspect.
        data_extent = max(lat_hi - lat_lo, lon_hi - lon_lo)
        margin_lat = max(min_margin, data_extent * 0.30)
        margin_lon = max(min_margin_lon, data_extent * 0.30)
        map_lat_min, map_lat_max, map_lon_min, map_lon_max = cfg.map_bounds
        yl0 = map_lat_min if map_lat_min is not None else lat_lo - margin_lat
        yl1 = map_lat_max if map_lat_max is not None else lat_hi + margin_lat
        xl0 = map_lon_min if map_lon_min is not None else lon_lo - margin_lon
        xl1 = map_lon_max if map_lon_max is not None else lon_hi + margin_lon
        # A single-location region is so small its ticks would need 0.01° (2 decimals,
        # which overflow the axis).  Enforce a minimum LATITUDE span, then square the
        # extent so longitude is expanded to match (Mercator) — done here, before the
        # layout, so the aspect is computed from the final limits.
        _min_lat_span = 0.2
        if yl1 - yl0 < _min_lat_span:
            _cy = 0.5 * (yl0 + yl1)
            yl0, yl1 = _cy - _min_lat_span / 2, _cy + _min_lat_span / 2
        yl0, yl1, xl0, xl1 = square_map_limits(yl0, yl1, xl0, xl1, cos_lat)
    else:
        margin = max(min_margin, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.15)
        yl0, yl1, xl0, xl1 = _map_lim(
            lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
        )
        yl0, yl1, xl0, xl1 = square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    fig, ax, cax, _ = _map_layout(fig_w, xl0, xl1, yl0, yl1, cos_lat)

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    ax.plot(lons_arr, lats_arr, "-", color="white", lw=pen("thick"), zorder=3)
    ax.scatter(
        lons_arr,
        lats_arr,
        s=_MAP_MARKER_S,
        facecolors="white",
        edgecolors="black",
        linewidths=pen("thinnest"),
        zorder=4,
    )
    # A single-location timeseries stacks every cast on one point — label only the
    # first and last so the numbers don't overwrite each other.
    _pts = list(zip(lons_arr, lats_arr, cast_nums, strict=True))
    _show = {0, len(_pts) - 1} if min_margin_lon is not None else set(range(len(_pts)))
    for i, (x, y, n) in enumerate(_pts):
        if i not in _show:
            continue
        ax.annotate(
            str(n),
            (x, y),
            fontsize=CAST_LABEL_FS,
            color="black",
            xytext=(3, 3),
            textcoords="offset points",
        )

    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    return fig


def draw_all_sections_map_fig(
    sections_data: list[dict[str, Any]],
    all_lats: list[float],
    all_lons: list[float],
    legend_outside: bool = False,  # noqa: ARG001  (kept for call-site compatibility)
    *,
    target_h: float = 4.5,  # noqa: ARG001
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_HALF,
) -> plt.Figure | None:
    """Return a GEBCO map Figure showing every section track in its own colour.

    Parameters
    ----------
    sections_data : list of dict
        One dict per section with ``name``, ``color``, ``lats`` and ``lons``.
    all_lats, all_lons : list of float
        Positions of all casts, drawn as a grey background scatter.
    legend_outside : bool
        Accepted for call-site compatibility and ignored; the legend sits in a
        reserved row below the map.
    target_h : float
        Accepted for call-site compatibility and ignored; the layout sets the height.
    cfg : ReportConfig
        Report configuration; ``gebco_path`` supplies the bathymetry and
        ``map_bounds`` can fix the extent.
    width_in : float, default ``W_HALF``
        Figure width in inches (half slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when *sections_data* is empty or no position is finite.
    """
    if not sections_data:
        return None
    all_s_lats = [y for s in sections_data for y in s["lats"]] + list(all_lats)
    all_s_lons = [x for s in sections_data for x in s["lons"]] + list(all_lons)
    finite_lats = [v for v in all_s_lats if np.isfinite(v)]
    finite_lons = [v for v in all_s_lons if np.isfinite(v)]
    if not finite_lats:
        return None

    lat_lo, lat_hi = min(finite_lats), max(finite_lats)
    lon_lo, lon_hi = min(finite_lons), max(finite_lons)
    margin = max(0.05, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.12)
    mean_lat = 0.5 * (lat_lo + lat_hi)
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))
    yl0, yl1, xl0, xl1 = _map_lim(
        lat_lo, lat_hi, lon_lo, lon_hi, margin, bounds=cfg.map_bounds
    )
    yl0, yl1, xl0, xl1 = square_map_limits(yl0, yl1, xl0, xl1, cos_lat)

    ncol = min(len(sections_data), 3)
    legend_rows = math.ceil(len(sections_data) / ncol)
    fig, ax, cax, legend_top = _map_layout(
        width_in, xl0, xl1, yl0, yl1, cos_lat, legend_rows=legend_rows
    )

    map_panel(ax, cax, xl0, xl1, yl0, yl1, cfg=cfg)

    if all_lats:
        fin = [
            np.isfinite(y) and np.isfinite(x)
            for y, x in zip(all_lats, all_lons, strict=True)
        ]
        ax.scatter(
            [x for x, f in zip(all_lons, fin, strict=True) if f],
            [y for y, f in zip(all_lats, fin, strict=True) if f],
            s=_MAP_MARKER_S,
            facecolors="white",
            edgecolors="black",
            linewidths=pen("thinnest"),
            zorder=2,
        )

    for sec in sections_data:
        slats = np.array(sec["lats"])
        slons = np.array(sec["lons"])
        color = sec.get("color", "#555555")
        ax.plot(
            slons,
            slats,
            "-o",
            color=color,
            lw=pen("thicker"),
            ms=_MAP_MARKER_MS,
            markeredgecolor="black",
            markeredgewidth=pen("thinnest"),
            zorder=4,
            label=sec["name"],
        )

    _finish_map_axes(ax, xl0, xl1, yl0, yl1)
    # Legend sits in the reserved south strip (figure coords), full width — never over
    # the map, and the same strip on every all-sections map.
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=ncol,
        framealpha=0.9,
        bbox_to_anchor=(0.5, legend_top),
    )
    return fig
