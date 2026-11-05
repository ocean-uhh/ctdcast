.. _quickstart:

================
Quickstart guide
================

This guide takes a cruise's CTD data from the raw files to a report.
Two workflows are available: a quick look that needs only CNV files and no configuration,
and the full workflow — raw ``.hex`` or ``.cnv`` through every processing stage, with
sections, time series, LADCP panels and the processing record.

----

Quick look (no config file needed)
-----------------------------------

If you have SBE CNV files and want cast pages, an index and a map immediately::

   pip install "ctdcast[cnv]"
   ctdcast draft /path/to/cnv/                         # output → ./ctd_draft/
   ctdcast draft /path/to/cnv/ ./out/ --cruise odb2026 # with cruise ID and output dir
   ctdcast draft /path/to/cnv/ --dry-run               # preview without writing

``ctdcast draft`` reads the CNV files to netCDF (stage 1), compiles ``profiles.nc`` and
builds the cast pages, the index, the map, the sensors page and the processing page in one
step.  No ``config.yaml`` is needed.  It builds no section or time-series pages (their index
pages are empty): those need a groupings file that says which casts belong together; for
those, use the full workflow below.

----

Full workflow prerequisites
---------------------------

Python 3.11–3.14 is required.  Install from PyPI into a virtual environment:

.. code-block:: bash

   python -m venv venv
   source venv/bin/activate        # macOS / Linux
   pip install ctdcast             # reads .hex; add [cnv] to read .cnv

or from source, which also gives you the demo:

.. code-block:: bash

   git clone https://github.com/ocean-uhh/ctdcast
   cd ctdcast
   python -m venv venv
   source venv/bin/activate        # macOS / Linux
   pip install -e .

Land coastlines on the interactive maps need the optional ``maps`` extra (cartopy and
shapely): ``pip install -e ".[maps]"``.  Without it the maps draw over a lat/lon graticule.

To check a source checkout, build a demo report from the committed fixture casts.  They are
stage-1 files: ``--stage profiles`` compiles and reports them without running stages 2 and 3
(which would write into the fixtures), and the compiled file goes to a work folder
(``demo_work/``):

.. code-block:: bash

   ctdcast run config_demo.yaml --stage profiles

Then open ``demo_report/index.html`` in a browser.
See :ref:`demo` for a preview of what the output looks like.

----

Prepare your input files
-------------------------

ctdcast starts from the raw files, one per cast: Sea-Bird ``.hex`` files with the
``.xmlcon`` beside each (``hex_dir``), or ``.cnv`` files (``cnv_dir``).  It never writes
there.  LADCP profiles come as processed ``.mat`` files, one per cast (``ladcp_dir``).

Each instrument gets one **root** that ctdcast owns and fills.  Inside it, one directory per
processing stage, products, and the compiled file at the top:

.. code-block:: text

   /data/cruise/CTD/ctd_nc/          # ctd_root
       stage1/
           MIXSED2_001_stage1.nc     # the raw file read to netCDF (named after it)
           MIXSED2_002_stage1.nc
       stage2/
           MIXSED2_001_stage2.nc     # + soak / back-on-deck flags
       stage3/
           MIXSED2_001_stage3.nc     # + Sea-Bird's steps, calibration and QC
       products/
           1dbar_down/
               MIXSED2_001_1dbar_down.nc   # a product, as configured
       profiles.nc                   # the compiled casts

   /data/cruise/LADCP/ladcp_nc/      # ladcp_root
       stage1/
       ladcp_profiles.nc

A directory of unsuffixed per-cast files written before the stage layout is still
read, as stage 1.

See :doc:`data_files` for what each file contains.

----

Edit config.yaml
----------------

Generate a template with ``ctdcast init`` (it writes a commented ``config.yaml`` in
the current directory), then adjust the paths:

.. code-block:: yaml

   data:
     ctd_root:     /data/cruise/CTD/ctd_nc     # ctdcast's; profiles.nc goes at its top
     hex_dir:      /data/cruise/CTD/raw        # .hex + .xmlcon, read only
     # cnv_dir:    /data/cruise/CTD/cnv        # or .cnv instead (needs ctdcast[cnv])
     groupings_yaml: /data/cruise/config/ctd_groupings.yaml
     gebco_nc:     /data/GEBCO_2025.nc         # optional

   output:
     dir: /data/cruise/report

   generate:
     stations:   true
     sections:   true    # requires profiles.nc and groupings_yaml
     timeseries: true    # requires profiles.nc

Leave ``gebco_nc`` blank or omit it entirely if you do not have a GEBCO file — maps will
render without bathymetry.  Sea-Bird's processing steps (Wild Edit, filters, alignment, cell
thermal mass, Loop Edit) and the products go in a ``data_processing`` block;
``ctdcast inspect cast.cnv`` prints that block from a CNV's own header, so you can start from
the steps used at sea.  See :doc:`config_yaml`.

----

Define your sections
--------------------

If ``generate.sections`` is ``true``, create a ``ctd_groupings.yaml`` file that groups
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

See :doc:`ctd_groupings` for the full groupings YAML specification.

----

Process and report
------------------

.. code-block:: bash

   ctdcast run config.yaml

``run`` runs every stage from the raw files (1, 2, 3, then the compile) and builds the
report.  To work a step at a time, use ``ctdcast process config.yaml --stage …`` and
``ctdcast report config.yaml`` (see :doc:`cli_reference`).

To force every stage and page to be rebuilt (including ones that are up to date):

.. code-block:: bash

   ctdcast run config.yaml --force

----

Open the report
---------------

Open ``<output.dir>/index.html`` in any browser.  The file is fully self-contained —
copy the entire output directory anywhere and it works offline.

.. code-block:: text

   <output.dir>/
       index.html              summary — map, overview panels, navigation
       casts.html              map and sortable table of all casts
       sections.html           section cards with links
       timeseries.html         time-series groups with links
       leaflet.html            interactive map
       sbe_sensors.html        sensors by cast and device
       processing.html         every processing step, by run of casts
       profiles_inventory.html variables and attributes of profiles.nc
       casts/
           cast_001.html
           ...
       sections/
           section_KTout.html
           ...
       timeseries/
           timeseries_<name>.html
           ...

See :doc:`report_output` for a description of what each page contains.

----

Updating mid-cruise
-------------------

``run`` is incremental.  A stage-1 file is read only when it is missing (``--force`` reads
a replaced raw file again); a stage-2 or stage-3 file is rebuilt when its input is newer;
``profiles.nc`` when a cast file is newer; a cast, section or time-series page when the files
it is drawn from are newer.  The cruise-wide pages (summary, casts, sensors, processing, …)
are rebuilt on every run.  After new casts arrive, run it again:

.. code-block:: bash

   ctdcast run config.yaml

The new casts are processed and get their pages; ``profiles.nc`` is recompiled, so the
section, time series and summary pages are rebuilt with them.  A config change is not a newer
file: after changing the processing steps or thresholds, add ``--force`` (with ``--only`` to
limit it to a few casts).

----

Where to go next
----------------

- :doc:`config_yaml` — every ``config.yaml`` field.
- :doc:`processing_framework` — the stages and what each one does.
- :doc:`cruise_metadata` — the ``cruise_info`` block: identity, platform, people, embargo.
- :doc:`ctd_groupings` — every ``ctd_groupings.yaml`` field.
- :doc:`data_files` — the netCDF files ctdcast reads and writes.
- :doc:`report_output` — what each report page contains.
- :doc:`api` — Python API for calling ctdcast from your own scripts.
