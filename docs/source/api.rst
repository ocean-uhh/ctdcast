.. _api:

============
Python API
============

The primary public entry point is :func:`ctdcast.report`.

----

Main entry point
----------------

.. autofunction:: ctdcast.reports.index.report

----

Best-available file selection
-----------------------------

The supported entry point for consumers outside ctdcast (e.g. ``caldip``) to read the
best available ctdcast file per cast — stage 3 if present, else stage 2, else stage 1 —
without reimplementing the precedence ladder. Import it as ``ctdcast.select_best_available``.

.. autofunction:: ctdcast.select_best_available

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

Plotting parameters
-------------------

.. automodule:: ctdcast.config.parameters
   :members:
   :undoc-members:

.. automodule:: ctdcast.config.preferred_sensors
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

:mod:`~ctdcast.config.cnv_header` is the counterpart that reads *inwards* rather
than composing outwards: pure functions over a CNV header's text, recovering what
the deck unit and SBE Data Processing did to a cast before ctdcast saw it. It opens
no files — the header travels on every stage-1 file in ``raw_metadata``.

.. automodule:: ctdcast.config.cnv_header
   :members:
   :undoc-members:

----

Acquisition-clock diagnostic
----------------------------

:mod:`~ctdcast.analysis.clock` reads each cast's System/NMEA clock pair off the
header and classifies the cruise's clock error (constant, step, drift, or too
little to tell), recursively segmenting the whole-second offsets into levels and
claiming a drift only when a rate positively fits.  It is read-only — it finds the
error and generates a paste-ready ``processing.clock`` block; applying the
correction is a stage-2 step.

.. automodule:: ctdcast.analysis.clock
   :members:
   :undoc-members:

----

Section manifest
----------------

Each report page is described by a :class:`~ctdcast.reports._vendored.page_model.Profile` of
:class:`~ctdcast.reports._vendored.page_model.Section` and
:class:`~ctdcast.reports._vendored.page_model.Panel` entries, resolved by
:func:`~ctdcast.reports._vendored.page_model.resolve` into a numbered, rendered report.  The
model is package-neutral; each page's concrete registry lives in its own generator
module.

.. automodule:: ctdcast.reports._vendored.page_model
   :members:
   :undoc-members:

----

Page generators
---------------

.. automodule:: ctdcast.reports.cast
   :members:
   :undoc-members:

.. automodule:: ctdcast.reports.section
   :members:
   :undoc-members:

.. automodule:: ctdcast.reports.timeseries
   :members:
   :undoc-members:

.. automodule:: ctdcast.reports.dataset
   :members:
   :undoc-members:

----

Interactive map
---------------

.. automodule:: ctdcast.reports.cruise_map
   :members:
   :undoc-members:

----

QC tables
---------

.. automodule:: ctdcast.reports.qc_tables
   :members:
   :undoc-members:

----

Report design — colormaps and accent
-------------------------------------

``design`` is ctdcast's owned hook onto the vendored report layer: the package
accent for the shared CSS, and the effective per-quantity colormap table
(vendored family defaults, overridden by ctdcast's choices, resolved per
variable).  ``design_tokens`` is the vendored source of those family defaults.

.. automodule:: ctdcast.reports.design
   :members:
   :undoc-members:

.. automodule:: ctdcast.reports._vendored.design_tokens
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

.. automodule:: ctdcast.processors.sensor_catalog
   :members:
   :undoc-members:

.. automodule:: ctdcast.processors.history
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
