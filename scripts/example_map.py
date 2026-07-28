from collections import Counter
from pathlib import Path

import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
import yaml

_repo_sm = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
_GEBCO = _repo_sm.parent / "cruiseplan" / "data" / "bathymetry" / "GEBCO_2025.nc"
_SECTIONS_YAML = _repo_sm / "config" / "ctd_sections.yaml"
_ACTIVITIES_YAML = _repo_sm / "config" / "cruise_activities.yaml"
_PROFILES_SM = Path("/Volumes/T9ifmeo/odb2026/CTD/profiles.nc")
_OUT_SM = _repo_sm / "outputs"

GEBCO_STRIDE = 4  # every Nth point after isel subset (~1 arc-min from 15" source)
CLUSTER_KM = 1.0  # casts within this distance share one dot and a combined label
MOORING_COLOR = "#4472c4"  # steel-blue label color for moorings

# ---- Parse sections --------------------------------------------------------

with open(_SECTIONS_YAML) as _f:
    _sec_cfg = yaml.safe_load(_f)["sections"]


def _expand_casts(spec):
    """Expand [[a,b], c, ...] or [a,b,...] to a flat list of ints."""
    out = []
    for item in spec:
        if isinstance(item, list) and len(item) == 2:
            out.extend(range(int(item[0]), int(item[1]) + 1))
        else:
            out.append(int(item))
    return out


_cast_to_section: dict[int, str] = {}
_section_colors: dict[str, str] = {}
for _sname, _sdef in _sec_cfg.items():
    _section_colors[_sname] = _sdef.get("color", "#999999")
    for _cn in _expand_casts(_sdef["cast_numbers"]):
        _cast_to_section[_cn] = _sname

# ---- Load downcast positions -----------------------------------------------

_ctd_sm = xr.open_dataset(_PROFILES_SM)
_mask_dn = _ctd_sm["cast_type"].values == "down"
_cnums = _ctd_sm["cast_number"].values[_mask_dn].astype(int)
_clats = _ctd_sm["latitude"].values[_mask_dn]
_clons = _ctd_sm["longitude"].values[_mask_dn]
_ctd_sm.close()

# ---- Load mooring positions from cruise_activities.yaml --------------------


