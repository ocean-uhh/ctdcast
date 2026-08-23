"""Shared scientific analysis: TEOS-10 derived variables, cast geometry, GEBCO bathymetry, clocks."""

from ctdcast.analysis.clock import (
    CastClock,
    ClockSegment,
    ClockVerdict,
    cast_number,
    classify_offsets,
    clock_offsets,
    coordinate_summary,
    correction_status,
    suggested_config_yaml,
)
from ctdcast.analysis.derive import (
    derive_AOU,
    derive_CT,
    derive_SA,
    derive_salinity,
    derive_sigma0,
    derive_teos10,
    derive_teos10_profiles,
)

__all__ = [
    "CastClock",
    "ClockSegment",
    "ClockVerdict",
    "cast_number",
    "classify_offsets",
    "clock_offsets",
    "coordinate_summary",
    "correction_status",
    "suggested_config_yaml",
    "derive_AOU",
    "derive_CT",
    "derive_SA",
    "derive_salinity",
    "derive_sigma0",
    "derive_teos10",
    "derive_teos10_profiles",
]
