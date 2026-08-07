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
report(nc_dir, profiles_path, section_yaml, out_dir, force=False)
stage1(cnv_dir, nc_dir, ...)
profiles(nc_dir, profiles_path, ...)
process(stage=None, *, proc_dir, force=False, **kw)
"""

from ctdcast._version import __version__
from ctdcast.processors import process
from ctdcast.processors.profiles import build_profiles as profiles
from ctdcast.processors.stage1 import stage1
from ctdcast.reports._index import report

__all__ = ["__version__", "process", "profiles", "report", "stage1"]
