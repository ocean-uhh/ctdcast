"""Backward-compatibility shim — use :mod:`ctdcast.analysis.derive` instead.

All functions have moved to ``derive.py`` with clearer names following GSW
conventions.  This module re-exports them under their original names so
existing callers (plotters, reports) continue to work without changes.
"""

from __future__ import annotations

from ctdcast.analysis.derive import (  # noqa: F401
    _convert_oxygen_to_pct_sat,
)
from ctdcast.analysis.derive import (
    derive_AOU as add_aou,
)
from ctdcast.analysis.derive import (
    derive_teos10 as add_teos10,
)
from ctdcast.analysis.derive import (
    derive_teos10_profiles as add_teos10_profiles,
)

__all__ = ["add_aou", "add_teos10", "add_teos10_profiles"]
