"""Read a cruise ``config.yaml`` into the settings the stages use, whichever layout it is in.

The config is split by what each block does::

    preferred_sensor:          # which sensor the plain ctd_temperature / ctd_salinity / ctd_oxygen use
      tc: primary              # the temperature/conductivity pair; bare value or {default:, ranges:}
      oxygen: primary
    clock: {...}               # the acquisition-clock correction (stage 2)
    qc: {gross_range: {...}, spike: {...}}
    fit: {...}                 # how ``ctdcast fit`` searches; nothing here is applied
    data_processing:           # what ctdcast applies to the data
      slope_offset: {...}      # per conductivity sensor: C' = slope * C + offset
      oxygen: {tau_window_seconds: 2.0}
      steps:                   # in the order they run
        - wildedit: {...}
        - alignctd: {...}
        - celltm: {...}
    processing:                # stage-2 trim and the profiles grid, unchanged
      trim: {...}
      profiles_dbar: 1

Ranges in ``preferred_sensor`` take ``value:``, as every other range does.

:func:`processing_view` turns this into the one dict the stages read.  The 0.4 layout (everything
under ``processing:``) is read for one more release, with a ``DeprecationWarning`` per key:
``processing.preferred_pair`` / ``preferred_oxygen``, ``processing.clock``, ``processing.qc`` and
``processing.calibration.conductivity_slope`` (one slope for both sensors, offset 0).  Blocks that
never shipped in a release (``processing.alignctd``, ``celltm``, ``oxygen``, ``fit``) are refused
with the place they moved to.
"""

from __future__ import annotations

import copy
import warnings
from typing import Any

#: Unreleased ``processing:`` keys and where they now live.
_MOVED_UNRELEASED = {
    "alignctd": "data_processing.steps (an `alignctd:` step)",
    "celltm": "data_processing.steps (a `celltm:` step)",
    "wildedit": "data_processing.steps (a `wildedit:` step)",
    "oxygen": "data_processing.oxygen",
    "fit": "fit (top level)",
}


def _deprecated(old: str, new: str) -> None:
    warnings.warn(
        f"config: `{old}` is deprecated and will be removed in the next release; use `{new}`.",
        DeprecationWarning,
        stacklevel=4,
    )


def _ranges_value_to_use(decl: Any, where: str) -> Any:  # noqa: ANN401  # a config value of any shape
    """Return a preferred-sensor declaration with each range's ``value:`` as the internal ``use:``."""
    if not isinstance(decl, dict):
        return decl
    out = dict(decl)
    ranges = []
    for rng in decl.get("ranges") or []:
        if isinstance(rng, dict) and "value" in rng:
            rng = {
                **{k: v for k, v in rng.items() if k != "value"},
                "use": rng["value"],
            }
        elif isinstance(rng, dict) and "use" in rng:
            _deprecated(f"{where}.ranges[].use", f"{where}.ranges[].value")
        ranges.append(rng)
    if "ranges" in decl:
        out["ranges"] = ranges
    return out


def processing_view(cfg: dict | None) -> dict:
    """Return the settings the stages read, from a config file of either layout.

    Parameters
    ----------
    cfg : dict or None
        The whole parsed ``config.yaml``.

    Returns
    -------
    dict
        ``processing:`` (``trim``, ``profiles_dbar``) plus ``preferred_pair``,
        ``preferred_oxygen``, ``clock``, ``qc``, ``fit`` and ``data_processing`` from wherever the
        file declares them.  The input is not changed.

    Raises
    ------
    ValueError
        For a ``processing:`` key that moved before it was ever released, naming its new place;
        or a key given in both layouts.
    """
    cfg = cfg or {}
    proc = copy.deepcopy(cfg.get("processing") or {})
    moved = sorted(k for k in proc if k in _MOVED_UNRELEASED)
    if moved:
        where = "; ".join(f"processing.{k} -> {_MOVED_UNRELEASED[k]}" for k in moved)
        raise ValueError(f"config: these keys have moved: {where}")
    view: dict[str, Any] = {
        k: v
        for k, v in proc.items()
        if k not in ("preferred_pair", "preferred_oxygen", "clock", "qc", "calibration")
    }

    sensor = cfg.get("preferred_sensor") or {}
    if not isinstance(sensor, dict):
        raise ValueError(f"config: preferred_sensor must be a mapping, got {sensor!r}")
    unknown = set(sensor) - {"tc", "oxygen"}
    if unknown:
        raise ValueError(
            f"config: preferred_sensor has unknown key(s) {sorted(unknown)}; expected tc, oxygen"
        )
    for new, old in (("tc", "preferred_pair"), ("oxygen", "preferred_oxygen")):
        if new in sensor and old in proc:
            raise ValueError(
                f"config: both preferred_sensor.{new} and processing.{old}; keep one"
            )
        if new in sensor:
            view[old] = _ranges_value_to_use(sensor[new], f"preferred_sensor.{new}")
        elif old in proc:
            _deprecated(f"processing.{old}", f"preferred_sensor.{new}")
            view[old] = proc[old]

    for key in ("clock", "qc"):
        if key in cfg and key in proc:
            raise ValueError(f"config: both {key} and processing.{key}; keep one")
        if key in cfg:
            view[key] = cfg[key]
        elif key in proc:
            _deprecated(f"processing.{key}", key)
            view[key] = proc[key]

    view["fit"] = copy.deepcopy(cfg.get("fit") or {})
    dp = copy.deepcopy(cfg.get("data_processing") or {})
    slope = (proc.get("calibration") or {}).get("conductivity_slope")
    if slope is not None:
        if dp.get("slope_offset"):
            raise ValueError(
                "config: both data_processing.slope_offset and "
                "processing.calibration.conductivity_slope; keep one"
            )
        _deprecated(
            "processing.calibration.conductivity_slope",
            "data_processing.slope_offset (per sensor: {slope:, offset:})",
        )
        both = {"slope": slope, "offset": 0.0}
        dp["slope_offset"] = {"conductivity_1": both, "conductivity_2": dict(both)}
    view["data_processing"] = dp
    return view
