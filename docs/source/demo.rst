.. _demo:

===========
CTD report
===========

The pages below are generated from the four committed fixture casts (cruise **odb26**, ship *Odon de Buen*, North Atlantic July 2026) using the same pipeline you would run on your own data.
They cover: two casts on a short transect (casts 011–012, section "KO") and two casts at a repeat station (casts 128–129, timeseries "Triangle"), all with LADCP.

**Run it yourself** — after installing ctdreport, generate the same report locally:

.. code-block:: bash

   ctdreport run config_demo.yaml

Output is written to ``demo_report/`` in the repo root.
To open it: find ``demo_report/index.html`` in your file manager and double-click it,
or from the terminal::

   open demo_report/index.html          # macOS
   xdg-open demo_report/index.html      # Linux
   start demo_report/index.html         # Windows

.. list-table::
   :widths: 30 70
   :header-rows: 0

   * - `Summary (index) <_static/demo/index.html>`_
     - Front page — cruise map, cast count, navigation to all sections
   * - `Station index <_static/demo/station_index.html>`_
     - Sortable table of all casts with position, depth, and time
   * - `Cast 011 <_static/demo/stations/cast_011.html>`_
     - Station page — CT/SA/σ₀ profiles, T–S diagram, LADCP, altimeter
   * - `Cast 128 <_static/demo/stations/cast_128.html>`_
     - Deeper cast (686 dbar)
   * - `Section KO <_static/demo/sections/section_KO.html>`_
     - Two-cast transect section (CT, SA, σ₀, O₂)
   * - `Timeseries Triangle <_static/demo/timeseries/timeseries_Triangle.html>`_
     - Repeat-station time series (CT, SA, σ₀, O₂, fluorescence, turbidity)
   * - `Interactive map <_static/demo/leaflet.html>`_
     - Leaflet map with cast markers and GEBCO bathymetry contours

----

Config files
------------

The two YAML files used to generate this demo are available to download and adapt:

- `config_demo.yaml <https://github.com/eleanorfrajka/ctdreport/blob/main/config_demo.yaml>`_ — top-level config (paths, cruise info, which pages to build); also at the repo root
- `ctd_sections_demo.yaml <_static/ctd_sections_demo.yaml>`_ — section and timeseries definitions

----

Regenerating the demo
----------------------

To rebuild the demo HTML from scratch (e.g. after changing the templates or mplstyle)::

   python scripts/make_demo.py

The script reads fixture data from ``tests/fixtures/``, builds a ``profiles_demo.nc``,
and writes all HTML to ``docs/source/_static/demo/``.
Commit the result so the docs work without re-running the script.
