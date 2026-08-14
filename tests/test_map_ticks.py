"""Unit tests for the cruise-map degree-tick chooser (``_deg_tick_step``)."""

from __future__ import annotations

import math

import pytest

from ctdcast.plotters.plots import _deg_tick_step

_NICE = {0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0}


def _ticks_in_range(lo: float, hi: float, step: float) -> int:
    """Count tick multiples of *step* that fall within ``[lo, hi]``."""
    return math.floor(hi / step + 1e-9) - math.ceil(lo / step - 1e-9) + 1


def test_regression_coarse_step_one_tick_rejected() -> None:
    """The case that regressed: a 0.5° step on a ~0.48° span lands one tick — rejected."""
    step = _deg_tick_step(-45.44, -44.96, max_ticks=2)
    assert _ticks_in_range(-45.44, -44.96, step) >= 2


@pytest.mark.parametrize(
    ("lo", "hi"),
    [(-45.44, -44.96), (65.35, 65.55), (60.0, 67.0), (-30.0, -22.0)],
)
def test_at_least_two_ticks_even_when_max_is_two(lo: float, hi: float) -> None:
    """For a real map span (>= the enforced 0.2° minimum) there are always >= 2 ticks."""
    step = _deg_tick_step(lo, hi, max_ticks=2)
    assert _ticks_in_range(lo, hi, step) >= 2


def test_width_cap_thins_ticks_on_a_narrow_map() -> None:
    """A wider allowance yields at least as many ticks as a narrow one over one span."""
    span = (60.0, 67.0)
    wide = _ticks_in_range(*span, _deg_tick_step(*span, max_ticks=8))
    narrow = _ticks_in_range(*span, _deg_tick_step(*span, max_ticks=3))
    assert wide >= narrow >= 2


@pytest.mark.parametrize(
    ("lo", "hi", "mx"),
    [(65.4, 65.5, 6), (65.40, 65.42, 6), (-45.5, -45.0, 4), (60.0, 67.0, 6)],
)
def test_step_never_finer_than_a_tenth(lo: float, hi: float, mx: int) -> None:
    """Steps are always >= 0.1° so tick labels need at most one decimal place."""
    assert _deg_tick_step(lo, hi, mx) >= 0.1


@pytest.mark.parametrize(
    ("lo", "hi", "mx"),
    [(60.0, 67.0, 6), (-45.44, -44.96, 2), (65.35, 65.55, 4)],
)
def test_returns_a_nice_multiple(lo: float, hi: float, mx: int) -> None:
    """Only 'nice' degree steps are returned."""
    assert _deg_tick_step(lo, hi, mx) in _NICE
