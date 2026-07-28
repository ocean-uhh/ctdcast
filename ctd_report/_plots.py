"""Tier-1 plot helpers: each returns a base64-encoded PNG string or None on error."""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any, Optional

import gsw
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

from ctd_report._analysis import (
    _add_teos10,
    _load_gebco,
    _split_cast,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to GEBCO_2025.nc — set this before generating maps, e.g.:
#   import ctd_report._plots as plots
#   plots.GEBCO_PATH = Path("/data/GEBCO_2025.nc")
# Maps render without bathymetry if None or file not found.
GEBCO_PATH: Optional[Path] = None

# Bundled mplstyle — controls font sizes, line widths, figure defaults.
_MPLSTYLE = Path(__file__).parent / "ctd_report.mplstyle"

# Colors for the triple-axis T / S / sigma0 profile plot.
_TS_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]

# ColorBrewer colormaps per variable (for pcolormesh / scatter).
_VAR_CMAPS: dict[str, str] = {
    "CT": "RdYlBu_r",
    "temperature_1": "RdYlBu_r",
    "SA": "YlGnBu",
    "salinity_1": "YlGnBu",
    "oxygen_1": "RdYlGn",
    "AOU": "RdBu_r",  # blue = near saturation, red = depleted
    "fluorescence": "YlGn",
    "turbidity": "YlOrBr",
    "sigma0": "Greys_r",
}

_VAR_LABELS: dict[str, str] = {
    "CT": "Conservative Temperature (°C)",
    "SA": "Absolute Salinity (g kg⁻¹)",
    "temperature_1": "Temperature (°C)",
    "salinity_1": "Salinity (PSU)",
    "oxygen_1": "O₂ saturation (%)",
    "AOU": "O₂ deficit (% sat)",
    "fluorescence": "Fluorescence (mg m⁻³)",
    "turbidity": "Turbidity (NTU)",
    "sigma0": "σ₀ (kg m⁻³)",
    "density": "Density (kg m⁻³)",
}


# ---------------------------------------------------------------------------
# Internal utilities (rendering helpers, no external science dependencies)
# ---------------------------------------------------------------------------


