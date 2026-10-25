"""Time-series figure builders: repeat-station series, pressure–time, clock offset, sensor and up/down differences."""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctdcast.analysis.derive import derive_teos10 as add_teos10
from ctdcast.config.parameters import (
    VAR_COLORS,
    vlabel,
    vunit,
)
from ctdcast.config.report_config import DEFAULT_REPORT_CONFIG, ReportConfig
from ctdcast.plotters.primitives import (
    _TS_COLORS,
    _UPCAST_COLOR,
    _discrete_norm,
    hide_outer_spines,
    nice_colorbar_ticks,
    sigma0_isopycnals,
    unit_colorbar,
)
from ctdcast.processors.stage2 import split_cast
from ctdcast.reports._vendored.design_tokens import (
    CAST_LABEL_FS,
    pen,
)
from ctdcast.reports._vendored.design_tokens import (
    MAX_SECTION_H as _MAX_SECTION_H,
)
from ctdcast.reports._vendored.design_tokens import (
    W_FULL as _W_FULL,
)
from ctdcast.reports._vendored.design_tokens import (
    W_HALF as _W_HALF,
)
from ctdcast.reports._vendored.design_tokens import (
    W_THIRD as _W_THIRD,
)
from ctdcast.reports._vendored.design_tokens import (
    W_TWOTHIRDS as _W_TWOTHIRDS,
)

if TYPE_CHECKING:
    from ctdcast.analysis.clock import CastClock, ClockVerdict


