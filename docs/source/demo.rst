.. _demo:

==========================
About the demo report
==========================

The pages below are generated from the four committed fixture casts (cruise **odb26**, ship *Odon de Buen*, North Atlantic July 2026) using the same pipeline you would run on your own data.
They cover: two casts on a short transect (casts 011–012, section "KO") and two casts at a repeat station (casts 128–129, timeseries "Triangle"), all with LADCP.

**Run it yourself** — from a source checkout (the fixture casts come with the repository, not
with ``pip install``), generate a report from the same casts:

.. code-block:: bash

   ctdcast run config_demo.yaml --stage profiles

The casts are stage-1 files: ``--stage profiles`` compiles and reports them without running
stages 2 and 3, which would write into the fixtures.  The published demo above is made by
``scripts/make_demo.py``, which also runs stage 2 and QC, so it has the QC tables the local
report lacks.  Output is written to ``demo_report/`` in the repo root, the compiled file to
``demo_work/``.
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
   * - `Cast index <_static/demo/casts.html>`_
     - Sortable table of all casts with position, depth, and time
   * - `Cast 011 <_static/demo/casts/cast_011.html>`_
     - Station page — CT/SA/σ₀ profiles, T–S diagram, LADCP, altimeter
   * - `Cast 128 <_static/demo/casts/cast_128.html>`_
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

- `config_demo.yaml <https://github.com/ocean-uhh/ctdcast/blob/main/config_demo.yaml>`_ — top-level config (paths, cruise info, which pages to build); also at the repo root
- `ctd_sections_demo.yaml <_static/ctd_sections_demo.yaml>`_ — section and timeseries definitions

----

Regenerating the demo
----------------------

To rebuild the demo HTML from scratch (e.g. after changing the templates or mplstyle)::

   python scripts/make_demo.py

The script reads fixture data from ``tests/fixtures/``, builds a ``profiles_demo.nc``,
and writes all HTML to ``docs/source/_static/demo/``.
Commit the result so the docs work without re-running the script.
