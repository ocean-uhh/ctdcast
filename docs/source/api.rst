.. _api:

============
Python API
============

The primary public entry point is :func:`ctdreport.index.generate_ctd_report`.

----

Main entry point
----------------

.. autofunction:: ctdreport.index.generate_ctdreport

----

Converters (Tier 0)
-------------------

.. automodule:: ctdreport.converters
   :members:
   :undoc-members:

----

Plot helpers (Tier 1)
---------------------

These functions return base64-encoded PNG strings.  They are called by the page
generators and return ``None`` on any exception, so a missing figure never prevents
a page from being written.

.. automodule:: ctdreport.plots
   :members:
   :undoc-members:

----

Page generators (Tier 2)
------------------------

.. automodule:: ctdreport.station
   :members:
   :undoc-members:

.. automodule:: ctdreport.section
   :members:
   :undoc-members:

.. automodule:: ctdreport.timeseries
   :members:
   :undoc-members:

----

Interactive map (Tier 2)
------------------------

.. automodule:: ctdreport.map_leaflet
   :members:
   :undoc-members:

----

Analysis helpers
----------------

.. automodule:: ctdreport.analysis
   :members:
   :undoc-members:
