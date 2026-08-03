"""Tests for analysis helpers: _section_orientation."""

from ctdreport.analysis import _section_orientation


class TestSectionOrientation:
    def test_ew_west_to_east_no_flip(self):
        # First cast west, last cast east → west already on left → no flip
        lats = [60.0, 60.0, 60.0]
        lons = [-30.0, -25.0, -20.0]
        assert _section_orientation(lats, lons) is False

    def test_ew_east_to_west_flip(self):
        # First cast east, last cast west → needs flip so west is left
        lats = [60.0, 60.0, 60.0]
        lons = [-20.0, -25.0, -30.0]
        assert _section_orientation(lats, lons) is True

    def test_ns_north_to_south_no_flip(self):
        # First cast north, last cast south → north already on left → no flip
        lats = [65.0, 63.0, 61.0]
        lons = [-25.0, -25.0, -25.0]
        assert _section_orientation(lats, lons) is False

    def test_ns_south_to_north_flip(self):
        # First cast south, last cast north → needs flip so north is left
        lats = [61.0, 63.0, 65.0]
        lons = [-25.0, -25.0, -25.0]
        assert _section_orientation(lats, lons) is True

    def test_single_point_no_flip(self):
        assert _section_orientation([60.0], [-25.0]) is False

    def test_ew_dominant_over_ns(self):
        # Large lon span, small lat span → E-W dominant
        lats = [60.0, 60.5]
        lons = [-30.0, -20.0]  # 10° lon vs 0.5° lat → E-W
        assert _section_orientation(lats, lons) is False  # west-to-east, no flip

    def test_ns_dominant_over_ew(self):
        # Large lat span, small lon span → N-S dominant
        lats = [65.0, 60.0]
        lons = [-25.0, -25.2]  # 5° lat vs 0.2° lon → N-S
        assert _section_orientation(lats, lons) is False  # north-to-south, no flip
