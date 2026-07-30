.. _api:

============
Python API
============

The primary public entry point is :func:`ctd_report.generate_ctd_report`.  All other
functions are internal.

.. note::

   The module will be renamed from ``ctd_report`` to ``oceancast`` in a future release
   once the package rename is complete.  The public API will remain the same.

----

Main entry point
----------------

.. autofunction:: ctd_report._index.generate_ctd_report

----

Plot helpers (Tier 1)
---------------------

These functions return base64-encoded PNG strings.  They are called by the page
generators and return ``None`` on any exception, so a missing figure never prevents
a page from being written.

.. automodule:: ctd_report._plots
   :members:
   :undoc-members:

----

Page generators (Tier 2)
------------------------

.. automodule:: ctd_report._station
   :members:
   :undoc-members:

.. automodule:: ctd_report._section
   :members:
   :undoc-members:

.. automodule:: ctd_report._timeseries
   :members:
   :undoc-members:
