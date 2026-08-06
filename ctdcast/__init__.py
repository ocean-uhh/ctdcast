"""ctdcast — CTD data processing and reporting for shipboard oceanography.

Subpackages
-----------
analysis:   TEOS-10, cast geometry, GEBCO bathymetry (pure computation).
cast:       per-cast processing (``stage2`` trim; ``stage1``/``stage3`` later).
readers:    format readers (LADCP ``.mat``, sensor metadata).
reports:    HTML page builders and the public ``report()`` entry point.

``plots.py`` (figure builders) sits at the package root until PR 1b splits it
into ``plotters/`` and ``reports/_plots.py``.

Public API
----------
report(nc_dir, profiles_path, section_yaml, out_dir, force=False)
"""

from ctdcast._version import __version__
from ctdcast.reports._index import report

__all__ = ["__version__", "report"]
