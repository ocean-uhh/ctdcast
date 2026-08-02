.. _api:

============
Python API
============

The primary public entry point is :func:`ctd_report.generate_ctd_report`.

.. note::

   The module will be renamed from ``ctd_report`` to ``oceancast`` in a future release
   once the package rename is complete.  The public API will remain the same.

----

Main entry point
----------------

.. autofunction:: ctd_report.index.generate_ctd_report

----

Converters (Tier 0)
-------------------

.. automodule:: ctd_report.converters
   :members:
   :undoc-members:

----

Plot helpers (Tier 1)
---------------------

These functions return base64-encoded PNG strings.  They are called by the page
generators and return ``None`` on any exception, so a missing figure never prevents
a page from being written.

.. automodule:: ctd_report.plots
   :members:
   :undoc-members:

----

Page generators (Tier 2)
------------------------

.. automodule:: ctd_report.station
   :members:
   :undoc-members:

.. automodule:: ctd_report.section
   :members:
   :undoc-members:

.. automodule:: ctd_report.timeseries
   :members:
   :undoc-members:

----

Interactive map (Tier 2)
------------------------

.. automodule:: ctd_report.map_leaflet
   :members:
   :undoc-members:

----

Analysis helpers
----------------

.. automodule:: ctd_report.analysis
   :members:
   :undoc-members:
