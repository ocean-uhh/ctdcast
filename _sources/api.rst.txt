.. _api:

============
Python API
============

The public entry points are importable from ``ctdcast`` itself: :func:`ctdcast.process` runs
processing stages, :func:`ctdcast.report` builds the HTML report, and
``ctdcast.stage1`` / ``ctdcast.profiles`` run stage 1 and the profiles compile on their own.

----

Main entry points
-----------------

.. autofunction:: ctdcast.processors.process

.. autofunction:: ctdcast.reports.index.report

``ctdcast.stage1`` is :func:`ctdcast.processors.stage1.stage1` and ``ctdcast.profiles`` is
:func:`ctdcast.processors.profiles.build_profiles`, both documented below.

The stage registry: one entry per stage token, read by the CLI's ``--stage`` and by
:func:`ctdcast.process`.

.. autodata:: ctdcast.processors.STAGES
   :no-value:

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
dataset lacks the required variables). They are grouped by subject.

Maps
^^^^

.. automodule:: ctdcast.plotters.maps
   :members:
   :undoc-members:

Profiles
^^^^^^^^

.. automodule:: ctdcast.plotters.profiles
   :members:
   :undoc-members:

Sections
^^^^^^^^

.. automodule:: ctdcast.plotters.sections
   :members:
   :undoc-members:

Time series
^^^^^^^^^^^

.. automodule:: ctdcast.plotters.timeseries
   :members:
   :undoc-members:

LADCP
^^^^^

.. automodule:: ctdcast.plotters.ladcp
   :members:
   :undoc-members:

Corrections (alignment and cell thermal mass)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The figures on the *T/S corrections* page, drawn from the ``fits.nc`` file ``ctdcast fit`` writes.

.. automodule:: ctdcast.plotters.corrections
   :members:
   :undoc-members:

The figure of a processing setting against cast number, for the processing page.

.. automodule:: ctdcast.plotters.processing
   :members:

The figure for a ctdcast-versus-Sea-Bird comparison: the difference in each variable against
pressure.

.. automodule:: ctdcast.plotters.sbe_compare
   :members:

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

.. automodule:: ctdcast.config.sensors
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

:mod:`~ctdcast.config.sbe_steps` turns the SBE Data Processing steps recorded in a CNV header
into the equivalent ``data_processing:`` steps, in the order they ran, with each step's
parameters and ctdcast's variable names — the starting point for reproducing a cruise's own CNVs
from its ``.hex`` files.

.. automodule:: ctdcast.config.sbe_steps
   :members:

:mod:`~ctdcast.config.layout` reads a ``config.yaml`` into the settings the stages use, from the
current layout or, for one release, the 0.4 one.

.. automodule:: ctdcast.config.layout
   :members:

----

Acquisition-clock diagnostic
----------------------------

:mod:`~ctdcast.analysis.clock` reads each cast's System/NMEA clock pair off the
header and classifies the cruise's clock error (constant, step, drift, or too
little to tell), recursively segmenting the whole-second offsets into levels and
claiming a drift only when a rate positively fits.  It is read-only — it finds the
error and generates a paste-ready ``clock`` block; applying the
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

.. automodule:: ctdcast.reports.sbe_processing
   :members:

.. automodule:: ctdcast.reports.processing
   :members:

.. automodule:: ctdcast.reports.corrections
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

:mod:`~ctdcast.analysis.fits` holds the alignment and cell-thermal-mass cost functions and the
cruise aggregation behind ``ctdcast fit`` — pure numpy over a cast's arrays, writing no files.

.. automodule:: ctdcast.analysis.fits
   :members:
   :undoc-members:

:mod:`~ctdcast.analysis.processing_record` lists every step applied to a cast — stage 1, the
Sea-Bird steps in the raw header, stage 2, stage 3 and products — with the setting kept apart from
what it did on the cast; ``profiles.nc`` stores it per cast as ``processing_record``.

.. automodule:: ctdcast.analysis.processing_record
   :members:

:mod:`~ctdcast.analysis.sbe_compare` compares a ctdcast stage file with a Sea-Bird CNV made from
the same ``.hex``, scan by scan: per-variable differences where neither side flags the scan, and
the flags of each side counted against the other.

.. automodule:: ctdcast.analysis.sbe_compare
   :members:

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

.. automodule:: ctdcast.processors.steps
   :members:

.. automodule:: ctdcast.processors.editing
   :members:

.. automodule:: ctdcast.processors.filtering
   :members:

.. automodule:: ctdcast.processors.products
   :members:

.. automodule:: ctdcast.processors.corrections
   :members:
   :undoc-members:

:mod:`~ctdcast.processors.fit` is ``ctdcast fit``: it scores every native-rate stage-2 cast with
:mod:`~ctdcast.analysis.fits`, writes the cost surfaces to ``fits.nc``, and turns them into the
cruise summary and the suggested ``data_processing:`` block.

.. automodule:: ctdcast.processors.fit
   :members:
   :undoc-members:

----

Stage layout
^^^^^^^^^^^^

Where each stage's files live and how a file's stage is read from its name.

.. automodule:: ctdcast.processors.stage_layout
   :members:

.. automodule:: ctdcast.processors.ladcp
   :members:

.. automodule:: ctdcast.processors.units
   :members:

----

Readers
-------

.. automodule:: ctdcast.readers.cnv
   :members:

.. automodule:: ctdcast.readers.ladcp
   :members:
   :undoc-members:

.. automodule:: ctdcast.readers.metadata
   :members:
   :undoc-members:

.. automodule:: ctdcast.readers.hex
   :members:
   :undoc-members:

.. automodule:: ctdcast.readers.xmlcon
   :members:
   :undoc-members:

----

Writers
-------

.. automodule:: ctdcast.writers.netcdf
   :members:

.. automodule:: ctdcast.writers.dtypes
   :members:

----

Configuration
-------------

.. automodule:: ctdcast.config.loader
   :members:

.. automodule:: ctdcast.config.report_config
   :members:
