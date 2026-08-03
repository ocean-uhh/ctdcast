.. _cli_reference:

=============
CLI reference
=============

All subcommands are available via the ``ctdreport`` entry point.
Run ``ctdreport <command> --help`` for the full flag list at any time.

----

ctdreport draft
---------------

Quick-look pipeline: convert raw CNV files to station pages + index + map in one step.
No ``config.yaml`` required.  Sections and time series are skipped (require ``profiles.nc``).

.. code-block:: text

   ctdreport draft <cnv_dir> [out_dir] [options]

   positional arguments:
     cnv_dir          Directory of raw SBE CNV files (required)
     out_dir          Output directory (default: ./ctd_draft/)

   options:
     --cruise ID      Cruise ID shown in the report header
                      (default: read from nc file attrs, fallback 'draft')
     --ship NAME      Ship name shown in the report header
     --keep-nc DIR    Save converted netCDF files to DIR instead of discarding after the run
     --force          Regenerate existing pages regardless of modification times
     --dry-run        Print what would be done without writing any files

Requires ``seasenselib`` (``pip install seasenselib``) for CNV conversion.

**Examples**::

   ctdreport draft /data/cnv/
   ctdreport draft /data/cnv/ ./out/ --cruise odb2026 --ship RRS_Discovery
   ctdreport draft /data/cnv/ --keep-nc ./nc_out/ --force
   ctdreport draft /data/cnv/ --dry-run

----

ctdreport init
--------------

Write a commented template ``config.yaml`` (and optionally ``ctd_sections.yaml``)
in the target directory.

.. code-block:: text

   ctdreport init [dest] [options]

   positional arguments:
     dest             Destination directory or explicit .yaml path (default: .)

   options:
     --sections       Also write a template ctd_sections.yaml
     --force          Overwrite existing files

**Examples**::

   ctdreport init                        # write config.yaml in current directory
   ctdreport init /data/cruise/
   ctdreport init --sections             # also write ctd_sections.yaml
   ctdreport init myconfig.yaml          # explicit output path

----

ctdreport validate
------------------

Validate config paths and data before the first run.  Does not write any files.

.. code-block:: text

   ctdreport validate <config> [options]

   positional arguments:
     config           Path to config.yaml

   options:
     --strict         Also check that all cast numbers referenced in
                      ctd_sections.yaml are present in nc_dir

**Examples**::

   ctdreport validate config.yaml
   ctdreport validate config.yaml --strict

----

ctdreport convert
-----------------

Convert raw data to netCDF inputs without generating HTML.

.. code-block:: text

   ctdreport convert <config> [options]

   positional arguments:
     config           Path to config.yaml

   step selection (default: --profiles only if data.profiles_nc is configured):
     --ctd            Convert per-cast CNV files to netCDF (requires data.cnv_dir in config)
     --profiles       Compile per-cast netCDF files into profiles.nc

   options:
     --backend NAME   CTD conversion backend (currently only 'seasenselib')
     --cast N         Convert only cast N (implies --ctd)
     --force          Overwrite existing output files
     --dry-run        Print what would be done without writing any files

**Examples**::

   ctdreport convert config.yaml                  # build profiles.nc (default)
   ctdreport convert config.yaml --ctd            # CNV → nc, then profiles.nc
   ctdreport convert config.yaml --profiles       # rebuild profiles.nc only
   ctdreport convert config.yaml --ctd --cast 42  # convert one cast
   ctdreport convert config.yaml --dry-run

----

ctdreport report
----------------

Generate HTML pages from existing netCDF inputs.  Does not run any conversion.

.. code-block:: text

   ctdreport report <config> [options]

   positional arguments:
     config           Path to config.yaml

   page selection (default: all page types enabled in config):
     --stations       Generate per-cast station pages
     --sections       Generate section pages (requires profiles.nc and section_yaml)
     --timeseries     Generate timeseries pages (requires profiles.nc and section_yaml)
     --index          Generate index.html and station_index.html
     --map            Generate leaflet.html interactive map

   options:
     --cast N         Regenerate only the station page for cast N
     --force          Regenerate all pages regardless of modification times
     --skip-existing  Skip pages whose HTML already exists (fill missing pages only)
     --dry-run        Print what would be done without writing any files

**Examples**::

   ctdreport report config.yaml                   # generate all enabled page types
   ctdreport report config.yaml --stations        # station pages only
   ctdreport report config.yaml --cast 42 --force # rebuild one cast page
   ctdreport report config.yaml --skip-existing   # fill any missing pages
   ctdreport report config.yaml --dry-run

----

ctdreport run
-------------

Run convert then report in one step (most common workflow).

.. code-block:: text

   ctdreport run <config> [options]

   positional arguments:
     config           Path to config.yaml

   options:
     --ctd            Also run CNV → netCDF conversion before building profiles
                      (requires data.cnv_dir in config)
     --cast N         Rebuild only the station page for cast N (skips profiles step)
     --force          Force regeneration of all outputs regardless of modification times
     --skip-existing  Skip pages whose HTML already exists
     --dry-run        Print what would be done without writing any files

Equivalent to running ``ctdreport convert`` then ``ctdreport report`` in sequence.

**Examples**::

   ctdreport run config.yaml                      # smart update (skips up-to-date pages)
   ctdreport run config.yaml --force              # rebuild everything
   ctdreport run config.yaml --cast 42            # rebuild one cast page
   ctdreport run config.yaml --ctd --force        # full pipeline including CNV conversion
   ctdreport run config.yaml --dry-run
