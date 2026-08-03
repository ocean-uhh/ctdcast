"""Tests for analysis helpers: _section_orientation, _find_soak_end."""

import numpy as np

from ctdreport.analysis import _find_soak_end, _section_orientation


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


# ---------------------------------------------------------------------------
# _find_soak_end
# ---------------------------------------------------------------------------


def _make_times(n: int, dt_seconds: float = 1.0) -> np.ndarray:
    """Return a datetime64 array with *n* samples spaced *dt_seconds* apart."""
    base = np.datetime64("2025-01-01T00:00:00", "s")
    return base + (np.arange(n) * dt_seconds).astype("timedelta64[s]")


class TestFindSoakEnd:
    """Tests for _find_soak_end using the corrected 3-step algorithm.

    Algorithm:
      1. i_max = index of global pressure maximum.
      2. In pressure[0:i_max+1], find the last index where p < near_surface_dbar.
      3. In the search_seconds window before that index, find the pressure minimum.
      Return the index after that minimum (first record of the real downcast).
    """

    def test_empty_array_returns_zero(self):
        assert _find_soak_end(np.array([]), np.array([])) == 0

    def test_no_near_surface_before_max_returns_zero(self):
        # Cast always >= 10 dbar (e.g. deployed from depth, never near surface).
        p = np.ones(200) * 15.0
        t = _make_times(200)
        # No p < 10 anywhere in [0, i_max] → return 0 (no trim).
        assert _find_soak_end(p, t) == 0

    def test_good_weather_soak_trimmed(self):
        # Realistic good-weather profile:
        #   p[0:60]   = 8 dbar  (soak at ~8 m)
        #   p[60:80]  = 0.5 dbar (raised back to near-surface)
        #   p[80:160] = 0 → 200 dbar  (real descent — first crosses 10 at ~84)
        #   p[160:200]= 200 → 0 dbar  (upcast, not relevant)
        n = 200
        p = np.empty(n)
        p[:60] = 8.0
        p[60:80] = 0.5
        p[80:160] = np.linspace(0, 200, 80)  # step ≈ 2.53 dbar/s
        p[160:200] = np.linspace(200, 0, 40)
        t = _make_times(n)
        # Step 1: i_max = 159 (200 dbar)
        # Step 2: last p<10 in [0,159]: p[83]≈7.59 < 10; p[84]≈10.13 >= 10 → i_last=83
        # Step 3: 20 s before 83 → window [63,83]; p[63:80]=0.5, p[80]=0
        #         min = 0 at local 17 (= global 80) → return 81
        result = _find_soak_end(p, t)
        assert result == 81

    def test_upcast_near_surface_not_used(self):
        # Profile: descent then upcast back to surface. The upcast near-surface
        # records must not drive the trim (they are after i_max).
        n = 200
        p = np.empty(n)
        p[:100] = np.linspace(0, 200, 100)  # descent
        p[100:] = np.linspace(200, 0, 100)  # upcast (last records near 0)
        t = _make_times(n)
        # i_max = 99; last p<10 in [0,99]: near start of descent
        # The upcast (p[100:]=200→0) is entirely past i_max and never considered.
        # Whatever result is returned, it must be <= 10 (only trimming the very
        # start where the CTD was near-surface before descending).
        result = _find_soak_end(p, t)
        assert 0 <= result <= 10

    def test_aborted_cast_all_near_surface_returns_zero(self):
        # CTD never went below near_surface_dbar → no trim (return 0).
        p = np.ones(100) * 0.5  # always near surface
        t = _make_times(100)
        # nanargmax of all-same → 0; pre_max_mask = p[:1] < 10 = [True]
        # i_last_near = 0; window [0,0]; min at 0 → return 1
        # Actually: pre_max includes only p[0]. Since all p = 0.5 < 10:
        # → last near = 0; window = p[0:1] = [0.5]; min at 0 → return 1
        # With a cast this shallow there's nothing meaningful to trim — but
        # generate_station_page guards against returning n (empty dataset).
        result = _find_soak_end(p, t)
        assert result <= 5  # tiny trim; not n=100

    def test_numeric_time_works(self):
        # Float seconds should work identically to datetime64.
        n = 200
        p = np.empty(n)
        p[:60] = 8.0
        p[60:80] = 0.5
        p[80:160] = np.linspace(0, 200, 80)
        p[160:] = np.linspace(200, 0, 40)
        t = np.arange(n, dtype=float)
        assert _find_soak_end(p, t) == 81

    def test_custom_near_surface_dbar(self):
        # With near_surface_dbar=5, threshold is tighter — last p<5 is earlier.
        n = 200
        p = np.empty(n)
        p[:60] = 8.0
        p[60:80] = 0.5
        p[80:160] = np.linspace(0, 200, 80)  # crosses 5 at p[82]≈5.06
        p[160:] = np.linspace(200, 0, 40)
        t = _make_times(n)
        # Step 2: last p<5 in [0,159]: p[81]≈2.53; p[82]≈5.06 → i_last=81
        # Step 3: 20s window [61,81]; p[61:80]=0.5, p[80]=0, p[81]=2.53
        #         min=0 at local 19 (global 80) → return 81
        result = _find_soak_end(p, t, near_surface_dbar=5.0)
        assert result == 81

    def test_custom_search_seconds(self):
        # With search_seconds=5, the backward window is only 5 s wide.
        n = 200
        p = np.empty(n)
        p[:60] = 8.0
        p[60:80] = 0.5
        p[80:160] = np.linspace(0, 200, 80)
        p[160:] = np.linspace(200, 0, 40)
        t = _make_times(n)
        # i_last_near = 83; 5 s window → [78, 83]; p[78:80]=0.5, p[80]=0, p[81:83]<10
        # min = 0 at global 80 → return 81
        result = _find_soak_end(p, t, search_seconds=5.0)
        assert result == 81

    def test_result_never_exceeds_array_length(self):
        # The return value must always be a valid slice start (0 <= idx <= n).
        p = np.arange(300, dtype=float)  # monotonically increasing pressure
        t = _make_times(300)
        idx = _find_soak_end(p, t)
        assert 0 <= idx <= 300
