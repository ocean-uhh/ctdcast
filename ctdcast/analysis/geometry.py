"""Cast geometry: along-track distance and section orientation.

Pure computation — no matplotlib, no HTML.
"""

from __future__ import annotations

import gsw
import numpy as np


def along_track_km(lats: list[float], lons: list[float]) -> tuple[np.ndarray, str]:
    """Return (cumulative_distance_km, x_axis_label) for a list of positions."""
    if len(lats) < 2:
        return np.arange(len(lats), dtype=float), "Cast index"
    try:
        dists_m = gsw.distance(np.array(lons), np.array(lats))
        x_km = np.concatenate([[0.0], np.cumsum(dists_m / 1000.0)])
        return x_km, "Along-track distance (km)"
    except Exception:  # noqa: BLE001
        return np.arange(len(lats), dtype=float), "Cast index"


def distance_from_km(
    key_lat: float, key_lon: float, lats: list[float], lons: list[float]
) -> np.ndarray:
    """Return great-circle distance in km from a key position to each position.

    Used for ``key_cast`` section ordering: each cast's x-coordinate is its
    distance from the chosen key cast.  Uses ``gsw.distance`` per pair so the
    convention matches :func:`along_track_km`.  A position identical to the key
    yields 0.
    """
    out = np.empty(len(lats), dtype=float)
    for i, (la, lo) in enumerate(zip(lats, lons)):
        try:
            out[i] = float(gsw.distance([key_lon, lo], [key_lat, la])[0]) / 1000.0
        except Exception:  # noqa: BLE001
            out[i] = np.nan
    return out


def section_orientation(lats: list[float], lons: list[float]) -> bool:
    """Return True if the section x-axis should be flipped for geographic convention.

    Convention: west on the left for E–W-dominant sections; north on the left for
    N–S-dominant sections.  Dominance is determined by comparing the end-to-end
    longitude span against the latitude span.

    Parameters
    ----------
    lats:
        Latitude of each cast in the section, in cast order.
    lons:
        Longitude of each cast in the section, in cast order.

    Returns
    -------
    bool
        True if ``x_vals`` (cumulative along-track distance from first cast)
        should be replaced by ``x_total - x_vals`` before plotting.
    """
    if len(lats) < 2:
        return False
    delta_lon = lons[-1] - lons[0]
    delta_lat = lats[-1] - lats[0]
    if abs(delta_lon) >= abs(delta_lat):  # E–W dominant
        return delta_lon < 0  # first cast is east → flip so west is left
    else:  # N–S dominant
        return delta_lat > 0  # first cast is south → flip so north is left