def draw_clock_offset_fig(
    series: list[CastClock],
    verdict: ClockVerdict,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_FULL,
) -> plt.Figure | None:
    """Return a Figure of per-cast clock offset vs cast number, with segment means and changepoints.

    Points, not a line — the offsets are whole-second-quantised, so a line would imply a precision
    that is not there. Each segment mean is drawn as a horizontal rule over its cast range and each
    changepoint as a vertical rule. Returns ``None`` when there is nothing to plot (no segments —
    a ``no_clock_pair`` or ``insufficient`` verdict).

    Parameters
    ----------
    series : list of CastClock
        Per-cast clock offsets, in cast order.
    verdict : ClockVerdict
        Segmentation of *series* (segment means and changepoints).
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_FULL``
        Figure width in inches (full slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when there is nothing to plot (no segments).
    """
    from ctdcast.analysis.clock import cast_number

    if not series or not verdict.segments:
        return None
    x = [cast_number(c.cast_id) for c in series]
    y = [c.offset_seconds for c in series]

    fig, ax = plt.subplots(figsize=(width_in, width_in * 4.0 / _W_FULL))
    ax.axhline(0, color="0.8", lw=pen("thinner"))  # zero-offset reference
    for seg in verdict.segments[1:]:  # changepoints (none for constant/drift)
        ax.axvline(cast_number(seg.first_cast), color="0.6", ls="--", lw=pen("thinner"))
    for seg in verdict.segments:  # segment means, over the cast range
        ax.hlines(
            seg.offset_seconds,
            cast_number(seg.first_cast),
            cast_number(seg.last_cast),
            color="#c1272d",
            lw=pen("thick"),
            zorder=2,
        )
    # Translucent dark-grey dots (not solid black) so overlapping casts read as denser;
    # ~30% smaller than the style default for the same reason.
    ax.plot(
        x,
        y,
        marker="o",
        linestyle="none",
        color="0.3",
        alpha=0.5,
        markersize=plt.rcParams["lines.markersize"] * 0.7,
        markeredgecolor="none",
        zorder=3,
    )
    ax.set_xlabel("cast number")
    ax.set_ylabel("clock offset (s)   NMEA − System")
    ax.grid(True)
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_timeseries_fig(
    ds_prof: xr.Dataset,
    var: str,
    label: str,  # noqa: ARG001 — full label retained for callers; figure shows units only
    style: str = "pcolormesh",
    vmin: float | None = None,
    vmax: float | None = None,
    figw: float | None = None,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
) -> plt.Figure | None:
    """Return a Figure of *var* vs cast time × pressure, downcasts and upcasts.

    Parameters
    ----------
    ds_prof : xarray.Dataset
        Profiles with ``time_start``, ``time_end``, ``cast_number`` and ``cast_type``.
    var : str
        Variable to plot from *ds_prof*.
    label : str
        Accepted for call-site compatibility; the colorbar shows units only.
    style : {"pcolormesh", "contourf"}
        Field rendering.
    vmin, vmax : float, optional
        Colour limits; each defaults to the 2nd / 98th percentile of the data.
    figw : float, optional
        Figure width in inches.  When None it follows the profile count: full
        width for 30 or more, half for 15 or more, else third.
    cfg : ReportConfig
        Report configuration; ``var_cmaps`` gives the colormap for *var*.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when *var* or ``time_start`` is absent or no value is finite.
    """
    import matplotlib.dates as mdates

    if var not in ds_prof or "time_start" not in ds_prof:
        return None
    pressure = ds_prof["pressure"].values
    data = ds_prof[var].values
    times_start = ds_prof["time_start"].values
    cast_types = (
        ds_prof["cast_type"].values
        if "cast_type" in ds_prof
        else np.full(len(times_start), "down")
    )
    cast_numbers = ds_prof["cast_number"].values if "cast_number" in ds_prof else None

    if not len(times_start):
        return None

    # Use profile midpoint time so down/up pairs of the same deployment
    # are spread apart rather than stacked at the same time_start.
    if "time_end" in ds_prof:
        times_end = ds_prof["time_end"].values
        times = times_start + (times_end - times_start) // 2
    else:
        times = times_start

    order = np.argsort(times)
    data = data[order]
    times = times[order]
    cast_types = cast_types[order]
    if cast_numbers is not None:
        cast_numbers = cast_numbers[order]

    # Trim to deepest pressure level that has any valid data across all profiles
    valid_cols = np.where(np.any(np.isfinite(data), axis=0))[0]
    if not len(valid_cols):
        return None
    p_trim = pressure[: valid_cols[-1] + 1]
    data_trim = data[:, : valid_cols[-1] + 1]

    d_fin = data_trim[np.isfinite(data_trim)]
    if not len(d_fin):
        return None

    cmap, norm, bounds, _ = _discrete_norm(
        d_fin, var, vmin, vmax, var_cmaps=cfg.var_cmaps
    )

    t_mpl = mdates.date2num(times.astype("datetime64[ms]").astype("O"))
    n_prof = len(t_mpl)
    fw = figw
    if fw is None:
        # Mirror the step function in timeseries.py so standalone callers
        # get a slot-consistent width even without the Tier-2 caller.
        fw = _W_FULL if n_prof >= 30 else _W_HALF if n_prof >= 15 else _W_THIRD
    fig_h = float(np.clip(float(p_trim[-1]) / 250.0 + 2.5, 3.0, _MAX_SECTION_H))

    fig, ax = plt.subplots(figsize=(fw, fig_h))
    x_for_contour: np.ndarray
    if style == "contourf":
        t_idx = np.arange(n_prof, dtype=float)
        pc = ax.contourf(
            t_idx,
            p_trim,
            data_trim.T,
            levels=bounds,
            cmap=cmap,
            norm=norm,
            extend="both",
        )
        x_for_contour = t_idx
        _max_ticks = max(4, round(fw * 1.4))
        _tick_step = max(1, n_prof // _max_ticks)
        ax.set_xticks(t_idx[::_tick_step])
        ax.set_xticklabels(
            [mdates.num2date(t).strftime("%d %b\n%H:%M") for t in t_mpl[::_tick_step]],
            rotation=30,
            ha="right",
        )
    else:
        pc = ax.pcolormesh(
            t_mpl, p_trim, data_trim.T, cmap=cmap, norm=norm, shading="nearest"
        )
        x_for_contour = t_mpl
        ax.xaxis_date()
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

    unit_colorbar(
        ax,
        pc,
        unit=vunit(var),
        ticks=nice_colorbar_ticks(float(bounds[0]), float(bounds[-1])),
        extend="both",
        reserve=True,
        title_loc="left",
    )

    if var == "sigma0":
        sigma0_isopycnals(ax, x_for_contour, p_trim, data_trim)

    # ▼ for downcast, △ for upcast floating above axes; cast number above each downcast
    trans = ax.get_xaxis_transform()
    n_down = sum(1 for ct in cast_types if ct == "down")
    label_step = max(1, n_down // 20)
    down_count = 0
    for i, (t_val, ctype) in enumerate(zip(t_mpl, cast_types, strict=True)):
        marker, color = ("v", "#1f77b4") if ctype == "down" else ("^", _UPCAST_COLOR)
        ax.plot(
            t_val,
            1.03,
            marker=marker,
            ls="none",
            ms=5,
            mfc="none",
            mec=color,
            mew=0.7,
            clip_on=False,
            transform=trans,
        )
        if ctype == "down" and cast_numbers is not None:
            if down_count % label_step == 0:
                ax.text(
                    t_val,
                    1.05,
                    str(int(cast_numbers[i])),
                    transform=trans,
                    ha="center",
                    va="bottom",
                    fontsize=CAST_LABEL_FS,
                    rotation=0,
                )
            down_count += 1

    ax.set_ylim(float(p_trim[-1]), float(p_trim[0]))
    ax.set_ylabel(vlabel("pressure"))
    return fig


def draw_sensor_diff_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_TWOTHIRDS,
) -> plt.Figure | None:
    """Return primary-minus-secondary sensor difference profiles (T₁−T₂, S₁−S₂).

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with a primary and a secondary temperature and/or
        salinity channel.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_TWOTHIRDS``
        Figure width in inches (two-thirds slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when neither a temperature nor a salinity pair is present.
    """
    p = ds["pressure"].values
    _t1 = next((v for v in ("ctd_temperature_1", "temperature_1") if v in ds), None)
    _t2 = next((v for v in ("ctd_temperature_2", "temperature_2") if v in ds), None)
    _s1 = next((v for v in ("ctd_salinity_1", "salinity_1") if v in ds), None)
    _s2 = next((v for v in ("ctd_salinity_2", "salinity_2") if v in ds), None)
    has_t = _t1 is not None and _t2 is not None
    has_s = _s1 is not None and _s2 is not None
    if not has_t and not has_s:
        return None

    n_panels = int(has_t) + int(has_s)
    fig, axes = plt.subplots(
        1, n_panels, figsize=(width_in, width_in * 5.5 / _W_TWOTHIRDS), sharey=True
    )
    if n_panels == 1:
        axes = [axes]

    max_p = float(np.nanmax(p))
    idx = 0
    if has_t:
        dt = ds[_t1].values - ds[_t2].values
        axes[idx].plot(
            dt,
            p,
            ".",
            color=VAR_COLORS["conservative_temperature"],
            markersize=1.5,
            linewidth=0,
        )
        axes[idx].axvline(0, color="0.6", linewidth=pen("thinner"), linestyle="--")
        axes[idx].set_xlabel(f"T₁ − T₂ ({vunit('ctd_temperature_1')})")
        axes[idx].set_xlim(-0.01, 0.01)
        axes[idx].grid(True)
        idx += 1
    if has_s:
        ds_diff = ds[_s1].values - ds[_s2].values
        axes[idx].plot(
            ds_diff,
            p,
            ".",
            color=VAR_COLORS["absolute_salinity"],
            markersize=1.5,
            linewidth=0,
        )
        axes[idx].axvline(0, color="0.6", linewidth=pen("thinner"), linestyle="--")
        axes[idx].set_xlabel(f"S₁ − S₂ ({vunit('ctd_salinity_1')})")
        axes[idx].set_xlim(-0.01, 0.01)
        axes[idx].grid(True)

    axes[0].set_ylabel(vlabel("pressure"))
    axes[0].set_ylim(max_p, 0)
    hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig


def draw_pressure_time_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_THIRD,
) -> plt.Figure | None:
    """Return a pressure vs elapsed time Figure (cast trajectory and bottle stops).

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with ``pressure`` and ``time``.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_THIRD``
        Figure width in inches (third slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure
        The figure.
    """
    p = ds["pressure"].values
    t_raw = ds["time"].values

    if np.issubdtype(t_raw.dtype, np.datetime64):
        elapsed_min = (t_raw - t_raw[0]) / np.timedelta64(1, "s") / 60.0
    else:
        elapsed_min = (t_raw.astype(float) - float(t_raw[0])) / 60.0

    fig, ax = plt.subplots(figsize=(width_in, width_in * 3.7 / _W_THIRD))
    ax.plot(elapsed_min, p, color="k", linewidth=pen("thin"))
    max_p = float(np.nanmax(p))
    ax.set_ylim(max_p, 0)
    ax.set_xlabel("Elapsed time (min)")
    ax.set_ylabel(vlabel("pressure"))
    ax.grid(True)
    hide_outer_spines(ax, clean=cfg.clean_spines)
    return fig


