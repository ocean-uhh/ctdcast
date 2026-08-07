"""Config loading utilities for ctdcast reports."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SectionsConfig:
    """Parsed contents of a ``ctd_sections.yaml`` file.

    Loaded once at the ``report()`` entry point and passed to page builders,
    replacing four independent ``yaml.safe_load`` calls scattered across the
    reports package.
    """

    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    timeseries: dict[str, dict[str, Any]] = field(default_factory=dict)
    cruise_info: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path | str) -> SectionsConfig:
        """Load a ``SectionsConfig`` from a ``ctd_sections.yaml`` file.

        Returns an empty ``SectionsConfig`` if the file does not exist.
        """
        p = Path(path)
        if not p.exists():
            return cls()
        with open(p) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return cls(
            sections=data.get("sections") or {},
            timeseries=data.get("timeseries") or {},
            cruise_info=data.get("cruise_info") or {},
        )


def load_display_config(cruise_cfg: dict[str, Any]) -> dict[str, dict]:
    """Return VARIABLES with cruise-level overrides applied.

    Package defaults come from :data:`ctdcast.config.parameters.VARIABLES`.
    Per-cruise overrides are read from ``cruise_cfg["display"]["variables"]``
    (the ``display:`` block in the cruise ``config.yaml``).  Later keys win.
    Returns a new dict; nothing global is mutated, so the result can be
    recorded in the output file's attributes for provenance.

    Example cruise config override::

        display:
          variables:
            temperature_1:
              vmin: 4
              vmax: 25
    """
    from ctdcast.config.parameters import VARIABLES

    merged: dict[str, dict] = copy.deepcopy(VARIABLES)
    overrides = (cruise_cfg.get("display") or {}).get("variables") or {}
    for name, over in overrides.items():
        merged.setdefault(name, {}).update(over)
    return merged
