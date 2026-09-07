"""ctdcast — CTD data processing and reporting for shipboard oceanography.

Subpackages
-----------
analysis:     TEOS-10, cast geometry, GEBCO bathymetry (pure computation).
processors:   per-cast and cruise-level processing pipeline (all stages).
readers:      format readers (LADCP ``.mat``, CNV shim, sensor metadata).
reports:      HTML page builders and the public ``report()`` entry point.
writers:      output writers (CF-compliant netCDF).

Public API
----------
report(nc_dir, profiles_path, groupings_yaml, out_dir, force=False)
stage1(cnv_dir, nc_dir, ...)
profiles(nc_dir, profiles_path, ...)
process(stage=None, *, cnv_dir, nc_dir, profiles_path, force=False, dry_run=False, **kw)
select_best_available(root): the stage-3-else-2-else-1 precedence for every cast under a
    CTD root — the supported entry point for out-of-package consumers (e.g. caldip) that
    need to read the best ctdcast file per cast without reimplementing the ladder.
"""

from ctdcast._version import __version__
from ctdcast.processors import process
from ctdcast.processors.profiles import build_profiles as profiles
from ctdcast.processors.stage1 import stage1
from ctdcast.processors.stage_layout import select_best_available

__all__ = [
    "__version__",
    "process",
    "profiles",
    "report",
    "select_best_available",
    "stage1",
]


def __getattr__(name: str) -> object:
    """Import the report entry point lazily (PEP 562).

    ``ctdcast.report`` pulls the report stack (jinja2, matplotlib); deferring it keeps a
    bare ``import ctdcast`` from executing that stack, so a consumer that only needs the
    processing/lineage surface — e.g. caldip importing ``select_best_available`` and
    ``config.cnv_header`` — does not pay for the report dependencies at import time.
    ``ctdcast.report`` still resolves on first access.
    """
    if name == "report":
        from ctdcast.reports._index import report

        return report
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
