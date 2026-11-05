"""Figure for the cruise processing page: a setting that changes cast to cast."""

from __future__ import annotations

from collections.abc import Sequence

import matplotlib.pyplot as plt
import numpy as np

from ctdcast.reports._vendored.design_tokens import W_HALF as _W_HALF

#: Height over width of the figure; the width comes from the page slot.
_ASPECT = 0.45


def draw_setting_by_cast_fig(
    casts: Sequence[int],
    values: Sequence[float],
    label: str,
    *,
    width_in: float = _W_HALF,
) -> plt.Figure | None:
    """Return the value a step used on each cast, against cast number.

    Parameters
    ----------
    casts : sequence of int
        Cast numbers.
    values : sequence of float
        The step's value on each cast (NaN where the step did not run).
    label : str
        The y-axis label: the step and the quantity.
    width_in : float, default ``W_HALF``
        Figure width in inches; the height follows at a fixed aspect.

    Returns
    -------
    matplotlib.figure.Figure or None
        None when no cast has a value.
    """
    x = np.asarray(casts, dtype=float)
    y = np.asarray(values, dtype=float)
    if not (np.isfinite(x) & np.isfinite(y)).any():
        return None
    fig, ax = plt.subplots(figsize=(width_in, width_in * _ASPECT))
    # NaN breaks the line, so casts the step did not run on leave a gap rather than a bridge.
    ax.plot(x, y, marker="o", linestyle="-", markersize=3)
    ax.set_xlabel("Cast")
    ax.set_ylabel(label)
    return fig
