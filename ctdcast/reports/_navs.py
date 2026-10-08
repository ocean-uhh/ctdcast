"""Builder for the masthead page-nav mapping — ctdcast's page set.

The nav is a plain mapping rendered by the vendored ``templates/_nav.html`` macros
and validated by :func:`ctdcast.reports._manifest.validate_nav`.  This module is
the one place that knows ctdcast's pages and their roles; the *shape* it builds is
the shared cross-package contract, so each sibling package carries its own
``_navs.py`` building the same shape for its own pages.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ctdcast.reports._manifest import validate_nav

#: The masthead row, in rendered order: (current-key, label, bare href, role).
#: ``current-key`` is what a page passes as ``current`` to light its pill.
_PAGES: tuple[tuple[str, str, str, str], ...] = (
    ("summary", "Summary", "index.html", "landing"),
    ("casts", "Casts", "casts.html", "collection"),
    ("sections", "Sections", "sections.html", "aggregate-a"),
    ("timeseries", "Timeseries", "timeseries.html", "aggregate-b"),
    ("interactive", "Interactive", "leaflet.html", "map"),
)


def inventory_sources(
    profiles_path: Path | str | None, ladcp_profiles_path: Path | str | None
) -> tuple[list[Path], bool]:
    """Return ``(dataset_srcs, has_sensors)`` — the compiled products present on disk.

    The single definition of "which compiled products exist": the dataset netCDFs
    that exist, and whether a sensor catalog is available (it lives in
    ``profiles.nc``).  Both the inventory strip (:func:`inventory_pills`) and the
    caller's page-generation loop read this, so the two cannot disagree about which
    products are present.

    Parameters
    ----------
    profiles_path : pathlib.Path or str or None
        The compiled ``profiles.nc`` path, or None.
    ladcp_profiles_path : pathlib.Path or str or None
        The compiled ``ladcp_profiles.nc`` path, or None.

    Returns
    -------
    tuple of (list of pathlib.Path, bool)
        The existing dataset paths, and whether the SBE sensors page applies.
    """
    srcs = [
        Path(s)
        for s in (profiles_path, ladcp_profiles_path)
        if s is not None and Path(s).exists()
    ]
    has_sensors = profiles_path is not None and Path(profiles_path).exists()
    return srcs, has_sensors


def inventory_pills(
    profiles_path: Path | str | None, ladcp_profiles_path: Path | str | None
) -> list[dict[str, str]]:
    """Return the "Data inventory:" strip pills for the compiled products present.

    One pill per compiled dataset that exists (``profiles.nc``,
    ``ladcp_profiles.nc``), plus an ``SBE sensors`` pill when ``profiles.nc`` is
    present.  Built from :func:`inventory_sources` so the strip and the caller's
    generation loop share one existence rule.  Hrefs are bare (no path prefix);
    :func:`nav_for` applies the per-page prefix.

    Parameters
    ----------
    profiles_path : pathlib.Path or str or None
        The compiled ``profiles.nc`` path, or None.
    ladcp_profiles_path : pathlib.Path or str or None
        The compiled ``ladcp_profiles.nc`` path, or None.

    Returns
    -------
    list of dict
        ``{"label", "href"}`` entries, one per inventory page.
    """
    srcs, has_sensors = inventory_sources(profiles_path, ladcp_profiles_path)
    pills = [{"label": p.name, "href": f"{p.stem}_inventory.html"} for p in srcs]
    if has_sensors:
        pills.append({"label": "SBE sensors", "href": "sbe_sensors.html"})
    return pills


def nav_for(
    current: str | None,
    *,
    prefix: str = "",
    inventory: Sequence[Mapping[str, str]] = (),
    inventory_current: str | None = None,
) -> dict:
    """Build the masthead nav mapping for one page.

    Exactly one pill is marked ``current``: a main page lights its row pill
    (``current`` is a :data:`_PAGES` key), a file page lights its strip pill
    (``current`` is None and ``inventory_current`` names the strip href).

    Parameters
    ----------
    current : str or None
        The active row pill's key (a :data:`_PAGES` key), or None for a page whose
        current pill is in the inventory strip (the dataset / sensors pages).
    prefix : str, default ""
        Prepended to every href — ``""`` for top-level pages, ``"../"`` for the
        per-cast / per-section / per-timeseries detail pages.
    inventory : sequence of mapping, default ()
        The strip pills from :func:`inventory_pills` (``{"label", "href"}``).
    inventory_current : str or None, default None
        The bare href of the strip pill for the page being viewed, if any.

    Returns
    -------
    dict
        The nav mapping, already passed through :func:`validate_nav`.
    """
    rows = [
        {
            "label": "Pages:",
            "pills": [
                {
                    "label": label,
                    "href": prefix + href,
                    "role": role,
                    "state": "current" if key == current else "link",
                }
                for key, label, href, role in _PAGES
            ],
        }
    ]
    strip = [
        {
            "label": p["label"],
            "href": prefix + p["href"],
            "role": "component",
            "state": "current" if p["href"] == inventory_current else "link",
        }
        for p in inventory
    ]
    nav = {"rows": rows, "back": None, "inventory": strip}
    validate_nav(nav)
    return nav
