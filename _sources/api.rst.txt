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

File-level metadata
-------------------

Cruise-level metadata written into the compiled files as ACDD-1.3 global
attributes.  :mod:`~ctdcast.config.global_attrs` composes the derived coverage
bounds, provenance, embargo licence, people, and platform attributes;
:mod:`~ctdcast.config.platforms` resolves the vessel registry and derives the
EXPOCODE; :mod:`~ctdcast.config.people` turns the structured ``contributors``
list into the semicolon-delimited ACDD strings.

.. automodule:: ctdcast.config.global_attrs
   :members:
   :undoc-members:

.. automodule:: ctdcast.config.platforms
   :members:
   :undoc-members:

.. automodule:: ctdcast.config.people
   :members:
   :undoc-members:

----

Section manifest
----------------

Each report page is described by a :class:`~ctdcast.reports._manifest.Profile` of
:class:`~ctdcast.reports._manifest.Section` and
:class:`~ctdcast.reports._manifest.Panel` entries, resolved by
:func:`~ctdcast.reports._manifest.resolve` into a numbered, rendered report.  The
model is package-neutral; each page's concrete registry lives in its own generator
module.  ``_anchors`` maps the old hand-authored ``#s-*`` anchors onto the new
section ids for one release.

.. automodule:: ctdcast.reports._manifest
   :members:
   :undoc-members:

.. automodule:: ctdcast.reports._anchors
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
