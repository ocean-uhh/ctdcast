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
       casts.html      sortable table of all casts
       sections.html           section overview cards
       timeseries.html         cruise-wide time series
       casts/
           cast_001.html
           cast_002.html
           ...
       sections/
           section_KTout.html
           section_FARDWO.html
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

A card grid showing each named section from ``ctd_sections.yaml``.  Each card shows the
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