def _fig_to_base64(fig: Any) -> str:
    """Render *fig* to a PNG and return its base64-encoded bytes as a string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _nice_colorbar_bounds(vmin: float, vmax: float, n: int = 20) -> np.ndarray:
    """Return a boundary array for a discrete colorbar with approximately *n* levels.

    Steps are chosen from the "nice" ladder [1, 2, 2.5, 5, 10] scaled to the
    appropriate decade, so ticks land on clean values (e.g. 1.0 rather than 0.8,
    0.5 rather than 0.4). The range is centred on the midpoint of [vmin, vmax].
    """
    span = vmax - vmin
    if span <= 0:
        return np.linspace(vmin - 1, vmin + 1, n + 1)
    raw_step = span / n
    mag = 10.0 ** math.floor(math.log10(raw_step))
    normalized = raw_step / mag  # in [1, 10)
    # Pick the smallest nice multiplier >= normalized
    nice_step = 10.0 * mag  # fallback
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        if factor >= normalized:
            nice_step = factor * mag
            break
    mid = (vmin + vmax) / 2
    mid_aligned = round(mid / nice_step) * nice_step
    lo = mid_aligned - (n / 2) * nice_step
    return np.array([lo + i * nice_step for i in range(n + 1)])


# ---------------------------------------------------------------------------
# Tier-1: individual figure functions
# ---------------------------------------------------------------------------


def _make_profile_b64(ds: xr.Dataset, var: str, ylabel: str) -> Optional[str]:
    """Return a base64 PNG of *var* vs pressure (downcast blue, upcast red)."""
    if var not in ds:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        ds_down, ds_up = _split_cast(ds)
        p_down = ds_down["pressure"].values
        v_down = ds_down[var].values
        p_up = ds_up["pressure"].values
        v_up = ds_up[var].values

        fig, ax = plt.subplots(figsize=(4, 7))
        ax.plot(v_down, p_down, color="#1f77b4", label="downcast")
        if len(v_up) > 2:
            ax.plot(v_up, p_up, color="#aaaaaa", alpha=0.5, label="upcast")
        ax.invert_yaxis()
        ax.set_ylabel("Pressure (dbar)")
        ax.set_xlabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="lower right")
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_ts_density_b64(ds: xr.Dataset) -> Optional[str]:
    """Return a base64 PNG of CT / SA / σ₀ triple-axis profile (downcast only)."""
    try:
        plt.style.use(str(_MPLSTYLE))
        ds = _add_teos10(ds)
        ds_down, _ = _split_cast(ds)
        p = ds_down["pressure"].values
        ct = ds_down["CT"].values
        sa = ds_down["SA"].values
        sig = ds_down["sigma0"].values

        fig, ax0 = plt.subplots(figsize=(4.5, 8))
        ax0.invert_yaxis()
        ax1 = ax0.twiny()
        ax2 = ax0.twiny()

        (l0,) = ax0.plot(ct, p, color=_TS_COLORS[0], label="CT")
        (l1,) = ax1.plot(sa, p, color=_TS_COLORS[1], label="SA")
        (l2,) = ax2.plot(sig, p, color=_TS_COLORS[2], label="σ₀")

        ax2.spines["top"].set_position(("axes", 1.12))
        ax2.spines["top"].set_visible(True)

        for ax, line in zip((ax0, ax1, ax2), (l0, l1, l2)):
            ax.xaxis.label.set_color(line.get_color())
            ax.tick_params(axis="x", colors=line.get_color())
            ax.spines["top"].set_edgecolor(line.get_color())

        ax0.set_ylabel("Pressure (dbar)")
        ax0.set_xlabel("CT (°C)", color=_TS_COLORS[0])
        ax1.set_xlabel("SA (g kg⁻¹)", color=_TS_COLORS[1])
        ax2.set_xlabel("σ₀ (kg m⁻³)", color=_TS_COLORS[2])
        ax0.grid(True, alpha=0.3)

        lines = [l0, l1, l2]
        labels = [ln.get_label() for ln in lines]
        ax0.legend(lines, labels, loc="lower right")
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_ts_diagram_b64(ds: xr.Dataset) -> Optional[str]:
    """Return a base64 PNG of a T-S diagram colored by O₂ saturation."""
    try:
        plt.style.use(str(_MPLSTYLE))
        ds = _add_teos10(ds)
        ds_down, _ = _split_cast(ds)
        sa = ds_down["SA"].values
        ct = ds_down["CT"].values
        if "oxygen_1" not in ds_down:
            return None
        o2 = ds_down["oxygen_1"].values

        mask = np.isfinite(sa) & np.isfinite(ct) & np.isfinite(o2)
        sa, ct, o2 = sa[mask], ct[mask], o2[mask]
        if len(sa) < 5:
            return None

        o2_fin = o2[np.isfinite(o2)]
        bounds = _nice_colorbar_bounds(
            float(np.nanpercentile(o2_fin, 2)),
            float(np.nanpercentile(o2_fin, 98)),
            n=16,
        )
        cmap = plt.get_cmap("RdYlGn", len(bounds) - 1)
        norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

        fig, ax = plt.subplots(figsize=(5.5, 5))

        sa_grid = np.linspace(sa.min() - 0.1, sa.max() + 0.1, 80)
        ct_grid = np.linspace(ct.min() - 0.2, ct.max() + 0.2, 80)
        SA_g, CT_g = np.meshgrid(sa_grid, ct_grid)
        sig0_g = gsw.sigma0(SA_g, CT_g)
        cs = ax.contour(SA_g, CT_g, sig0_g, levels=8, colors="0.6", linewidths=0.6)
        ax.clabel(cs, fmt="%.1f", fontsize=7)

        sc = ax.scatter(sa, ct, c=o2, cmap=cmap, norm=norm, s=6, alpha=0.8)
        cb = fig.colorbar(sc, ax=ax, ticks=bounds)
        cb.set_label("O₂ saturation (%)")

        ax.set_xlabel("Absolute Salinity (g kg⁻¹)")
        ax.set_ylabel("Conservative Temperature (°C)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_stability_b64(ds: xr.Dataset) -> Optional[str]:
    """Return a base64 PNG of N² and Turner angle (2-panel)."""
    try:
        plt.style.use(str(_MPLSTYLE))
        ds = _add_teos10(ds)
        ds_down, _ = _split_cast(ds)
        p = ds_down["pressure"].values.astype(float)
        sa = ds_down["SA"].values.astype(float)
        ct = ds_down["CT"].values.astype(float)
        lat = float(np.nanmedian(ds["latitude"].values))

        if len(p) < 3:
            return None

        n2, p_n2 = gsw.Nsquared(sa, ct, p, lat=lat)
        tu, _, p_tu = gsw.Turner_Rsubrho(sa, ct, p, axis=0)

        fig, axes = plt.subplots(1, 2, figsize=(7, 6), sharey=True)
        ax_n2, ax_tu = axes

        ax_n2.plot(n2, p_n2, color="k")
        ax_n2.axvline(0, color="0.6", lw=0.8, ls="--")
        ax_n2.invert_yaxis()
        ax_n2.set_xlabel("N² (s⁻²)")
        ax_n2.set_ylabel("Pressure (dbar)")
        ax_n2.grid(True, alpha=0.3)

        ax_tu.axvspan(-90, -45, color="#f4a582", alpha=0.35, label="salt fingering")
        ax_tu.axvspan(45, 90, color="#92c5de", alpha=0.35, label="diffusive conv.")
        ax_tu.axvspan(-45, 45, color="0.88", alpha=0.5, label="doubly stable")
        ax_tu.axvline(-45, color="k", lw=0.8, ls="--")
        ax_tu.axvline(45, color="k", lw=0.8, ls="--")
        ax_tu.plot(tu, p_tu, color="#333333")
        ax_tu.set_xlim(-90, 90)
        ax_tu.set_xlabel("Turner angle (°)")
        ax_tu.legend(loc="lower right", fontsize=7)
        ax_tu.grid(True, alpha=0.3)

        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_aux_profiles_b64(ds: xr.Dataset) -> Optional[str]:
    """Return a base64 PNG of O₂ sat, fluorescence, turbidity profiles (downcast + pale upcast)."""
    vars_labels = [
        ("oxygen_1", "O₂ saturation (%)"),
        ("fluorescence", "Fluorescence (mg m⁻³)"),
        ("turbidity", "Turbidity (NTU)"),
    ]
    available = [(v, lbl) for v, lbl in vars_labels if v in ds]
    if not available:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        ds_down, ds_up = _split_cast(ds)

        fig, axes = plt.subplots(
            1, len(available), figsize=(3.5 * len(available), 7), sharey=True
        )
        if len(available) == 1:
            axes = [axes]

        colors = ["#1b7837", "#762a83", "#bf812d"]
        for ax, (var, label), color in zip(axes, available, colors):
            ax.plot(
                ds_down[var].values,
                ds_down["pressure"].values,
                color=color,
                label="downcast",
            )
            if var in ds_up and len(ds_up["pressure"]) > 2:
                ax.plot(
                    ds_up[var].values,
                    ds_up["pressure"].values,
                    color="#aaaaaa",
                    alpha=0.5,
                    label="upcast",
                )
            ax.invert_yaxis()
            ax.set_xlabel(label)
            ax.grid(True, alpha=0.3)

        axes[0].set_ylabel("Pressure (dbar)")
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_ts_updown_b64(ds: xr.Dataset) -> Optional[str]:
    """Return a base64 PNG of CT–SA scatter: downcast in blue, upcast in red, σ₀ contours."""
    try:
        plt.style.use(str(_MPLSTYLE))
        ds = _add_teos10(ds)
        ds_down, ds_up = _split_cast(ds)

        sa_d = ds_down["SA"].values
        ct_d = ds_down["CT"].values
        sa_u = ds_up["SA"].values
        ct_u = ds_up["CT"].values

        mask_d = np.isfinite(sa_d) & np.isfinite(ct_d)
        mask_u = np.isfinite(sa_u) & np.isfinite(ct_u)
        if not mask_d.any():
            return None

        all_sa = np.concatenate(
            [sa_d[mask_d], sa_u[mask_u]] if mask_u.any() else [sa_d[mask_d]]
        )
        all_ct = np.concatenate(
            [ct_d[mask_d], ct_u[mask_u]] if mask_u.any() else [ct_d[mask_d]]
        )
        sa_g = np.linspace(all_sa.min() - 0.1, all_sa.max() + 0.1, 80)
        ct_g = np.linspace(all_ct.min() - 0.2, all_ct.max() + 0.2, 80)
        SA_g, CT_g = np.meshgrid(sa_g, ct_g)
        sig0_g = gsw.sigma0(SA_g, CT_g)

        fig, ax = plt.subplots(figsize=(5, 5))
        cs = ax.contour(SA_g, CT_g, sig0_g, levels=8, colors="0.6", linewidths=0.6)
        ax.clabel(cs, fmt="%.1f", fontsize=7)
        ax.scatter(
            sa_d[mask_d],
            ct_d[mask_d],
            s=6,
            color="#1f77b4",
            alpha=0.7,
            label="downcast",
        )
        if mask_u.any():
            ax.scatter(
                sa_u[mask_u],
                ct_u[mask_u],
                s=4,
                color="#d62728",
                alpha=0.4,
                label="upcast",
            )
        ax.set_xlabel("Absolute Salinity (g kg⁻¹)")
        ax.set_ylabel("Conservative Temperature (°C)")
        ax.legend(loc="best", markerscale=2)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_station_map_b64(
    lat: float,
    lon: float,
    all_meta: list[dict],
) -> Optional[str]:
    """Return a base64 PNG of a GEBCO map with all casts and this cast highlighted."""
    try:
        plt.style.use(str(_MPLSTYLE))
        all_lats = [m["lat"] for m in all_meta if np.isfinite(m.get("lat", np.nan))]
        all_lons = [m["lon"] for m in all_meta if np.isfinite(m.get("lon", np.nan))]

        if not all_lats:
            return None

        lat_lo, lat_hi = min(all_lats), max(all_lats)
        lon_lo, lon_hi = min(all_lons), max(all_lons)
        margin = max(0.05, (lat_hi - lat_lo) * 0.1)

        fig, ax = plt.subplots(figsize=(5, 5))

        gebco = _load_gebco(
            lat_lo, lat_hi, lon_lo, lon_hi, margin=margin, path=GEBCO_PATH
        )
        if gebco is not None:
            lons_b, lats_b, depth_b = gebco
            d_fin = depth_b[depth_b > 0]
            if len(d_fin):
                bounds_b = _nice_colorbar_bounds(
                    float(d_fin.min()), float(np.percentile(d_fin, 98)), n=14
                )
                cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
                norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
                LON2, LAT2 = np.meshgrid(lons_b, lats_b)
                ax.pcolormesh(
                    LON2,
                    LAT2,
                    depth_b,
                    cmap=cmap_b,
                    norm=norm_b,
                    shading="nearest",
                    rasterized=True,
                )

        ax.scatter(all_lons, all_lats, s=12, color="0.5", zorder=3, label="all casts")
        ax.scatter(
            [lon], [lat], s=60, color="#d62728", zorder=5, label="this cast", marker="*"
        )
        ax.set_xlabel("Longitude (°E)")
        ax.set_ylabel("Latitude (°N)")
        ax.set_xlim(lon_lo - margin, lon_hi + margin)
        ax.set_ylim(lat_lo - margin, lat_hi + margin)
        ax.legend(loc="upper right", markerscale=1.2)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_cruise_map_b64(all_meta: list[dict]) -> Optional[str]:
    """Return a base64 PNG of all cast positions (no single-cast highlight).

    Casts are drawn as grey scatter over GEBCO bathymetry.  Cast numbers are
    annotated for the first and last cast and every 10th in between.
    """
    try:
        plt.style.use(str(_MPLSTYLE))
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

        fig, ax = plt.subplots(figsize=(6, 5))

        gebco = _load_gebco(
            lat_lo, lat_hi, lon_lo, lon_hi, margin=margin, path=GEBCO_PATH
        )
        if gebco is not None:
            lons_b, lats_b, depth_b = gebco
            d_fin = depth_b[depth_b > 0]
            if len(d_fin):
                bounds_b = _nice_colorbar_bounds(
                    float(d_fin.min()), float(np.percentile(d_fin, 98)), n=12
                )
                cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
                norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
                LON2, LAT2 = np.meshgrid(lons_b, lats_b)
                ax.pcolormesh(
                    LON2,
                    LAT2,
                    depth_b,
                    cmap=cmap_b,
                    norm=norm_b,
                    shading="nearest",
                    rasterized=True,
                )

        ax.scatter(lons, lats, s=14, color="0.4", zorder=3)
        n = len(nums)
        label_idx = sorted(set([0, n - 1] + list(range(0, n, max(1, n // 10)))))
        for i in label_idx:
            ax.annotate(
                str(nums[i]),
                (lons[i], lats[i]),
                fontsize=6,
                xytext=(3, 3),
                textcoords="offset points",
            )

        ax.set_xlabel("Longitude (°E)")
        ax.set_ylabel("Latitude (°N)")
        ax.set_xlim(lon_lo - margin, lon_hi + margin)
        ax.set_ylim(lat_lo - margin, lat_hi + margin)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_section_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    x_vals: np.ndarray,
    x_label: str,
    title: str = "",
    style: str = "pcolormesh",
    bathy_depths: Optional[np.ndarray] = None,
    cast_labels: Optional[list] = None,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> Optional[str]:
    """Return a base64 PNG of *var* vs pressure × *x_vals*.

    Parameters
    ----------
    title:
        Ignored (kept for call-site compatibility). Variable label appears on colorbar.
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    bathy_depths:
        GEBCO water depth (m, same length as N_PROF) drawn as a filled black area below data.
    cast_labels:
        Cast numbers shown as ▼ markers and sparse tick labels along the top edge.
    vmin, vmax:
        Colormap limit overrides; auto from 2–98th percentile if ``None``.
    """
    if var not in ds_prof:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        pressure = ds_prof["pressure"].values
        data = ds_prof[var].values

        valid_cols = np.where(np.any(np.isfinite(data), axis=0))[0]
        if not len(valid_cols):
            return None
        p_trim = pressure[: valid_cols[-1] + 1]
        data_trim = data[:, : valid_cols[-1] + 1]

        d_fin = data_trim[np.isfinite(data_trim)]
        if not len(d_fin):
            return None

        cmap_name = _VAR_CMAPS.get(var, "viridis")
        v0 = vmin if vmin is not None else float(np.percentile(d_fin, 2))
        v1 = vmax if vmax is not None else float(np.percentile(d_fin, 98))
        if v0 >= v1:
            v0, v1 = float(np.percentile(d_fin, 2)), float(np.percentile(d_fin, 98))
        bounds = _nice_colorbar_bounds(v0, v1, n=20)
        cmap = plt.get_cmap(cmap_name, len(bounds) - 1)
        norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

        # Auto-size: for along-track km axes (x range > 10), scale width to distance
        dist = float(x_vals[-1] - x_vals[0]) if len(x_vals) > 1 else 10.0
        p_max_data = float(p_trim[-1])
        if dist > 10.0:
            fig_w = max(6.0, min(18.0, dist / 50.0))
            fig_h = max(3.0, min(7.0, fig_w * p_max_data / max(dist, 1.0) / 40.0))
        else:
            fig_w, fig_h = 9.0, 5.0

        # Y extent: deeper of data max and bathy max
        p_max_bathy = (
            float(np.nanmax(bathy_depths))
            if bathy_depths is not None and len(bathy_depths)
            else 0.0
        )
        y_bottom = max(p_max_data, p_max_bathy) * 1.05

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        if style == "contourf":
            X, Y = np.meshgrid(x_vals, p_trim)
            Z = np.ma.masked_invalid(data_trim.T)
            cf = ax.contourf(X, Y, Z, levels=bounds, cmap=cmap_name, extend="both")
            cb = fig.colorbar(cf, ax=ax, ticks=bounds, pad=0.02)
        else:
            pc = ax.pcolormesh(
                x_vals, p_trim, data_trim.T, cmap=cmap, norm=norm, shading="nearest"
            )
            cb = fig.colorbar(pc, ax=ax, ticks=bounds, pad=0.02)

        if bathy_depths is not None and len(bathy_depths) == len(x_vals):
            ax.fill_between(
                x_vals, bathy_depths, y_bottom, color="black", step="mid", lw=0
            )

        cb.set_label(label)
        ax.set_ylim(y_bottom, 0)
        ax.set_ylabel("Pressure (dbar)")
        ax.set_xlabel(x_label)
        ax.grid(True, alpha=0.2, color="white")

        if cast_labels is not None and len(cast_labels) == len(x_vals):
            trans = ax.get_xaxis_transform()
            ax.plot(
                x_vals,
                [1.0] * len(x_vals),
                marker="v",
                ls="none",
                ms=3,
                mfc="black",
                mec="black",
                transform=trans,
                clip_on=False,
                zorder=6,
            )
            n_lab = len(cast_labels)
            label_step = max(1, n_lab // 20)
            for i in range(0, n_lab, label_step):
                ax.text(
                    float(x_vals[i]),
                    1.04,
                    str(cast_labels[i]),
                    transform=trans,
                    ha="center",
                    va="bottom",
                    fontsize=5,
                    rotation=90,
                )

        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_section_ts_profiles_b64(
    ds_prof: xr.Dataset,
    x_vals: np.ndarray,
) -> Optional[str]:
    """Return a base64 PNG of per-cast CT–SA profiles coloured by along-track distance.

    Each downcast in *ds_prof* is drawn as a CT–SA line with σ₀ background contours.
    Colour encodes the corresponding *x_vals* value (along-track km).
    """
    if "SA" not in ds_prof or "CT" not in ds_prof:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        sa_all = ds_prof["SA"].values  # (N_PROF, N_P)
        ct_all = ds_prof["CT"].values  # (N_PROF, N_P)
        sa_fin = sa_all[np.isfinite(sa_all)]
        ct_fin = ct_all[np.isfinite(ct_all)]
        if not len(sa_fin) or not len(ct_fin):
            return None

        sa_g = np.linspace(sa_fin.min() - 0.05, sa_fin.max() + 0.05, 80)
        ct_g = np.linspace(ct_fin.min() - 0.1, ct_fin.max() + 0.1, 80)
        SA_g, CT_g = np.meshgrid(sa_g, ct_g)
        sig0_g = gsw.sigma0(SA_g, CT_g)

        x_lo, x_hi = float(x_vals.min()), float(x_vals.max())
        if x_hi <= x_lo:
            x_hi = x_lo + 1.0
        bounds = _nice_colorbar_bounds(x_lo, x_hi, n=12)
        cmap = plt.get_cmap("plasma", len(bounds) - 1)
        norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

        fig, ax = plt.subplots(figsize=(5.5, 5))
        cs = ax.contour(SA_g, CT_g, sig0_g, levels=8, colors="0.6", linewidths=0.6)
        ax.clabel(cs, fmt="%.1f", fontsize=7)

        for i in range(sa_all.shape[0]):
            mask = np.isfinite(sa_all[i]) & np.isfinite(ct_all[i])
            if not mask.any():
                continue
            ax.plot(
                sa_all[i, mask],
                ct_all[i, mask],
                color=cmap(norm(float(x_vals[i]))),
                alpha=0.6,
                lw=0.8,
            )

        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, ticks=bounds[::2])
        cb.set_label("Along-track distance (km)")

        ax.set_xlabel("Absolute Salinity (g kg⁻¹)")
        ax.set_ylabel("Conservative Temperature (°C)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_section_ts_histogram_b64(ds_prof: xr.Dataset) -> Optional[str]:
    """Return a base64 PNG of a CT–SA 2-D count histogram (log₁₀ colour) for section profiles."""
    if "SA" not in ds_prof or "CT" not in ds_prof:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        sa = ds_prof["SA"].values.ravel()
        ct = ds_prof["CT"].values.ravel()
        mask = np.isfinite(sa) & np.isfinite(ct)
        sa, ct = sa[mask], ct[mask]
        if len(sa) < 10:
            return None

        sa_lo, sa_hi = sa.min(), sa.max()
        ct_lo, ct_hi = ct.min(), ct.max()
        sa_g = np.linspace(sa_lo - 0.05, sa_hi + 0.05, 80)
        ct_g = np.linspace(ct_lo - 0.1, ct_hi + 0.1, 80)
        SA_g, CT_g = np.meshgrid(sa_g, ct_g)
        sig0_g = gsw.sigma0(SA_g, CT_g)

        sa_edges = np.linspace(sa_lo, sa_hi, 51)
        ct_edges = np.linspace(ct_lo, ct_hi, 51)
        counts, _, _ = np.histogram2d(sa, ct, bins=[sa_edges, ct_edges])

        sa_c = (sa_edges[:-1] + sa_edges[1:]) / 2
        ct_c = (ct_edges[:-1] + ct_edges[1:]) / 2
        counts_log = np.log10(np.where(counts.T > 0, counts.T, np.nan))

        c_fin = counts_log[np.isfinite(counts_log)]
        if not len(c_fin):
            return None
        bounds_c = _nice_colorbar_bounds(float(c_fin.min()), float(c_fin.max()), n=12)
        cmap_c = plt.get_cmap("plasma", len(bounds_c) - 1)
        norm_c = mcolors.BoundaryNorm(bounds_c, ncolors=cmap_c.N)

        fig, ax = plt.subplots(figsize=(5.5, 5))
        cs = ax.contour(SA_g, CT_g, sig0_g, levels=8, colors="0.6", linewidths=0.6)
        ax.clabel(cs, fmt="%.1f", fontsize=7)
        pc = ax.pcolormesh(sa_c, ct_c, counts_log, cmap=cmap_c, norm=norm_c)
        cb = fig.colorbar(pc, ax=ax, ticks=bounds_c)
        cb.set_label("log₁₀(count)")

        ax.set_xlabel("Absolute Salinity (g kg⁻¹)")
        ax.set_ylabel("Conservative Temperature (°C)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_section_ts_o2_b64(ds_prof: xr.Dataset) -> Optional[str]:
    """Return a base64 PNG of CT–SA histogram coloured by median O₂ saturation per bin."""
    if "SA" not in ds_prof or "CT" not in ds_prof or "oxygen_1" not in ds_prof:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        sa = ds_prof["SA"].values.ravel()
        ct = ds_prof["CT"].values.ravel()
        o2 = ds_prof["oxygen_1"].values.ravel()
        mask = np.isfinite(sa) & np.isfinite(ct) & np.isfinite(o2)
        sa, ct, o2 = sa[mask], ct[mask], o2[mask]
        if len(sa) < 10:
            return None

        sa_lo, sa_hi = sa.min(), sa.max()
        ct_lo, ct_hi = ct.min(), ct.max()
        sa_g = np.linspace(sa_lo - 0.05, sa_hi + 0.05, 80)
        ct_g = np.linspace(ct_lo - 0.1, ct_hi + 0.1, 80)
        SA_g, CT_g = np.meshgrid(sa_g, ct_g)
        sig0_g = gsw.sigma0(SA_g, CT_g)

        n_sa, n_ct = 50, 50
        sa_edges = np.linspace(sa_lo, sa_hi, n_sa + 1)
        ct_edges = np.linspace(ct_lo, ct_hi, n_ct + 1)
        sa_c = (sa_edges[:-1] + sa_edges[1:]) / 2
        ct_c = (ct_edges[:-1] + ct_edges[1:]) / 2

        sa_b = np.clip(np.searchsorted(sa_edges, sa, side="right") - 1, 0, n_sa - 1)
        ct_b = np.clip(np.searchsorted(ct_edges, ct, side="right") - 1, 0, n_ct - 1)
        flat = sa_b * n_ct + ct_b

        order = np.argsort(flat)
        flat_s, o2_s = flat[order], o2[order]
        uniq_f, starts = np.unique(flat_s, return_index=True)
        stops = np.r_[starts[1:], len(flat_s)]

        o2_flat = np.full(n_sa * n_ct, np.nan)
        for k, fi in enumerate(uniq_f):
            pts = o2_s[starts[k] : stops[k]]
            if len(pts) >= 2:
                o2_flat[int(fi)] = float(np.median(pts))

        o2_grid = o2_flat.reshape(n_sa, n_ct).T  # (ct_bins, sa_bins) for pcolormesh
        o2_fin = o2_grid[np.isfinite(o2_grid)]
        if not len(o2_fin):
            return None

        bounds_o = _nice_colorbar_bounds(
            float(np.nanpercentile(o2_fin, 2)),
            float(np.nanpercentile(o2_fin, 98)),
            n=16,
        )
        cmap_o = plt.get_cmap("RdYlGn", len(bounds_o) - 1)
        norm_o = mcolors.BoundaryNorm(bounds_o, ncolors=cmap_o.N)

        fig, ax = plt.subplots(figsize=(5.5, 5))
        cs = ax.contour(SA_g, CT_g, sig0_g, levels=8, colors="0.6", linewidths=0.6)
        ax.clabel(cs, fmt="%.1f", fontsize=7)
        pc = ax.pcolormesh(sa_c, ct_c, o2_grid, cmap=cmap_o, norm=norm_o)
        cb = fig.colorbar(pc, ax=ax, ticks=bounds_o[::2])
        cb.set_label("Median O₂ saturation (%)")

        ax.set_xlabel("Absolute Salinity (g kg⁻¹)")
        ax.set_ylabel("Conservative Temperature (°C)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_section_map_b64(
    lats: list[float],
    lons: list[float],
    cast_nums: list[int],
    title: str = "",
) -> Optional[str]:
    """Return a base64 PNG of a GEBCO map with the section track."""
    try:
        plt.style.use(str(_MPLSTYLE))
        lats_arr = np.array(lats)
        lons_arr = np.array(lons)
        mask = np.isfinite(lats_arr) & np.isfinite(lons_arr)
        if not mask.any():
            return None
        lats_arr, lons_arr = lats_arr[mask], lons_arr[mask]

        lat_lo, lat_hi = lats_arr.min(), lats_arr.max()
        lon_lo, lon_hi = lons_arr.min(), lons_arr.max()
        margin = max(0.03, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.15)

        fig, ax = plt.subplots(figsize=(5, 4))

        gebco = _load_gebco(
            lat_lo, lat_hi, lon_lo, lon_hi, margin=margin, path=GEBCO_PATH
        )
        if gebco is not None:
            lons_b, lats_b, depth_b = gebco
            d_fin = depth_b[depth_b > 0]
            if len(d_fin):
                bounds_b = _nice_colorbar_bounds(
                    float(d_fin.min()), float(np.percentile(d_fin, 98)), n=12
                )
                cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
                norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
                LON2, LAT2 = np.meshgrid(lons_b, lats_b)
                ax.pcolormesh(
                    LON2,
                    LAT2,
                    depth_b,
                    cmap=cmap_b,
                    norm=norm_b,
                    shading="nearest",
                    rasterized=True,
                )

        ax.plot(lons_arr, lats_arr, "-", color="white", lw=1.2, zorder=3)
        ax.scatter(lons_arr, lats_arr, s=20, color="white", zorder=4)
        for x, y, n in zip(lons_arr, lats_arr, cast_nums):
            ax.annotate(
                str(n),
                (x, y),
                fontsize=6,
                color="black",
                xytext=(3, 3),
                textcoords="offset points",
            )

        ax.set_xlabel("Longitude (°E)")
        ax.set_ylabel("Latitude (°N)")
        ax.set_xlim(lon_lo - margin, lon_hi + margin)
        ax.set_ylim(lat_lo - margin, lat_hi + margin)
        if title:
            ax.set_title(title)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_overview_panel_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    bathy_depths: Optional[np.ndarray] = None,
    style: str = "pcolormesh",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> Optional[str]:
    """Return a base64 PNG of *var* vs pressure × cast number (cruise overview panel).

    *ds_prof* must already be filtered to downcasts and sorted by cast_number.
    X-axis positions are evenly spaced (0, 1, …, N-1) with cast numbers as tick labels.
    *bathy_depths* (m, same length as N_PROF) draws a filled black bathymetry below data.

    Parameters
    ----------
    vmin, vmax:
        Optional colormap limit overrides; auto from 1–99th percentile if ``None``.
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    """
    if var not in ds_prof:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        pressure = ds_prof["pressure"].values
        data = ds_prof[var].values  # (N_PROF, N_P)
        cast_nums = ds_prof["cast_number"].values.astype(int)

        valid_cols = np.where(np.any(np.isfinite(data), axis=0))[0]
        if not len(valid_cols):
            return None
        p_trim = pressure[: valid_cols[-1] + 1]
        data_trim = data[:, : valid_cols[-1] + 1]

        d_fin = data_trim[np.isfinite(data_trim)]
        if not len(d_fin):
            return None

        cmap_name = _VAR_CMAPS.get(var, "viridis")
        v0 = vmin if vmin is not None else float(np.percentile(d_fin, 1))
        v1 = vmax if vmax is not None else float(np.percentile(d_fin, 99))
        bounds = _nice_colorbar_bounds(v0, v1, n=20)
        cmap = plt.get_cmap(cmap_name, len(bounds) - 1)
        norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

        x_pos = np.arange(len(cast_nums), dtype=float)

        # Y extent: deeper of data max and bathy
        p_max_data = float(p_trim[-1])
        p_max_bathy = (
            float(np.nanmax(bathy_depths))
            if bathy_depths is not None and len(bathy_depths)
            else 0.0
        )
        y_bottom = max(p_max_data, p_max_bathy) * 1.05

        fig, ax = plt.subplots(figsize=(12, 4))

        if style == "contourf":
            X, Y = np.meshgrid(x_pos, p_trim)
            Z = np.ma.masked_invalid(data_trim.T)
            cf = ax.contourf(X, Y, Z, levels=bounds, cmap=cmap_name, extend="both")
            cb = fig.colorbar(cf, ax=ax, ticks=bounds[::2], pad=0.02)
        else:
            pc = ax.pcolormesh(
                x_pos, p_trim, data_trim.T, cmap=cmap, norm=norm, shading="nearest"
            )
            cb = fig.colorbar(pc, ax=ax, ticks=bounds[::2], pad=0.02)

        if bathy_depths is not None:
            ax.fill_between(
                x_pos, bathy_depths, y_bottom, color="black", step="mid", lw=0
            )

        cb.set_label(label)
        ax.set_ylim(y_bottom, 0)
        ax.set_ylabel("Pressure (dbar)")
        ax.set_xlabel("Cast number")
        ax.grid(True, alpha=0.2, color="white")

        n_casts = len(cast_nums)
        step = max(1, n_casts // 20)
        tick_idx = np.arange(0, n_casts, step)
        ax.set_xticks(x_pos[tick_idx])
        ax.set_xticklabels(
            [str(cast_nums[i]) for i in tick_idx], rotation=45, ha="right"
        )

        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_all_sections_map_b64(
    sections_data: list[dict[str, Any]],
    all_lats: list[float],
    all_lons: list[float],
) -> Optional[str]:
    """Return a base64 PNG showing all section tracks coloured by section.

    Parameters
    ----------
    sections_data:
        List of dicts with keys ``name``, ``color``, ``lats``, ``lons``.
    all_lats, all_lons:
        Positions of all casts drawn as a grey background scatter.
    """
    if not sections_data:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))

        all_s_lats = [y for s in sections_data for y in s["lats"]] + list(all_lats)
        all_s_lons = [x for s in sections_data for x in s["lons"]] + list(all_lons)
        finite_lats = [v for v in all_s_lats if np.isfinite(v)]
        finite_lons = [v for v in all_s_lons if np.isfinite(v)]
        if not finite_lats:
            return None

        lat_lo, lat_hi = min(finite_lats), max(finite_lats)
        lon_lo, lon_hi = min(finite_lons), max(finite_lons)
        margin = max(0.05, max(lat_hi - lat_lo, lon_hi - lon_lo) * 0.12)

        fig, ax = plt.subplots(figsize=(7, 6))

        gebco = _load_gebco(
            lat_lo, lat_hi, lon_lo, lon_hi, margin=margin, path=GEBCO_PATH
        )
        if gebco is not None:
            lons_b, lats_b, depth_b = gebco
            d_fin = depth_b[depth_b > 0]
            if len(d_fin):
                bounds_b = _nice_colorbar_bounds(
                    float(d_fin.min()), float(np.percentile(d_fin, 98)), n=12
                )
                cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
                norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
                LON2, LAT2 = np.meshgrid(lons_b, lats_b)
                ax.pcolormesh(
                    LON2,
                    LAT2,
                    depth_b,
                    cmap=cmap_b,
                    norm=norm_b,
                    shading="nearest",
                    rasterized=True,
                )

        if all_lats:
            fin = [
                np.isfinite(y) and np.isfinite(x) for y, x in zip(all_lats, all_lons)
            ]
            ax.scatter(
                [x for x, f in zip(all_lons, fin) if f],
                [y for y, f in zip(all_lats, fin) if f],
                s=8,
                color="0.7",
                zorder=2,
                alpha=0.5,
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
                lw=1.5,
                ms=4,
                zorder=4,
                label=sec["name"],
            )

        ax.set_xlabel("Longitude (°E)")
        ax.set_ylabel("Latitude (°N)")
        ax.set_xlim(lon_lo - margin, lon_hi + margin)
        ax.set_ylim(lat_lo - margin, lat_hi + margin)
        ax.legend(loc="best", fontsize=7, framealpha=0.7)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None


def _make_timeseries_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    title: str,
    style: str = "pcolormesh",
) -> Optional[str]:
    """Return a base64 PNG of *var* vs cast time × pressure.

    Parameters
    ----------
    style:
        ``"pcolormesh"`` (default) or ``"contourf"``.
    """
    if var not in ds_prof or "time_start" not in ds_prof:
        return None
    try:
        plt.style.use(str(_MPLSTYLE))
        pressure = ds_prof["pressure"].values
        data = ds_prof[var].values
        times = ds_prof["time_start"].values

        if "cast_type" in ds_prof:
            mask = ds_prof["cast_type"].values == "down"
            data = data[mask]
            times = times[mask]

        if not len(times):
            return None

        order = np.argsort(times)
        data = data[order]
        times = times[order]

        valid_cols = np.where(np.any(np.isfinite(data), axis=0))[0]
        if not len(valid_cols):
            return None
        p_trim = pressure[: valid_cols[-1] + 1]
        data_trim = data[:, : valid_cols[-1] + 1]

        d_fin = data_trim[np.isfinite(data_trim)]
        if not len(d_fin):
            return None

        cmap_name = _VAR_CMAPS.get(var, "viridis")
        bounds = _nice_colorbar_bounds(
            float(np.percentile(d_fin, 2)), float(np.percentile(d_fin, 98)), n=20
        )
        cmap = plt.get_cmap(cmap_name, len(bounds) - 1)
        norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

        import matplotlib.dates as mdates

        t_mpl = mdates.date2num(times.astype("datetime64[ms]").astype("O"))

        fig, ax = plt.subplots(figsize=(10, 5))
        pc = ax.pcolormesh(
            t_mpl, p_trim, data_trim.T, cmap=cmap, norm=norm, shading="nearest"
        )
        cb = fig.colorbar(pc, ax=ax, ticks=bounds, pad=0.02)
        cb.set_label(label)

        ax.xaxis_date()
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

        ax.set_ylim(float(p_trim[-1]), 0)
        ax.set_ylabel("Pressure (dbar)")
        ax.set_title(title)
        ax.grid(True, alpha=0.2, color="white")
        fig.tight_layout()
        b64 = _fig_to_base64(fig)
        plt.close(fig)
        return b64
    except Exception:  # noqa: BLE001
        return None