def draw_updown_diff_fig(
    ds: xr.Dataset,
    *,
    cfg: ReportConfig = DEFAULT_REPORT_CONFIG,
    width_in: float = _W_FULL,
) -> plt.Figure | None:
    """Return downcast-minus-upcast profiles of ΔCT, ΔSA and Δσ₀ on a shared 1 dbar grid.

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast dataset with ``pressure`` and the T/S channels; CT, SA and σ₀
        are derived here (TEOS-10), and the cast is split at
        the turnaround.
    cfg : ReportConfig
        Report configuration; ``clean_spines`` sets the despine.
    width_in : float, default ``W_FULL``
        Figure width in inches (full slot); the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        The figure, or None when either half has fewer than five levels, the down/up overlap is under
        10 dbar, or no difference can be formed.
    """
    ds_teos = add_teos10(ds)
    ds_down, ds_up = split_cast(ds_teos)

    if len(ds_down["pressure"]) < 5 or len(ds_up["pressure"]) < 5:
        return None

    p_down = ds_down["pressure"].values
    p_up = ds_up["pressure"].values
    p_lo = max(float(np.nanmin(p_down)), float(np.nanmin(p_up)))
    p_hi = min(float(np.nanmax(p_down)), float(np.nanmax(p_up)))
    if p_hi - p_lo < 10:
        return None

    p_grid = np.arange(p_lo, p_hi + 1, 1.0)

    # Sort each cast by pressure so np.interp receives monotonically increasing x
    sort_d = np.argsort(p_down)
    sort_u = np.argsort(p_up)
    p_d_s, p_u_s = p_down[sort_d], p_up[sort_u]

    diffs, labels, colors = [], [], []
    for var, label, color in zip(
        ("conservative_temperature", "absolute_salinity", "sigma0"),
        (
            vlabel(v, prefix="Δ")
            for v in ("conservative_temperature", "absolute_salinity", "sigma0")
        ),
        _TS_COLORS,
        strict=True,
    ):
        if var not in ds_down or var not in ds_up:
            continue
        v_d = np.interp(p_grid, p_d_s, ds_down[var].values[sort_d])
        v_u = np.interp(p_grid, p_u_s, ds_up[var].values[sort_u])
        diffs.append(v_d - v_u)
        labels.append(label)
        colors.append(color)

    if not diffs:
        return None

    fig, axes = plt.subplots(
        1, len(diffs), figsize=(width_in, width_in * 5.5 / _W_FULL), sharey=True
    )
    if len(diffs) == 1:
        axes = [axes]
    for ax, diff, label, color in zip(axes, diffs, labels, colors, strict=True):
        ax.plot(diff, p_grid, color=color, linewidth=pen("thin"))
        ax.axvline(0, color="0.6", linewidth=pen("thinner"), linestyle="--")
        ax.set_xlabel(label)
        ax.grid(True)
    axes[0].set_ylabel(vlabel("pressure"))
    axes[0].set_ylim(float(p_grid[-1]), 0)
    hide_outer_spines(*axes, clean=cfg.clean_spines)
    return fig
