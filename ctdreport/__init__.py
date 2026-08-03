"""CTD HTML report system — three-tier architecture.

Tier-1 (plots.py):    base64 PNG helpers, one function per figure type.
Tier-2 (station, section, timeseries): per-page orchestrators.
Tier-3 (index.py):    entry point, generates index / stations / sections pages.

Public API
----------
generate_ctd_report(nc_dir, profiles_path, section_yaml, out_dir, force=False)
"""

from ctdreport._version import __version__
from ctdreport.index import generate_ctd_report

__all__ = ["__version__", "generate_ctd_report"]
