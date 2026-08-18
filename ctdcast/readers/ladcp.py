"""Reader for LDEO IXv14 LADCP ``.mat`` files.

Locates the ``.mat`` file for a cast (:func:`find_ladcp_file`), loads it with a
single set of ``scipy.io.loadmat`` options (:func:`read_ladcp`), and maps the
result struct to a single-cast :class:`xarray.Dataset` on the native 10 m depth
grid (:func:`read_ladcp_cast`).  The ``.mat`` is the LDEO IX velocity *solution*;
its ~50 fields are mapped to the compiled-dataset schema in
``.claude/notes/2026-08-17-ladcp-compiled-dataset.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast.identity import format_cast_id


def read_ladcp(path: Path | str) -> dict[str, Any]:
    """Load an LDEO IXv14 LADCP ``.mat`` file.

    Uses ``squeeze_me=True`` and ``struct_as_record=False`` so the LADCP result
    struct is reachable as ``read_ladcp(path)["dr"]`` with attribute access.
    """
    import scipy.io

    return scipy.io.loadmat(str(path), squeeze_me=True, struct_as_record=False)


def _field(struct: Any, name: str, default: Any = None) -> Any:
    """Return ``struct.name`` if present, else *default* (structs vary by cruise)."""
    return getattr(struct, name, default)


def _profile(struct: Any, name: str, n: int) -> np.ndarray:
    """Return ``struct.name`` as a length-*n* float array, or all-NaN when absent."""
    val = _field(struct, name)
    if val is None:
        return np.full(n, np.nan)
    arr = np.asarray(val, dtype=float).ravel()
    if arr.shape != (n,):
        return np.full(n, np.nan)
    return arr


def _instrument_config(dr: Any, ps: Any, n: int) -> str:
    """Return which ADCP(s) provided valid data for this cast.

    On OdB both were always installed but one was sometimes corrupted, so this is
    per-cast data *validity*, not fixed hardware.  Derived from the finiteness of
    the downlooker/uplooker-only solutions (a corrupted instrument's profile is
    all-NaN), which is robust to the empty ``f.ladcpup`` path seen on some casts.
    ``ps.down_up`` is used only as a fallback when neither profile is present.
    """
    has_do = np.isfinite(_profile(dr, "u_do", n)).any()
    has_up = np.isfinite(_profile(dr, "u_up", n)).any()
    if has_do and has_up:
        return "both"
    if has_do:
        return "downlooker"
    if has_up:
        return "uplooker"
    return {1: "downlooker", 2: "uplooker", 3: "both"}.get(
        int(_field(ps, "down_up", 0) or 0), "unknown"
    )


def read_ladcp_cast(
    path: Path | str, *, cast_num: int, cast_suffix: str = ""
) -> xr.Dataset:
    """Map an LDEO LADCP ``.mat`` to a single-cast Dataset on the native 10 m grid.

    Returns a Dataset with dimension ``depth`` (uniform 10 m, positive down), an
    auxiliary ``pressure(depth)`` coordinate (dbar, the bridge to ``profiles.nc``),
    the inverse (``u``/``v``) and shear (``u_shear``/``v_shear``/``w_shear``)
    velocity solutions, per-instrument down/up-looker profiles, per-cast scalars
    (barotropic, bottom-track, position, ``instrument_config``), and the LADCP
    processing provenance as global attributes.  Velocity carries the CF
    ``eastward``/``northward``/``error_sea_water_velocity`` standard names.
    """
    m = read_ladcp(path)
    dr, ps, da = m["dr"], m.get("ps"), m.get("da")

    depth = np.asarray(_field(dr, "z"), dtype=float).ravel()
    n = depth.size

    data_vars: dict[str, tuple] = {
        "u": ("depth", _profile(dr, "u", n), {"standard_name": "eastward_sea_water_velocity"}),
        "v": ("depth", _profile(dr, "v", n), {"standard_name": "northward_sea_water_velocity"}),
        "u_shear": ("depth", _profile(dr, "u_shear_method", n), {"standard_name": "eastward_sea_water_velocity"}),
        "v_shear": ("depth", _profile(dr, "v_shear_method", n), {"standard_name": "northward_sea_water_velocity"}),
        "w_shear": ("depth", _profile(dr, "w_shear_method", n), {"standard_name": "upward_sea_water_velocity"}),
        "u_error": ("depth", _profile(dr, "uerr", n), {"standard_name": "error_sea_water_velocity"}),
        "ensemble_vel_err": ("depth", _profile(dr, "ensemble_vel_err", n), {"long_name": "ensemble velocity error", "units": "m s-1"}),
        "nvel": ("depth", _profile(dr, "nvel", n), {"long_name": "number of velocity samples per bin"}),
        "profiling_range": ("depth", _profile(dr, "range", n), {"long_name": "effective acoustic profiling range at each depth bin", "units": "m"}),
        "u_downlooker": ("depth", _profile(dr, "u_do", n), {"standard_name": "eastward_sea_water_velocity"}),
        "v_downlooker": ("depth", _profile(dr, "v_do", n), {"standard_name": "northward_sea_water_velocity"}),
        "u_uplooker": ("depth", _profile(dr, "u_up", n), {"standard_name": "eastward_sea_water_velocity"}),
        "v_uplooker": ("depth", _profile(dr, "v_up", n), {"standard_name": "northward_sea_water_velocity"}),
        "target_strength": ("depth", _profile(dr, "ts", n), {"long_name": "target strength, 2nd downlooker bin (dB, RDI 0.45, median of 4 beams, super-ensemble averaged)", "units": "dB"}),
        "target_strength_out": ("depth", _profile(dr, "ts_out", n), {"long_name": "target strength, last downlooker bin (dB, RDI 0.45, median of 4 beams, super-ensemble averaged)", "units": "dB"}),
    }
    for name, (_dim, _arr, attrs) in data_vars.items():
        if name.startswith(("u", "v", "w")) and name != "nvel":
            attrs.setdefault("units", "m s-1")

    # Bottom-track: both bottom bins kept (Eleanor 2026-08-18), on a small
    # ``bottom_track`` dimension rather than collapsed to a per-cast mean.
    ubot = np.asarray(_field(dr, "ubot", np.nan), dtype=float).ravel()
    vbot = np.asarray(_field(dr, "vbot", np.nan), dtype=float).ravel()
    zbot = np.asarray(_field(dr, "zbot", np.nan), dtype=float).ravel()
    bt_vars: dict[str, tuple] = {
        "u_bottom": (("bottom_track",), ubot, {"long_name": "bottom-track eastward velocity per bottom bin", "units": "m s-1", "standard_name": "eastward_sea_water_velocity"}),
        "v_bottom": (("bottom_track",), vbot, {"long_name": "bottom-track northward velocity per bottom bin", "units": "m s-1", "standard_name": "northward_sea_water_velocity"}),
        "z_bottom": (("bottom_track",), zbot, {"long_name": "bottom-track bin depth", "units": "m", "positive": "down"}),
    }

    def _scalar(v: Any, dtype: type = float) -> Any:
        return dtype(v) if v is not None and np.isscalar(v) else dtype(np.nan)

    scalars: dict[str, tuple] = {
        "cast_number": ((), np.int32(cast_num), {}),
        "cast_suffix": ((), cast_suffix, {}),
        "latitude": ((), _scalar(_field(dr, "lat")), {"standard_name": "latitude", "units": "degrees_north"}),
        "longitude": ((), _scalar(_field(dr, "lon")), {"standard_name": "longitude", "units": "degrees_east"}),
        "u_barotropic": ((), _scalar(_field(dr, "ubar")), {"long_name": "barotropic (depth-mean) eastward velocity", "units": "m s-1"}),
        "v_barotropic": ((), _scalar(_field(dr, "vbar")), {"long_name": "barotropic (depth-mean) northward velocity", "units": "m s-1"}),
        "instrument_config": ((), _instrument_config(dr, ps, n), {"long_name": "ADCP instrument(s) with valid data for this cast", "flag_values": "both downlooker uplooker unknown"}),
    }
    if da is not None:
        for src, dst, attrs in (
            ("GEN_Ocean_depth_m", "ocean_depth", {"long_name": "ocean depth", "units": "m", "positive": "down"}),
            ("GEN_Magnetic_deviation_deg", "magnetic_deviation_deg", {"long_name": "magnetic deviation", "units": "degree"}),
        ):
            val = _field(da, src)
            if val is not None and np.isscalar(val):
                scalars[dst] = ((), float(val), attrs)

    ds = xr.Dataset(
        data_vars={**data_vars, **bt_vars, **scalars},
        coords={
            "depth": ("depth", depth, {"standard_name": "depth", "units": "m", "positive": "down"}),
            "pressure": ("depth", _profile(dr, "p", n), {"standard_name": "sea_water_pressure", "units": "dbar"}),
            # Integer index so the compiler can pad the (per-cast-varying) count.
            "bottom_track": ("bottom_track", np.arange(ubot.size)),
        },
    )
    ds["time"] = ((), _ladcp_time(dr))
    ds = ds.set_coords(["cast_number", "cast_suffix", "latitude", "longitude", "time"])
    ds.attrs.update(_provenance_attrs(dr, ps, da))
    return ds


def _ladcp_time(dr: Any) -> np.datetime64:
    """Return the cast time from ``dr.date`` ([Y, M, D, h, m, s]), or NaT."""
    date = _field(dr, "date")
    if date is None:
        return np.datetime64("NaT")
    try:
        y, mo, d, h, mi, s = (int(x) for x in np.asarray(date).ravel()[:6])
        return np.datetime64(f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}")
    except (ValueError, TypeError):
        return np.datetime64("NaT")


def _provenance_attrs(dr: Any, ps: Any, da: Any) -> dict[str, Any]:
    """Collect LADCP processing provenance from the structs into global attrs."""
    attrs: dict[str, Any] = {"source": "LDEO IXv14 LADCP .mat solution"}
    name = _field(dr, "name")
    if name is not None:
        attrs["ladcp_cast_name"] = str(name)
    if da is not None:
        for src, key in (
            ("GEN_Processing_date", "ladcp_processing_date"),
            ("GEN_Processing_personnel", "ladcp_processing_personnel"),
            ("GEN_Proc_methodology", "ladcp_processing_methodology"),
            ("GEN_Velocity_Units", "ladcp_velocity_units"),
            ("GEN_Depth_source", "ladcp_depth_source"),
            ("GEN_Percent_3beam", "ladcp_percent_3beam"),
            ("GEN_Inverse_weight_bottom", "ladcp_inverse_weight_bottom"),
            ("GEN_Inverse_weight_navigation", "ladcp_inverse_weight_navigation"),
            ("GEN_Inverse_weight_smooth", "ladcp_inverse_weight_smooth"),
            ("LADCP_dn_hard_SN", "ladcp_downlooker_serial"),
            ("LADCP_dn_hard_freq_kHz", "ladcp_downlooker_freq_khz"),
            ("LADCP_dn_hard_beam_ang_deg", "ladcp_downlooker_beam_angle_deg"),
        ):
            val = _field(da, src)
            if val is not None:
                attrs[key] = str(val) if isinstance(val, str) else float(val) if np.isscalar(val) else str(val)
    if ps is not None:
        dz = _field(ps, "dz")
        if dz is not None and np.isscalar(dz):
            attrs["ladcp_grid_step_m"] = float(dz)
    return attrs


def find_ladcp_file(
    ladcp_dir: Path,
    cast_num: int,
    cast_suffix: str = "",
    ladcp_pattern: str | None = None,
) -> Path | None:
    """Return the .mat file for *cast_num* in *ladcp_dir*, or ``None`` if absent.

    If *ladcp_pattern* is given (e.g. ``"msm_142_1_*.mat"``), the ``*``
    wildcard is replaced with the zero-padded cast number (and optional suffix)
    and that name is tried first.  Falls back to standard names (``NNN.mat``,
    ``NNNb.mat``) then a ``*_NNN.mat`` glob for cruise-prefixed filenames.
    The first glob match (lexicographic) is returned when multiple files match.
    """
    _id, _id_plain = format_cast_id(cast_num, cast_suffix), format_cast_id(cast_num)
    if ladcp_pattern:
        for cast_str in (_id, _id_plain):
            p = ladcp_dir / ladcp_pattern.replace("*", cast_str)
            if p.exists():
                return p
    for name in (f"{_id}.mat", f"{_id_plain}.mat"):
        p = ladcp_dir / name
        if p.exists():
            return p
    for glob_pat in (f"*_{_id}.mat", f"*_{_id_plain}.mat"):
        found = sorted(ladcp_dir.glob(glob_pat))
        if found:
            return found[0]
    return None
