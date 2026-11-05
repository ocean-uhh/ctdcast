.. _report_output:
.. _output_structure:

=============
Report output
=============

All generated HTML files are fully self-contained: figures are embedded as base64 PNG
images, JavaScript libraries are bundled inline, and no external requests are made at
view time.  The entire output directory can be copied to a USB drive or a vessel
intranet server and used offline.

----

Directory layout
----------------

.. code-block:: text

   <output.dir>/
       index.html              summary: map and cruise-wide overview panels
       casts.html              map, sortable table of all casts, acquisition clock
       sections.html           section cards
       timeseries.html         time-series group cards
       leaflet.html            interactive map
       sbe_sensors.html        sensors by cast and device, and the sensor variables
       processing.html         every processing step applied, by run of casts
       <stem>_inventory.html   variables and attributes of each compiled file
                               (profiles_inventory.html, ladcp_profiles_inventory.html)
       corrections_ts.html     alignment and cell-thermal-mass fits, when ctdcast fit
                               has written fits.nc
       casts/
           cast_001.html
           cast_002.html
           ...
       sections/
           section_KTout.html
           section_FARDWO.html
           ...
       timeseries/
           timeseries_<name>.html
           ...

----

index.html
----------

The summary page.  Its masthead gives the cruise, ship, departure and arrival, duration,
number of casts and sections, and maximum depth, and links every other page.  Below it:

- **Map** — the cruise track and station positions (a static map; the interactive one is
  ``leaflet.html``).
- **Hydrography** — cruise-wide overview panels of conservative temperature, absolute
  salinity and potential density across all downcasts.
- **Biogeochemistry** — the same for oxygen, fluorescence and turbidity.
- **Velocity** — eastward and northward LADCP velocity, when LADCP data are present.
- **T–S diagram** — a CT–SA histogram of all downcast profiles.

----

casts.html
------------------

An interactive Leaflet map (bundled offline) above a sortable table.  The map shows one
marker per cast and a line per section; hovering a table row highlights its marker and vice
versa, and clicking a marker or row opens the station page.  A static map prints and shows
when JavaScript is off.

The table lists every cast: **Cast · File · Start (UTC) · Latitude · Longitude · Depth · QC
flagged · LADCP · Links** (*QC flagged* is the percentage of samples flagged suspect or fail;
*LADCP* appears when LADCP is configured).  An **Acquisition clock** section below it
compares the acquisition PC's clock with NMEA time cast by cast and suggests a ``clock``
block when they differ.

----

sections.html
-------------

One shared **Section tracks** map with every section drawn on it, then a card for each named
section in ``ctd_groupings.yaml`` with its name, description and casts, and a link to its
page.

----

Cast pages — ``casts/cast_NNN.html``
------------------------------------------

One page per cast.  The header gives the cast's position, time and depth, the **Raw input**
it was read from (``MIXSED2_012.hex + MIXSED2_012.XMLCON`` or ``mixsed2_012.cnv``) and its
**Sampling** (``24 Hz (native, unbinned)``, or what a CNV's ``# interval`` line says).
Sections, each shown only when it applies:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Section
     - Panels
   * - Overview
     - CT · SA · σ₀ against pressure (with the LADCP U and V profiles beside them when LADCP
       is present), the station map, and the T–S diagram down against up.
   * - Hydrography
     - CT · SA · σ₀ against pressure, downcast in colour, upcast in grey.
   * - Biogeochemistry
     - O₂ saturation, fluorescence and turbidity against pressure.
   * - T–S diagram
     - Coloured by O₂ saturation, downcast only.
   * - Stability
     - N² and Turner angle, downcast only.  Not drawn on a native-rate cast (unbinned 24 Hz
       scans); an amber note says why.
   * - Velocity (bottom track)
     - The LADCP bottom-track velocity, when LADCP data are present.
   * - Diagnostics
     - Pressure against time; primary minus secondary T and S; downcast minus upcast.
   * - QC flags
     - The distribution of each variable's values (grey all data, colour the data kept, a
       dashed line at each gross-range threshold), then the thresholds applied and the flag
       counts per variable.

Appendices: **(A) Sensors**, **(B) File provenance** (cast, data mode, processing stage and
the ``tracking_id`` lineage), **(C) netCDF data ranges** (minimum, maximum and valid count of
every variable in the file), and **(D) Processing provenance** (below).

Processing provenance
~~~~~~~~~~~~~~~~~~~~~~~

An appendix on each cast page reports what the Sea-Bird deck unit and Sea-Bird Data
Processing did to the cast **before** ctdcast read it, and, in a second table, **Corrections
applied by ctdcast** at stage 3 (and in its products), in the order they ran.  Both tables
number their steps (*#*).  ctdcast does not re-derive this;
it recovers it from the raw instrument header, which every stage-1 file carries verbatim
in its ``raw_metadata`` attribute and passes forward unchanged through stages 2 and 3.  A
cast with no Sea-Bird header (a LADCP cast, or a file converted without its header) has no
provenance appendix.

The **Corrections applied before ctdcast** table lists each step in file order — the deck
conductivity advance first, then each Data Processing module.  Its columns are:

- **Step** / **Producer** / **Version** — the module and who ran it.
- **Parameters** — the salient settings, close to the header's own wording.
- **Variables** — the variable(s) the step modified, in ctdcast's canonical names (the
  rename map is ``CNV_ALIASES`` in ``config/parameters.py``); a name it does not cover
  keeps its header spelling.
- **Matches reference** — a conformance check (see below), shown only for the SBE 9 / 11plus
  family, whose reference values are documented.

