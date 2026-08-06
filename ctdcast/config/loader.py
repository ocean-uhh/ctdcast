"""Config loading utilities for ctdcast reports."""

from __future__ import annotations

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

    @classmethod
    def empty(cls) -> SectionsConfig:
        """Return an all-empty ``SectionsConfig`` (no YAML loaded)."""
        return cls()
