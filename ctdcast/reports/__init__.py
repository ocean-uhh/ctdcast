"""HTML report generation — page builders and the public ``report()`` entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ctdcast.reports._index import report

__all__ = ["report"]


def __getattr__(name: str) -> object:
    """Resolve ``report`` lazily, without importing the pipeline at package import.

    Importing ``ctdcast.reports`` — or any submodule, such as the vendored layer or
    the ``design`` hook — must not pull ``_index`` and the whole report pipeline,
    which imports back into :mod:`ctdcast.config.report_config` and forms a cycle.
    ``report`` is imported on first attribute access instead.
    """
    if name == "report":
        from ctdcast.reports._index import report as _report

        return _report
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