def _parse_coord_sm(raw):
    """Parse decimal-degree or DMS string to signed decimal degrees."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    parts = str(raw).strip().split()
    try:
        if len(parts) == 1:
            return float(parts[0])
        deg = float(parts[0])
        mins = float(parts[1]) if len(parts) > 1 else 0.0
        if len(parts) >= 3:
            hemi = parts[2].upper()
            val = abs(deg) + mins / 60.0
            return -val if hemi in ("S", "W") else val
        sign = -1.0 if deg < 0 else 1.0
        return sign * (abs(deg) + mins / 60.0)
    except (ValueError, IndexError):
        return None


_moorings_sm: list[dict] = []
if _ACTIVITIES_YAML.exists():
    with open(_ACTIVITIES_YAML) as _f:
        _act = yaml.safe_load(_f)
    for _op in _act.get("operations", []):
        if not isinstance(_op, dict) or "moorings" not in _op:
            continue
        for _m in _op["moorings"]:
            _label = _m.get("mooring", "?")
            _cfg_path = Path(_m.get("config", ""))
            if not _cfg_path.exists():
                print(f"  [skip] {_label}: config not found: {_cfg_path}")
                continue
            with open(_cfg_path) as _f:
                _mcfg = yaml.safe_load(_f)
            _mlat = _parse_coord_sm(
                _mcfg.get("deployment_latitude") or _mcfg.get("latitude")
            )
            _mlon = _parse_coord_sm(
                _mcfg.get("deployment_longitude") or _mcfg.get("longitude")
            )
            if _mlat is None or _mlon is None:
                print(f"  [skip] {_label}: no lat/lon in {_cfg_path.name}")
                continue
            _moorings_sm.append({"label": _label, "lat": _mlat, "lon": _mlon})
    print(f"Loaded {len(_moorings_sm)} mooring positions")
else:
    print(
        f"WARNING: {_ACTIVITIES_YAML} not found — mooring positions will not be plotted"
    )

# ---- Map extent ------------------------------------------------------------

_lat0 = _clats.min() - 0.15
_lat1 = _clats.max() + 0.15
_lon0 = _clons.min() - 0.3
_lon1 = _clons.max() + 0.3

# ---- Cluster casts within CLUSTER_KM ---------------------------------------


def _flat_dist_km(lat1, lon1, lat_arr, lon_arr):
    dlat = np.radians(lat1 - lat_arr)
    dlon = np.radians(lon1 - lon_arr)
    mlat_r = np.radians((lat1 + lat_arr) / 2)
    return np.sqrt((dlat * 6371) ** 2 + (dlon * 6371 * np.cos(mlat_r)) ** 2)


_taken = np.zeros(len(_cnums), dtype=bool)
_clusters = []
for _i in range(len(_cnums)):
    if _taken[_i]:
        continue
    _near = np.where(
        (_flat_dist_km(_clats[_i], _clons[_i], _clats, _clons) < CLUSTER_KM) & ~_taken
    )[0]
    for _j in _near:
        _taken[_j] = True
    _clusters.append(_near.tolist())


def _fmt_cluster_label(cast_list):
    nums = sorted(cast_list)
    if len(nums) <= 5:
        return "\n".join(str(n) for n in nums)
    return f"{nums[0]}–{nums[-1]}\n({len(nums)})"


# ---- Figure ----------------------------------------------------------------

fig_sm, ax_sm = plt.subplots(figsize=(13, 9))

# GEBCO: isel subset on disk, then stride-downsample before contourf
if _GEBCO.exists():
    _b = xr.open_dataset(_GEBCO)
    _blat_g = _b["lat"].values
    _blon_g = _b["lon"].values
    _li = np.where((_blat_g >= _lat0) & (_blat_g <= _lat1))[0]
    _oi = np.where((_blon_g >= _lon0) & (_blon_g <= _lon1))[0]
    _dep = -_b["elevation"].isel(lat=_li, lon=_oi).values
    _b.close()
    _blat2 = _blat_g[_li][::GEBCO_STRIDE]
    _blon2 = _blon_g[_oi][::GEBCO_STRIDE]
    _dep2 = _dep[::GEBCO_STRIDE, ::GEBCO_STRIDE]
    ax_sm.contourf(
        _blon2,
        _blat2,
        _dep2,
        levels=np.arange(0, 2001, 100),
        cmap="Blues",
        alpha=0.35,
        vmin=0,
        vmax=2000,
    )
    ax_sm.contour(
        _blon2,
        _blat2,
        _dep2,
        levels=[200, 500, 700, 1000, 1500],
        colors="steelblue",
        linewidths=0.4,
        alpha=0.6,
    )
else:
    print(f"GEBCO not found: {_GEBCO} — skipping bathymetry background")

# Mooring positions — zorder 2 so CTD stations plot on top
for _moor in _moorings_sm:
    ax_sm.plot(
        _moor["lon"],
        _moor["lat"],
        "^",
        color=MOORING_COLOR,
        ms=10,
        mfc="white",
        mew=1.5,
        zorder=2,
    )
    ax_sm.annotate(
        _moor["label"].split("_")[0],
        (_moor["lon"], _moor["lat"]),
        xytext=(5, 4),
        textcoords="offset points",
        fontsize=7,
        color=MOORING_COLOR,
        fontweight="bold",
        zorder=3,
    )

# CTD clusters — one dot per group, all cast numbers listed
_unassigned_casts: list[int] = []
for _grp in _clusters:
    _clat_c = float(np.mean(_clats[_grp]))
    _clon_c = float(np.mean(_clons[_grp]))
    _casts = [int(_cnums[_k]) for _k in _grp]
    _secs = [_cast_to_section.get(_c) for _c in _casts]
    _good = [s for s in _secs if s is not None]

    if not _good:
        _unassigned_casts.extend(_casts)
        _color, _marker, _mew = "#aaaaaa", "x", 1.0
    else:
        _color = _section_colors[Counter(_good).most_common(1)[0][0]]
        _marker, _mew = "o", 0

    ax_sm.plot(
        _clon_c, _clat_c, _marker, color=_color, ms=7, mew=_mew, alpha=0.85, zorder=4
    )
    ax_sm.annotate(
        _fmt_cluster_label(_casts),
        (_clon_c, _clat_c),
        xytext=(4, 0),
        textcoords="offset points",
        fontsize=5,
        color="#333333",
        zorder=5,
        va="center",
    )

# Legend — lower right
_handles = [
    mpatches.Patch(color=col, label=sec) for sec, col in _section_colors.items()
]
_handles.append(mpatches.Patch(color="#aaaaaa", label="unassigned (not in YAML)"))
_handles.append(
    mlines.Line2D(
        [0],
        [0],
        marker="^",
        color=MOORING_COLOR,
        mfc="white",
        ms=8,
        lw=0,
        label="mooring",
    )
)
ax_sm.legend(
    handles=_handles,
    loc="lower right",
    fontsize=8,
    framealpha=0.85,
    title="Section",
    title_fontsize=9,
)

_aspect = 1.0 / np.cos(np.radians(0.5 * (_lat0 + _lat1)))
ax_sm.set_aspect(_aspect)
ax_sm.set_xlim(_lon0, _lon1)
ax_sm.set_ylim(_lat0, _lat1)
ax_sm.set_xlabel("Longitude (°E)")
ax_sm.set_ylabel("Latitude (°N)")
ax_sm.set_title(
    f"CTD cast positions by section  (clusters ≤{CLUSTER_KM:.0f} km)  —  triangles = moorings",
    fontsize=10,
)
ax_sm.grid(True, lw=0.3, alpha=0.4)

if _unassigned_casts:
    print(f"Unassigned casts — not in ctd_sections.yaml ({len(_unassigned_casts)}):")
    print("  ", sorted(_unassigned_casts))

_out_sm = _OUT_SM / "ctd_section_map.png"
fig_sm.savefig(_out_sm, dpi=150, bbox_inches="tight")
print(f"Saved → {_out_sm}")
plt.show()
