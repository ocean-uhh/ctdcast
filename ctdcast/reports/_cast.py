"""Tier-2: generate a per-cast HTML report page."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.derive import derive_teos10 as add_teos10
from ctdcast.config.parameters import UNKNOWN_CRUISE_ID
from ctdcast.config.report_tokens import ROLE_ACCENT
from ctdcast.identity import cast_id_from_name, format_cast_id
from ctdcast.processors.stage2 import find_cast_end, find_soak_end
from ctdcast.readers.ladcp import find_ladcp_file
from ctdcast.readers.metadata import parse_sensor_info
from ctdcast.reports._report_css import _JS_TOP_LINKS, SHARED_CSS
from ctdcast.reports._env import get_template
from ctdcast.reports._format import _fmt_utc
from ctdcast.reports._plots import (
    _make_aux_profiles_b64,
    _make_ct_sa_sigma0_b64,
    _make_ladcp_bottomtrack_b64,
    _make_pressure_time_b64,
    _make_sensor_diff_b64,
    _make_stability_b64,
    _make_station_map_b64,
    _make_ts_density_b64,
    _make_ts_diagram_b64,
    _make_ts_updown_b64,
    _make_updown_diff_b64,
)


def _dec_to_ddm(deg: float, axis: str) -> str:
    """Convert decimal degrees to degrees-decimal-minutes string.

    Examples: 64.7415 lat → '64 44.49 N', -31.4003 lon → '031 24.02 W'.
    """
    hemi = ("N" if deg >= 0 else "S") if axis == "lat" else ("E" if deg >= 0 else "W")
    d = int(abs(deg))
    m = (abs(deg) - d) * 60.0
    if axis == "lon":
        return f"{d:03d}° {m:05.2f}′ {hemi}"
    return f"{d:02d}° {m:05.2f}′ {hemi}"


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def generate_station_page(
    nc_path: Path,
    out_dir: Path,
    all_meta: list[dict[str, Any]],
    prev_cast_str: str | None = None,
    next_cast_str: str | None = None,
    force: bool = False,
    ladcp_dir: Path | None = None,
    ladcp_pattern: str | None = None,
    cast_num_str: str | None = None,
    sal_range: tuple[float, float] | None = None,
    trim_soak: bool = False,
    cast_notes: list[str] | None = None,
    cruise_info: dict | None = None,
) -> Path | None:
    """Generate a per-cast HTML report page and write it to *out_dir/casts/*.

    Parameters
    ----------
    nc_path:
        Path to a single cast ``.nc`` file.
    out_dir:
        Root output directory.
    all_meta:
        List of dicts with keys ``lat``, ``lon`` for all casts (used for map).
    prev_cast_str:
        Full cast identifier string of the previous cast for nav links, e.g.
        ``"010"`` or ``"004b"`` (or None for no previous link).
    next_cast_str:
        Full cast identifier string of the next cast for nav links (or None).
    force:
        Overwrite existing file if True.
    ladcp_dir:
        Directory containing processed LADCP ``.mat`` files named ``NNN.mat``
        or ``NNNb.mat``.  If None or no matching file exists, LADCP panels
        are omitted.
    ladcp_pattern:
        Optional filename glob for non-standard LADCP naming conventions,
        e.g. ``"msm_142_1_*.mat"``.  The ``*`` is replaced with the
        zero-padded cast number.  Falls back to glob-based discovery when omitted.
    cast_num_str:
        Full cast identifier string, e.g. ``"011"`` or ``"004b"``.  Derived
        from *nc_path* if not provided.
    sal_range:
        ``(sal_min, sal_max)`` — records with ``salinity_1`` outside this
        range are excluded from all plots (but the NC file is not modified).
        The count of excluded records is shown in the page header.
    trim_soak:
        If True, apply pre-soak detection via :func:`~ctdcast.processors.stage2.find_soak_end`.
        Finds the last record within 10 dbar of the surface before the cast
        maximum depth, crawls back up to 20 seconds to the shallowest point
        preceding the real descent, and trims everything up to that point.
        Applied before *sal_range* trimming.  NC files are not modified.
    cast_notes:
        Optional list of free-text notes for this cast (e.g. "SBE43 malfunction").
        Rendered as warning banners near the top of the page.

    Returns
    -------
    Path to the written HTML file, or None on failure.

    """
    cast_num, cast_suffix = _cast_id_from_path(nc_path)
    if cast_num_str is None:
        cast_num_str = format_cast_id(cast_num, cast_suffix)
    out_file = out_dir / "casts" / f"cast_{cast_num_str}.html"
    if out_file.exists() and not force:
        return out_file

    out_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        ds = xr.open_dataset(nc_path, decode_timedelta=False, engine="netcdf4").load()
        sensor_info = parse_sensor_info(ds)
        ds = add_teos10(ds)
    except Exception:  # noqa: BLE001
        return None

    # Pre-soak and post-recovery trim (both applied when trim_soak is True)
    n_soak_trimmed = 0
    n_deck_trimmed = 0
    if trim_soak and "pressure" in ds and "time" in ds:
        p = ds["pressure"].values
        t = ds["time"].values
        n_total_records = len(t)
        soak_end = find_soak_end(p, t)
        cast_end = find_cast_end(p, t)
        if cast_end <= soak_end:
            cast_end = n_total_records
        n_soak_trimmed = max(0, soak_end)
        n_deck_trimmed = (
            (n_total_records - cast_end) if cast_end < n_total_records else 0
        )
        if n_soak_trimmed > 0 or n_deck_trimmed > 0:
            ds = ds.isel(
                time=slice(
                    soak_end if soak_end > 0 else None,
                    cast_end if cast_end < n_total_records else None,
                )
            )

    # Salinity range trim (applied after soak trim)
    n_sal_trimmed = 0
    sal_lo = sal_hi = 0.0
    _sal_var = next(
        (v for v in ("ctd_salinity", "ctd_salinity_1", "salinity_1") if v in ds), None
    )
    if sal_range is not None and _sal_var is not None:
        sal_lo, sal_hi = sal_range
        sal_vals = ds[_sal_var].values
        mask = (sal_vals >= sal_lo) & (sal_vals <= sal_hi) & np.isfinite(sal_vals)
        n_sal_trimmed = int((~mask).sum())
        if n_sal_trimmed > 0:
            ds = ds.isel(time=mask)

    # Build a single human-readable trim note for the page header
    trim_note = ""
    soak_parts = []
    if n_soak_trimmed > 0:
        soak_parts.append(f"{n_soak_trimmed} pre-soak")
    if n_deck_trimmed > 0:
        soak_parts.append(f"{n_deck_trimmed} post-recovery")
    if n_sal_trimmed > 0:
        soak_parts.append(f"{n_sal_trimmed} salinity outside [{sal_lo}, {sal_hi}]")
    if soak_parts:
        n_total = n_soak_trimmed + n_deck_trimmed + n_sal_trimmed
        trim_note = f"{n_total} records excluded ({', '.join(soak_parts)})"

    lat = float(np.nanmedian(ds["latitude"].values))
    lon = float(np.nanmedian(ds["longitude"].values))
    max_depth = float(np.nanmax(ds["pressure"].values))
    t_raw = ds["time"].values
    t0 = _fmt_utc(t_raw[0])
    t_end = _fmt_utc(t_raw[-1])
    dur_s = int((t_raw[-1] - t_raw[0]) / np.timedelta64(1, "s"))
    dur_h, dur_rem = divmod(dur_s, 3600)
    dur_m = dur_rem // 60
    duration_str = f"{dur_h}h {dur_m:02d}m"
    _ci = cruise_info or {}
    cruise = _ci.get("cruise_id") or ds.attrs.get("cruise", UNKNOWN_CRUISE_ID)
    ship = (
        _ci.get("ship")
        or ds.attrs.get("ship")
        or ds.attrs.get("platform")
        or ds.attrs.get("vessel")
        or "UNK"
    )

    ladcp_path: Path | None = None
    if ladcp_dir is not None:
        found = find_ladcp_file(ladcp_dir, cast_num, cast_suffix, ladcp_pattern)
        # Keep a non-None path even when no file exists so downstream callers
        # that gate on ladcp_dir-is-not-None still get the LADCP plot layout.
        ladcp_path = (
            found
            if found is not None
            else ladcp_dir / f"{format_cast_id(cast_num, cast_suffix)}.mat"
        )
    ladcp_exists = ladcp_path is not None and ladcp_path.exists()

    ctx: dict[str, Any] = {
        "cast_num": cast_num_str,
        "cruise": cruise,
        "ship": ship,
        "datetime_str": t0,
        "time_end_str": t_end,
        "duration_str": duration_str,
        "lat_str": _dec_to_ddm(lat, "lat"),
        "lon_str": _dec_to_ddm(lon, "lon"),
        "max_depth_str": f"{max_depth:.0f} dbar",
        "prev_num": prev_cast_str or "",
        "next_num": next_cast_str or "",
        "ladcp_configured": ladcp_dir is not None,
        "ladcp_available": ladcp_exists,
        "trim_note": trim_note,
        "cast_notes": cast_notes or [],
        "sensor_info": sensor_info,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "version": _VERSION,
        # Overview row — CT/SA/σ₀ triple-axis + LADCP U/V panel
        "fig_ts_density_b64": _make_ts_density_b64(
            ds, ladcp_path if ladcp_dir is not None else None
        ),
        "fig_station_map_b64": _make_station_map_b64(lat, lon, all_meta, target_h=2.75),
        "fig_ts_updown_b64": _make_ts_updown_b64(ds),
        # Row 2
        "fig_ct_sa_sigma0_b64": _make_ct_sa_sigma0_b64(ds),
        # Row 3
        "fig_aux_b64": _make_aux_profiles_b64(ds),
        # Row 4
        "fig_ts_diagram_b64": _make_ts_diagram_b64(ds),
        # Row 5
        "fig_stability_b64": _make_stability_b64(ds),
        # Row 6: diagnostics
        "fig_pressure_time_b64": _make_pressure_time_b64(ds),
        "fig_sensor_diff_b64": _make_sensor_diff_b64(ds),
        "fig_updown_diff_b64": _make_updown_diff_b64(ds),
        # Row 7: LADCP bottom track
        "fig_ladcp_bottomtrack_b64": _make_ladcp_bottomtrack_b64(ladcp_path)
        if ladcp_exists
        else None,
    }

    html = get_template("cast.html").render(
        **ctx,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix="../",
        nav_current="casts",
        masthead_bg=ROLE_ACCENT["entity"],
    )
    out_file.write_text(html, encoding="utf-8")
    ds.close()
    return out_file


def _cast_id_from_path(nc_path: Path) -> tuple[int, str]:
    """Return ``(cast_num, cast_suffix)`` from a cast filename.

    Thin wrapper over :func:`ctdcast.identity.cast_id_from_name` that falls back
    to ``(0, "")`` when the stem contains no 3+-digit cast number.
    """
    return cast_id_from_name(nc_path.stem) or (0, "")