A step whose parameters differ per channel or per sensor — the deck advance (per
conductivity cell), cell thermal mass (per cell), the low-pass filter (per time-constant
group) — is split into one row each, so a check that passes on one channel and fails on
another is not hidden behind a single verdict.

Conformance
~~~~~~~~~~~

The **Matches reference** column compares each step's parameters against a *documented
typical value* and shows one of three states, **never conflated**:

- **✓** — matches the documented value.
- **✗** — differs from it.
- **—** — no reference exists to check against (an em dash, never a blank and never a
  cross).

A ✓ means "matches a documented typical value," **not** "correct"; a ✗ means "differs,"
**not** "wrong."  Every reference is configuration-dependent (a cell-thermal-mass α assumes
a pump and duct; the deck advance assumes standard plumbing), so each cell names the source
it compared against (e.g. *SBE manual p.92*), and the check is a match indicator, not a
verdict.  Some modules have no documented reference at all — Wild Edit, for instance, has
only *example* dialog values, so it shows **—** with those examples offered as suggested
starting points, not as a deviation.

A separate **Conformance** note collects the deviations as hedged, source-citing sentences,
kept distinct from the structural **Advisories** note (which reports what the file *is* —
e.g. already pressure-binned — rather than how its parameters compare).  The panel keeps its
focus on *what was done* to the data; per-sensor calibration state lives in the Sensors
appendix, and the panel carries a one-line pointer to it.

Sensors appendix
~~~~~~~~~~~~~~~~

A single table joins each science variable to the physical device that produced it, in one
row: **Variable · Role · Ch · Device · Model · Cal date · Slope · Offset**.  It is read from
the per-cast sensor catalog (the ``SENSOR_*`` entries and each variable's ``sensor`` link —
see :doc:`data_files`), not re-parsed from the header.  A
device with no stored variable still appears, with an empty Variable
cell; on a ``.hex`` cast a device ctdcast does not convert (pH, a user polynomial) is joined to
its raw voltage.  For a **frequency** sensor (temperature, conductivity, pressure) a Slope away from 1
or Offset away from 0 is a ``datcnv`` drift/span correction already baked in; that row is
tinted amber and the specific value bolded, so a correction is visible at a glance.  A cast
file that predates the catalog falls back to the header-parsed device inventory and
calibration-state tables.

----

processing.html
---------------

Every processing step applied to the casts in ``profiles.nc``, read from each profile's
``processing_record`` (see :doc:`data_files`), one table per stage: stage 1 (reading the raw
file), the Sea-Bird steps recorded in the raw header, stage 2 (soak and deck), stage 3 and the
products.  The columns are **# · Casts · Step · Producer · Version · Setting · Variables ·
Matches reference · Reference**; *#* numbers the steps in the order they ran, through the whole
page, and every row of a step carries its number, so sorting by *#* restores the order after
sorting by another column.

- Casts that used the same setting of a step share one row, its *Casts* column a run such as
  ``001–138``; a change of setting starts a new row.
- A step whose setting changed more than five times is drawn as one *varies cast to cast* row
  with the range of each changing number, and a figure of the value against cast number when
  only one number changes.
- A row is amber when the setting differs from the value SBE documents for that step, or when
  the step did not run as its setting says on some casts: Loop Edit without its soak test (a
  recording that starts below the surface-soak window), or Bin Average keeping the good values
  of scans with a flagged value, each get an amber row naming those casts.  The caption above
  the tables states the criterion.
- A step that runs more than once on a cast (a filter per variable, a correction per sensor)
  is matched across casts by the variables it changed.

What a step did on one cast (values marked, scans flagged) is on that cast's page.

The masthead groups ``sbe_sensors.html`` and ``processing.html`` in a **Provenance** row: they
describe how the data were taken and processed, not a data file, so they sit apart from the
*Data inventory* strip.

----

Section pages — ``sections/section_NAME.html``
----------------------------------------------

One page per named section, against distance along the section:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Section
     - Panels
   * - Map
     - The section track and its stations.
   * - Hydrography
     - CT, SA and σ₀ (with the 27.7 and 27.8 kg m⁻³ isopycnals labelled); triangles along the
       top mark the profiles.
   * - Biogeochemistry
     - Oxygen (``ctd_oxygen``, µmol kg⁻¹), fluorescence and turbidity, where present.
   * - Velocity
     - LADCP U (east) and V (north), when LADCP data are present.
   * - T–S diagrams
     - The section's water masses in temperature–salinity space.

The fields use discrete colorbars with 20 levels (the T–S diagrams 12; limits overridable with ``display.vmin`` /
``vmax``, see :doc:`config_yaml`).  Bathymetry is shown as a filled grey polygon when a GEBCO
file is available.

----

Time-series pages — ``timeseries.html`` and ``timeseries/timeseries_NAME.html``
--------------------------------------------------------------------------------

``timeseries.html`` is the index: a **Timeseries locations** map and a card for each
time-series group in ``ctd_groupings.yaml`` (repeat stations, sorted by time).  Each group's
page has:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Section
     - Panels
   * - Map
     - The group's station positions.
   * - Hydrography
     - CT, SA and σ₀ against time and pressure (downcasts).
   * - Biogeochemistry
     - Oxygen (``ctd_oxygen``), fluorescence and turbidity against time and pressure.
   * - Velocity
     - LADCP U and V, when LADCP data are present.
   * - T–S diagram
     - The group's profiles in temperature–salinity space.

Time runs on the horizontal axis, pressure on the vertical axis (increasing downward).
