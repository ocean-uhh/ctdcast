"""HTML report generation — page builders and the public ``report()`` entry point."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ctdcast.reports.cast import generate_station_page
    from ctdcast.reports.cruise_map import generate_leaflet_map
    from ctdcast.reports.dataset import generate_dataset_page, read_dataset_meta
    from ctdcast.reports.index import report
    from ctdcast.reports.section import generate_section_page
    from ctdcast.reports.timeseries import generate_timeseries_page

__all__ = [
    "generate_dataset_page",
    "generate_leaflet_map",
    "generate_section_page",
    "generate_station_page",
    "generate_timeseries_page",
    "read_dataset_meta",
    "report",
]

#: Public name -> the submodule that defines it.  Resolved lazily (see
#: :func:`__getattr__`) so importing this package — or any submodule, such as the
#: vendored layer or the ``design`` hook — does not import the page pipeline,
#: which imports back into :mod:`ctdcast.config.report_config` and forms a cycle.
_EXPORTS = {
    "report": "index",
    "generate_station_page": "cast",
    "generate_section_page": "section",
    "generate_timeseries_page": "timeseries",
    "generate_dataset_page": "dataset",
    "read_dataset_meta": "dataset",
    "generate_leaflet_map": "cruise_map",
}


def __getattr__(name: str) -> object:
    """Resolve a public report name lazily, importing its module on first access."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    obj = getattr(importlib.import_module(f"ctdcast.reports.{module}"), name)
    globals()[name] = (
        obj  # bind so later accesses are a normal attribute hit, not a re-import
    )
    return obj
