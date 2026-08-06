.. _api:

============
Python API
============

The primary public entry point is :func:`ctdcast.report`.

----

Main entry point
----------------

.. autofunction:: ctdcast.reports._index.report

----

Data preparation
----------------

.. automodule:: ctdcast.converters
   :members:
   :undoc-members:

----

Plot helpers
------------

These functions return base64-encoded PNG strings.  They are called by the page
generators and return ``None`` on any exception, so a missing figure never prevents
a page from being written.

.. automodule:: ctdcast.plots
   :members:
   :undoc-members:

----

Page generators
---------------

.. automodule:: ctdcast.reports._cast
   :members:
   :undoc-members:

.. automodule:: ctdcast.reports._section
   :members:
   :undoc-members:

.. automodule:: ctdcast.reports._timeseries
   :members:
   :undoc-members:

----

Interactive map
---------------

.. automodule:: ctdcast.reports._leaflet
   :members:
   :undoc-members:

----

Analysis helpers
----------------

.. automodule:: ctdcast.analysis.teos10
   :members:
   :undoc-members:

.. automodule:: ctdcast.analysis.geometry
   :members:
   :undoc-members:

.. automodule:: ctdcast.analysis.bathymetry
   :members:
   :undoc-members:

----

Cast processing
---------------

.. automodule:: ctdcast.cast.stage2
   :members:
   :undoc-members:

----

Readers
-------

.. automodule:: ctdcast.readers.ladcp
   :members:
   :undoc-members:

.. automodule:: ctdcast.readers.metadata
   :members:
   :undoc-members:
