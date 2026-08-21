"""Sensor-provenance registry and per-cruise override resolution.

Records each CTD sensor's identity — model, maker, serial, calibration date,
controlled-vocabulary URIs — so a cruise's sensor configuration is
reconstructable from the output alone.  Attribute *names* follow the
OceanGliders OG1 conventions where they apply (``sensor_model``,
``sensor_maker``, the L05/L22/L35 vocabularies, the ``SENSOR_*`` variable form)
for interoperability, but this is shipboard CTD data, not a glider mission: the
per-profile sensor linkage ctdcast adds has no OG1 equivalent, and nothing here
claims OG1 conformance.

Two layers feed a sensor's attributes:

1. The **universal** ``sbe_sensors.yaml`` shipped in this package, keyed on the
   numeric SeaBird ``SensorID`` from the CNV header (:class:`SensorRegistry`).
2. The operator's **cruise** ``config.yaml`` ``sensors:`` block, keyed on role,
   supplying what the header cannot — sensors the header can't identify
   (altimeter, user-polynomial channels) and model refinements
   (:class:`SensorOverrides`).

:func:`resolve_sensor` merges them in the fixed order *SensorID default -> role
override -> serial alias* and never invents a model: an unresolved sensor is
recorded as ``UNK`` with an actionable warning, or (``strict=True``) raises.
"""

from __future__ import annotations

import copy
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Sensor attribute fields a resolved sensor carries, in write order (names
#: follow OG1 conventions for interoperability).
SENSOR_ATTR_FIELDS: tuple[str, ...] = (
    "long_name",
    "sensor_type",
    "sensor_type_vocabulary",
    "sensor_model",
    "sensor_model_vocabulary",
    "sensor_maker",
    "sensor_maker_vocabulary",
)

#: Attributes filled for a SensorID the registry does not know at all.
_UNKNOWN_DEFAULT: dict[str, str] = {
    "long_name": "unknown sensor",
    "sensor_type": "",
    "sensor_type_vocabulary": "",
    "sensor_model": "UNK",
    "sensor_model_vocabulary": "",
    "sensor_maker": "UNK",
    "sensor_maker_vocabulary": "",
    "model_source": "UNK",
    "element": "",
}


@dataclass(frozen=True)
class SensorRegistry:
    """Universal SensorID -> sensor attribute table, from the package YAML."""

    by_sensor_id: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str | None = None) -> SensorRegistry:
        """Load the registry from ``sbe_sensors.yaml`` (package default if None)."""
        p = (
            Path(path)
            if path is not None
            else Path(__file__).with_name("sbe_sensors.yaml")
        )
        with open(p) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        raw = data.get("sensors") or {}
        # SensorID keys are strings ("55"); coerce any int that slipped through.
        table = {str(k): dict(v) for k, v in raw.items()}
        return cls(by_sensor_id=table)

    def default_for(self, sensor_id: str) -> dict[str, str] | None:
        """Return a copy of the registry entry for ``sensor_id``, or None."""
        entry = self.by_sensor_id.get(str(sensor_id))
        return copy.deepcopy(entry) if entry is not None else None


@dataclass(frozen=True)
class SensorOverrides:
    """Cruise-level, role-keyed sensor overrides and serial aliases.

    ``overrides`` is keyed by role (``"altimeter"``) or, to disambiguate two
    different-model devices in one role, ``"role:serial"`` (``"altimeter:42299"``).
    ``aliases`` maps a serial spelling to its canonical form so one physical
    device recorded two ways yields one catalog entry.
    """

    overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_cruise_config(cls, cruise_cfg: dict[str, Any] | None) -> SensorOverrides:
        """Build from a cruise ``config.yaml`` mapping (its ``sensors:`` block)."""
        block = (cruise_cfg or {}).get("sensors") or {}
        overrides = {str(k): dict(v) for k, v in (block.get("overrides") or {}).items()}
        aliases = {str(k): str(v) for k, v in (block.get("aliases") or {}).items()}
        return cls(overrides=overrides, aliases=aliases)

    def canonical_serial(self, serial: str) -> str:
        """Return the canonical spelling of ``serial`` after alias resolution."""
        return self.aliases.get(serial, serial)

    def for_role(self, role: str, serial: str) -> dict[str, str]:
        """Return the override for ``role``, most specific first, or ``{}``.

        Tries ``role:serial`` (raw then canonical), then bare ``role``.
        """
        canon = self.canonical_serial(serial)
        for key in (f"{role}:{serial}", f"{role}:{canon}", role):
            if key in self.overrides:
                return dict(self.overrides[key])
        return {}


def sanitize_serial(serial: str) -> str:
    """Apply OG1's rule — non-alphanumerics become underscores — to ``serial``."""
    return re.sub(r"[^0-9A-Za-z]", "_", serial)


def catalog_var_name(role: str, serial: str) -> str:
    """Return the sensor-catalog variable name ``SENSOR_<TYPE>_<INDEX>_<SERIAL>``.

    ``role`` is a canonical ctdcast role (``temperature_1``, ``fluorometer``);
    a trailing ``_N`` is the role index, defaulting to ``1`` when absent.
    """
    m = re.match(r"(?P<base>.+?)(?:_(?P<idx>\d+))?$", role)
    base = (m.group("base") if m else role).upper()
    idx = (m.group("idx") if m else None) or "1"
    return f"SENSOR_{base}_{idx}_{sanitize_serial(serial)}"


def _is_unresolved(attrs: dict[str, str]) -> bool:
    """Return True if the model was not determined (UNK or empty)."""
    return attrs.get("model_source") == "UNK" or attrs.get("sensor_model", "") in (
        "",
        "UNK",
    )


def resolve_sensor(
    *,
    sensor_id: str,
    serial: str,
    role: str,
    calibration_date: str = "",
    element: str = "",
    cast: int | str | None = None,
    registry: SensorRegistry,
    overrides: SensorOverrides | None = None,
    strict: bool = False,
) -> dict[str, str]:
    """Resolve one sensor's attributes: SensorID default -> override -> alias.

    ``sensor_id`` is the numeric SeaBird SensorID (as a string); ``serial`` the
    verbatim serial number (a string — leading zeros are significant); ``role``
    a canonical ctdcast role; ``element`` the CNV element name for cross-checking
    against the registry; ``cast`` an optional label used only in warnings.

    Returns a dict of sensor attributes plus provenance (``sensor_serial_number``,
    ``sensor_calibration_date``, ``sbe_sensor_id``, ``sbe_sensor_element``,
    ``model_source``).  Never invents a model: an unresolved sensor is returned
    with ``sensor_model="UNK"`` and a loud, actionable warning; with
    ``strict=True`` it raises :class:`ValueError` instead.

    :raises TypeError: if ``serial`` is not a ``str`` (guards YAML octal coercion
        of leading-zero serials).
    :raises ValueError: if ``strict`` and the model cannot be resolved.
    """
    if not isinstance(serial, str):
        raise TypeError(
            f"serial must be a str (got {type(serial).__name__} {serial!r}); "
            "leading zeros are significant and must never pass through int()."
        )

    base = registry.default_for(sensor_id)
    unknown_id = base is None
    if unknown_id:
        base = copy.deepcopy(_UNKNOWN_DEFAULT)

    reg_element = base.get("element", "")
    if element and reg_element and element != reg_element:
        warnings.warn(
            f"CNV element {element!r} disagrees with registry element {reg_element!r} "
            f"for SensorID {sensor_id!r} (role {role!r}, serial {serial!r}"
            f"{_cast_suffix(cast)}); using the registry entry.",
            stacklevel=2,
        )

    # A cruise role override merges over the default (or the UNK stub), so it can
    # fill any gap — including a SensorID the package table does not know.
    if overrides is not None:
        base.update(overrides.for_role(role, serial))

    # Warn only if still unresolved AFTER the override, so a filled gap is silent.
    if _is_unresolved(base):
        reason = (
            f"Unknown SeaBird SensorID {sensor_id!r}"
            if unknown_id
            else f"SensorID {sensor_id!r} carries no model default"
        )
        fix = f"Add sensors.overrides.{role} to the cruise config.yaml"
        if unknown_id:
            fix += " (or a row to ctdcast/config/sbe_sensors.yaml if universal)"
        msg = (
            f"{reason}: model not resolved for role {role!r} "
            f"(serial {serial!r}{_cast_suffix(cast)}).  {fix}."
        )
        if strict:
            raise ValueError(msg)
        warnings.warn(msg, stacklevel=2)
        base.setdefault("model_source", "UNK")

    result: dict[str, str] = {k: base.get(k, "") for k in SENSOR_ATTR_FIELDS}
    result["model_source"] = base.get("model_source", "UNK")
    result["sensor_serial_number"] = serial
    result["sensor_calibration_date"] = calibration_date
    result["sbe_sensor_id"] = str(sensor_id)
    result["sbe_sensor_element"] = reg_element or element
    return result


def _cast_suffix(cast: int | str | None) -> str:
    """Return a ``", cast NNN"`` fragment for warnings, or empty if no cast."""
    if cast is None:
        return ""
    return f", cast {cast}"
