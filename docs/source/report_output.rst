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
       index.html              front page
       casts.html              sortable table of all casts
       sections.html           section overview cards
       timeseries.html         cruise-wide time series index
       leaflet.html            interactive map
       sbe_sensors.html        sensor inventory across casts
       profiles_inventory.html netCDF variable + attribute inventory
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

The front page shows:

- An interactive Leaflet map (bundled offline) with the ship track and all cast
  positions.  Clicking a marker opens a pop-up with cast number and a link to the
  station page.
- A summary table: total casts, date range, depth range.
- Navigation links to the station index, section overview, and time series page.

----

casts.html
------------------

A sortable table listing every cast: cast number, date/time, latitude, longitude, and
maximum pressure.  Each row links to the corresponding station page.

----

sections.html
-------------

A card grid showing each named section from ``ctd_groupings.yaml``.  Each card shows the
section name, description, cast count, and a thumbnail map.  Clicking a card opens the
section page.

----

Cast pages — ``casts/cast_NNN.html``
------------------------------------------

One page per cast.  Panels shown:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Panel
     - Description
   * - CT profile
     - Conservative Temperature vs pressure (downcast and upcast).
   * - T / S / σ₀ profile
     - Triple-axis profile of in-situ temperature, absolute salinity, and potential
       density anomaly.
   * - T-S diagram
     - Temperature–salinity diagram coloured by O₂ saturation.
   * - Auxiliary profiles
     - O₂ saturation, fluorescence, and turbidity vs pressure.
   * - Stability panels
     - Buoyancy frequency N² and Turner angle vs pressure.
   * - Cast map
     - Cruise track with the current cast highlighted.
   * - LADCP profiles
     - Eastward and northward velocity vs pressure (shown when LADCP data are
       present).

Processing provenance
~~~~~~~~~~~~~~~~~~~~~~~

An appendix on each cast page reports what the Sea-Bird deck unit and Sea-Bird Data
Processing did to the cast **before** ctdcast read it.  ctdcast does not re-derive this;
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
device with no stored variable (pH, a transmissometer) still appears, with an empty Variable
cell.  For a **frequency** sensor (temperature, conductivity, pressure) a Slope away from 1
or Offset away from 0 is a ``datcnv`` drift/span correction already baked in; that row is
tinted amber and the specific value bolded, so a correction is visible at a glance.  A cast
file that predates the catalog falls back to the header-parsed device inventory and
calibration-state tables.

----

Section pages — ``sections/section_NAME.html``
----------------------------------------------

One page per named section.  Panels shown:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Panel
     - Description
   * - Conservative Temperature section
     - CT colour-filled on a distance × pressure grid.
   * - Absolute Salinity section
     - SA colour-filled on a distance × pressure grid.
   * - Potential density (σ₀) section
     - σ₀ colour-filled on a distance × pressure grid.
   * - O₂ saturation section
     - O₂ colour-filled on a distance × pressure grid.
   * - Section map
     - Cruise track with section casts highlighted.

All section plots use discrete colorbars with 20 levels.  Bathymetry is shown as a
filled grey polygon when a GEBCO file is available.

----

timeseries.html
---------------

Cruise-wide hovmöller diagrams:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Panel
     - Description
   * - Temperature
     - CT vs time and pressure (downcasts only).
   * - Salinity
     - SA vs time and pressure (downcasts only).
   * - O₂ saturation
     - O₂ % vs time and pressure (downcasts only).

Time runs on the horizontal axis; pressure on the vertical axis (increasing downward).
