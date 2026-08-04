.. _quickstart:

================
Quickstart guide
================

This guide walks through generating a ctdreport report from CTD data.
Two workflows are available: a quick-look path that needs only raw CNV files and no
configuration, and a full workflow for sections, time series, and LADCP panels.

----

Quick look (no config file needed)
-----------------------------------

If you have raw SBE CNV files and want station pages + index + map immediately::

   pip install seasenselib
   ctdreport draft /path/to/cnv/                         # output → ./ctd_draft/
   ctdreport draft /path/to/cnv/ ./out/ --cruise odb2026 # with cruise ID and output dir
   ctdreport draft /path/to/cnv/ --dry-run               # preview without writing

``ctdreport draft`` converts CNV files to netCDF via ``seasenselib``, then generates
station pages, an index, and a Leaflet map in one step.  No ``config.yaml`` is needed.
Sections and time series pages are **not** generated (they require a compiled
``profiles.nc``).  For those, use the full workflow below.

----

Full workflow prerequisites
---------------------------

Python 3.10–3.13 is required.  Create a virtual environment and install from source:

.. code-block:: bash

   git clone https://github.com/ocean-uhh/ctdreport
   cd ctdreport
   python -m venv venv
   source venv/bin/activate        # macOS / Linux
   pip install -e .

----

Prepare your input files
-------------------------

ctdreport needs at minimum a directory of per-cast netCDF files (one per CTD cast).
Section and time series pages additionally require a compiled ``profiles.nc``.

.. code-block:: text

   /data/cruise/CTD/
       cnv_nc/
           cast_001.nc
           cast_002.nc
           ...
       profiles.nc          # compiled 2D profiles (optional but recommended)

See :doc:`config_reference` for a description of what each file must contain.

----

Edit config.yaml
----------------

Copy the example ``config.yaml`` from the repository and adjust the paths:

.. code-block:: yaml

   data:
     nc_dir:       /data/cruise/CTD/cnv_nc
     profiles_nc:  /data/cruise/CTD/profiles.nc
     section_yaml: /data/cruise/config/ctd_sections.yaml
     gebco_nc:     /data/GEBCO_2025.nc   # optional

   output:
     dir: /data/cruise/report

   generate:
     stations:   true
     sections:   true    # requires profiles.nc and section_yaml
     timeseries: true    # requires profiles.nc

Leave ``gebco_nc`` blank or omit it entirely if you do not have a GEBCO file — maps will
render without bathymetry.

----

Define your sections
--------------------

If ``generate.sections`` is ``true``, create a ``ctd_sections.yaml`` file that groups
casts into named transects:

.. code-block:: yaml

   sections:
     KTout:
       description: "Kögur Transect outflow"
       color: "#e41a1c"
       cast_numbers: [[1, 12], 15]   # ranges and/or individual cast numbers
     FARDWO:
       description: "FARDWO mooring array"
       color: "#377eb8"
       cast_numbers: [[20, 35]]

See :doc:`config_reference` for the full section YAML specification.

----

Generate the report
-------------------

.. code-block:: bash

   ctdreport run config.yaml

To force regeneration of all pages (including ones that already exist):

.. code-block:: bash

   ctdreport run config.yaml --force

----

Open the report
---------------

Open ``<output.dir>/index.html`` in any browser.  The file is fully self-contained —
copy the entire output directory anywhere and it works offline.

.. code-block:: text

   <output.dir>/
       index.html              front page — map, cast count, navigation
       station_index.html      sortable table of all casts
       sections.html           section cards with links
       timeseries.html         T, S, O₂ hovmöller diagrams
       stations/
           cast_001.html
           ...
       sections/
           section_KTout.html
           ...

See :doc:`output_structure` for a description of what each page contains.

----

Updating mid-cruise
-------------------

All three steps are incremental by default — already-generated HTML pages are skipped.
After adding new casts, rebuild ``profiles.nc`` if needed, then re-run:

.. code-block:: bash

   ctdreport run config.yaml

Only pages for new casts will be written.  Existing section and time series pages are
**not** automatically updated when new casts arrive; add ``--force`` or set
``force: true`` to rebuild them.

----

Where to go next
----------------

- :doc:`config_reference` — all ``config.yaml`` and ``ctd_sections.yaml`` fields.
- :doc:`output_structure` — what each report page contains.
- :doc:`api` — Python API for calling ctdreport from your own scripts.
