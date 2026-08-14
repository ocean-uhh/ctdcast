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

Cast identity
-------------

.. automodule:: ctdcast.identity
   :members:
   :undoc-members:

----

Figure builders
---------------

``draw_*_fig`` functions build and return a matplotlib Figure (or ``None`` when the
dataset lacks the required variables).

.. automodule:: ctdcast.plotters.plots
   :members:
   :undoc-members:

Layer-1 primitives
------------------

``ax``-taking primitives that draw into a caller-supplied axes and create no Figure, so
a panel shared by more than one page type has a single implementation.

.. automodule:: ctdcast.plotters.primitives
   :members:
   :undoc-members:

Base64 encoders
---------------

``_make_*_b64`` wrappers render a figure builder's Figure to an embedded base64 PNG,
returning ``None`` on any exception so a missing figure never prevents a page from
being written.

.. automodule:: ctdcast.reports._plots
   :members:
   :undoc-members:

Plotting parameters
-------------------

.. automodule:: ctdcast.config.parameters
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

.. automodule:: ctdcast.analysis.derive
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

.. automodule:: ctdcast.processors.stage1
   :members:
   :undoc-members:

.. automodule:: ctdcast.processors.stage2
   :members:
   :undoc-members:

.. automodule:: ctdcast.processors.stage3
   :members:
   :undoc-members:

.. automodule:: ctdcast.processors.qc
   :members:
   :undoc-members:

.. automodule:: ctdcast.processors.profiles
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
