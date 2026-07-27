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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to GEBCO_2025.nc — set this before generating maps, e.g.:
#   import ctd_report; ctd_report._plots.GEBCO_PATH = Path("/data/GEBCO_2025.nc")
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
    "fluorescence": "Fluorescence (mg m⁻³)",
    "turbidity": "Turbidity (NTU)",
    "sigma0": "σ₀ (kg m⁻³)",
    "density": "Density (kg m⁻³)",
}


# ---------------------------------------------------------------------------
# Internal utilities (self-contained, no external package dependencies)
# ---------------------------------------------------------------------------

def _fig_to_base64(fig: Any) -> str:
    """Render *fig* to a PNG and return its base64-encoded bytes as a string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _nice_colorbar_bounds(vmin: float, vmax: float, n: int = 20) -> np.ndarray:
    """Return a boundary array for a discrete colorbar with approximately *n* levels.

    The step is rounded to 1 significant figure so tick labels land on clean values.
    The range is centred on the midpoint of [vmin, vmax].
    """
    span = vmax - vmin
    if span <= 0:
        return np.linspace(vmin - 1, vmin + 1, n + 1)
    raw_step = span / n
    mag = 10.0 ** math.floor(math.log10(raw_step))
    rounded = round(raw_step / mag)
    if rounded == 0:
        rounded = 1
    elif rounded >= 10:
        mag *= 10
        rounded = 1
    nice_step = rounded * mag
    mid = (vmin + vmax) / 2
    mid_aligned = round(mid / nice_step) * nice_step
    lo = mid_aligned - (n / 2) * nice_step
    return np.array([lo + i * nice_step for i in range(n + 1)])


def _add_teos10(ds: xr.Dataset) -> xr.Dataset:
    """Return *ds* with CT, SA, sigma0 added (computed via gsw if absent)."""
    if "CT" in ds and "SA" in ds and "sigma0" in ds:
        return ds
    ds = ds.copy()
    p = ds["pressure"].values.astype(float)
    t = ds["temperature_1"].values.astype(float)
    sp = ds["salinity_1"].values.astype(float)
    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    sa = gsw.SA_from_SP(sp, p, lon, lat)
    ct = gsw.CT_from_t(sa, t, p)
    sig0 = gsw.sigma0(sa, ct)
    dim = ds["pressure"].dims[0]
    ds["SA"] = xr.DataArray(sa.astype(np.float32), dims=[dim],
                             attrs={"long_name": "Absolute Salinity", "units": "g kg-1"})
    ds["CT"] = xr.DataArray(ct.astype(np.float32), dims=[dim],
                             attrs={"long_name": "Conservative Temperature", "units": "degC"})
    ds["sigma0"] = xr.DataArray(sig0.astype(np.float32), dims=[dim],
                                 attrs={"long_name": "Potential density anomaly",
                                        "units": "kg m-3"})
    return ds


def _split_cast(ds: xr.Dataset) -> tuple[xr.Dataset, xr.Dataset]:
    """Split *ds* (individual cast file, dim=time) into (downcast, upcast).

    Uses the turnaround convention: last index where pressure is within 2 dbar
    of its maximum.
    """
    p = ds["pressure"].values
    p_max = float(np.nanmax(p))
    near = np.where(p >= p_max - 2)[0]
    i_turn = int(near[-1]) if len(near) else len(p) // 2
    return ds.isel(time=slice(0, i_turn + 1)), ds.isel(time=slice(i_turn, None))


def _load_gebco(
    lat_lo: float, lat_hi: float, lon_lo: float, lon_hi: float, margin: float = 0.05
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Load a GEBCO subset; return (lons, lats, depth_m) or None if unavailable."""
    path = GEBCO_PATH
    if path is None or not Path(path).exists():
        return None
    try:
        bathy = xr.open_dataset(path)
        lon_dim = "lon" if "lon" in bathy.coords else "longitude"
        lat_dim = "lat" if "lat" in bathy.coords else "latitude"
        sub = bathy.sel({
            lon_dim: slice(lon_lo - margin, lon_hi + margin),
            lat_dim: slice(lat_lo - margin, lat_hi + margin),
        })
        lons = sub[lon_dim].values
        lats = sub[lat_dim].values
        depth = -sub["elevation"].values  # GEBCO: negative = below sea level
        bathy.close()
        return lons, lats, depth
    except Exception:  # noqa: BLE001
        return None


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
            ax.plot(v_up, p_up, color="#d62728", alpha=0.7, label="upcast")
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

        l0, = ax0.plot(ct,  p, color=_TS_COLORS[0], label="CT")
        l1, = ax1.plot(sa,  p, color=_TS_COLORS[1], label="SA")
        l2, = ax2.plot(sig, p, color=_TS_COLORS[2], label="σ₀")

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
        labels = [l.get_label() for l in lines]
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
        bounds = _nice_colorbar_bounds(float(np.nanpercentile(o2_fin, 2)),
                                       float(np.nanpercentile(o2_fin, 98)), n=16)
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
        ax_tu.axvline(45,  color="k", lw=0.8, ls="--")
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
    """Return a base64 PNG of O₂ sat, fluorescence, turbidity profiles."""
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
        ds_down, _ = _split_cast(ds)
        p = ds_down["pressure"].values

        fig, axes = plt.subplots(1, len(available), figsize=(3.5 * len(available), 7),
                                  sharey=True)
        if len(available) == 1:
            axes = [axes]

        colors = ["#1b7837", "#762a83", "#bf812d"]
        for ax, (var, label), color in zip(axes, available, colors):
            v = ds_down[var].values
            ax.plot(v, p, color=color)
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

        gebco = _load_gebco(lat_lo, lat_hi, lon_lo, lon_hi, margin=margin)
        if gebco is not None:
            lons_b, lats_b, depth_b = gebco
            d_fin = depth_b[depth_b > 0]
            if len(d_fin):
                bounds_b = _nice_colorbar_bounds(float(d_fin.min()),
                                                 float(np.percentile(d_fin, 98)), n=14)
                cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
                norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
                LON2, LAT2 = np.meshgrid(lons_b, lats_b)
                ax.pcolormesh(LON2, LAT2, depth_b, cmap=cmap_b, norm=norm_b,
                              shading="nearest", rasterized=True)

        ax.scatter(all_lons, all_lats, s=12, color="0.5", zorder=3, label="all casts")
        ax.scatter([lon], [lat], s=60, color="#d62728", zorder=5, label="this cast",
                   marker="*")
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


def _make_section_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    x_vals: np.ndarray,
    x_label: str,
    title: str,
) -> Optional[str]:
    """Return a base64 PNG pcolormesh of *var* vs pressure × *x_vals*."""
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
        bounds = _nice_colorbar_bounds(
            float(np.percentile(d_fin, 2)), float(np.percentile(d_fin, 98)), n=20
        )
        cmap = plt.get_cmap(cmap_name, len(bounds) - 1)
        norm = mcolors.BoundaryNorm(bounds, ncolors=cmap.N)

        fig, ax = plt.subplots(figsize=(9, 5))
        pc = ax.pcolormesh(x_vals, p_trim, data_trim.T, cmap=cmap, norm=norm,
                           shading="nearest")
        cb = fig.colorbar(pc, ax=ax, ticks=bounds, pad=0.02)
        cb.set_label(label)

        ax.set_ylim(float(p_trim[-1]), 0)
        ax.set_ylabel("Pressure (dbar)")
        ax.set_xlabel(x_label)
        ax.set_title(title)
        ax.grid(True, alpha=0.2, color="white")
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

        gebco = _load_gebco(lat_lo, lat_hi, lon_lo, lon_hi, margin=margin)
        if gebco is not None:
            lons_b, lats_b, depth_b = gebco
            d_fin = depth_b[depth_b > 0]
            if len(d_fin):
                bounds_b = _nice_colorbar_bounds(float(d_fin.min()),
                                                 float(np.percentile(d_fin, 98)), n=12)
                cmap_b = plt.get_cmap("Blues", len(bounds_b) - 1)
                norm_b = mcolors.BoundaryNorm(bounds_b, ncolors=cmap_b.N)
                LON2, LAT2 = np.meshgrid(lons_b, lats_b)
                ax.pcolormesh(LON2, LAT2, depth_b, cmap=cmap_b, norm=norm_b,
                              shading="nearest", rasterized=True)

        ax.plot(lons_arr, lats_arr, "-", color="white", lw=1.2, zorder=3)
        ax.scatter(lons_arr, lats_arr, s=20, color="white", zorder=4)
        for x, y, n in zip(lons_arr, lats_arr, cast_nums):
            ax.annotate(str(n), (x, y), fontsize=6, color="white",
                        xytext=(3, 3), textcoords="offset points")

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


def _make_timeseries_b64(
    ds_prof: xr.Dataset,
    var: str,
    label: str,
    title: str,
) -> Optional[str]:
    """Return a base64 PNG pcolormesh of *var* vs cast time × pressure."""
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
        pc = ax.pcolormesh(t_mpl, p_trim, data_trim.T, cmap=cmap, norm=norm,
                           shading="nearest")
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
