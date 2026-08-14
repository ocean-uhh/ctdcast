.. _cli_reference:

=============
CLI reference
=============

All subcommands are available via the ``ctdcast`` entry point.
Run ``ctdcast <command> --help`` for the full flag list at any time.

----

ctdcast draft
---------------

Quick-look pipeline: convert raw CNV files to station pages + index + map in one step.
No ``config.yaml`` required.  Sections and time series are skipped (require ``profiles.nc``).

.. code-block:: text

   ctdcast draft <cnv_dir> [out_dir] [options]

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

   ctdcast draft /data/cnv/
   ctdcast draft /data/cnv/ ./out/ --cruise odb2026 --ship RRS_Discovery
   ctdcast draft /data/cnv/ --keep-nc ./nc_out/ --force
   ctdcast draft /data/cnv/ --dry-run

----

ctdcast init
--------------

Write a commented template ``config.yaml`` (and optionally auto-detect
sections/timeseries groups from ``profiles.nc``) in the target directory.

.. code-block:: text

   ctdcast init [dest] [options]

   positional arguments:
     dest                  Destination directory or explicit .yaml path (default: .)

   options:
     --sections            Also write a template ctd_sections.yaml
     --interactive         Prompt for all data paths and cruise metadata,
                           then offer to auto-detect sections/timeseries
     --auto-section        Re-run section/timeseries detection from an existing
                           config and overwrite ctd_sections_draft.yaml.
                           Reads profiles_nc from the config; does not touch config.yaml.
     --force               Overwrite existing files

   detection thresholds (used with --interactive or --auto-section):
     --dx-diameter KM      Max inter-cast distance (km) within a repeat-station cluster (default: 1)
     --dx-section KM       Inter-cast gap (km) that starts a new coarse group (default: 50)
     --max-turn-deg DEG    Max heading change (°) within a directional run (default: 45)
     --min-run-casts N     Min casts for a run to be kept as a section (default: 4, min: 3)
     --max-section-casts N Safety cap: split runs longer than this (default: 25)

**Detection algorithm** (``--interactive`` / ``--auto-section``):

1. Coarse gap split on inter-cast distance > ``--dx-section``.
2. Within each coarse group, find maximal sub-sequences where every consecutive
   heading change ≤ ``--max-turn-deg`` (stable-heading run detection).
   A backward-extension step adds the "approach station" when the ship arrives
   at the first section station from the section's bearing direction.
3. Remaining unclaimed casts are clustered by proximity: consecutive unclaimed
   casts within ``--dx-diameter`` of each other form a repeat-station cluster.
4. Classification is by detection method: stable-heading runs → sections;
   diameter clusters → timeseries.
5. Runs > ``--max-section-casts`` are split into consecutive chunks.

Output is ``ctd_sections_draft.yaml`` (alongside ``section_yaml`` from the config,
or in the config's directory).  Review and rename to ``ctd_sections.yaml`` before use.

**Examples**::

   ctdcast init                          # write config.yaml in current directory
   ctdcast init /data/cruise/
   ctdcast init --sections               # also write a template ctd_sections.yaml
   ctdcast init --interactive config.yaml --force   # guided setup with auto-detection
   ctdcast init --auto-section config.yaml --force  # re-detect sections only

----

ctdcast validate
------------------

Validate config paths and data before the first run.  Does not write any files.

.. code-block:: text

   ctdcast validate <config> [options]

   positional arguments:
     config           Path to config.yaml

   options:
     --strict         Also check that all cast numbers referenced in
                      ctd_sections.yaml are present in nc_dir

**Examples**::

   ctdcast validate config.yaml
   ctdcast validate config.yaml --strict

----

ctdcast convert
-----------------

Convert raw data to netCDF inputs without generating HTML.

.. code-block:: text

   ctdcast convert <config> [options]

   positional arguments:
     config           Path to config.yaml

   step selection (default: --profiles only if data.profiles_nc is configured):
     --ctd            Convert per-cast CNV files to netCDF (requires data.cnv_dir in config)
     --profiles       Compile per-cast netCDF files into profiles.nc

   options:
     --backend NAME   CTD conversion backend (currently only 'seasenselib')
     --only N         Convert only cast N (implies --ctd)
     --force          Overwrite existing output files
     --dry-run        Print what would be done without writing any files

   (The former ``--cast`` spelling still works as a deprecated alias for ``--only``.)

**Examples**::

   ctdcast convert config.yaml                  # build profiles.nc (default)
   ctdcast convert config.yaml --ctd            # CNV → nc, then profiles.nc
   ctdcast convert config.yaml --profiles       # rebuild profiles.nc only
   ctdcast convert config.yaml --ctd --only 42  # convert one cast
   ctdcast convert config.yaml --dry-run

----

ctdcast report
----------------

Generate HTML pages from existing netCDF inputs.  Does not run any conversion.

.. code-block:: text

   ctdcast report <config> [options]

   positional arguments:
     config           Path to config.yaml

   page selection (default: all page types enabled in config):
     --casts          Generate per-cast pages
     --sections       Generate section pages (requires profiles.nc and section_yaml)
     --timeseries     Generate timeseries pages (requires profiles.nc and section_yaml)
     --index          Generate index.html and casts.html
     --map            Generate leaflet.html interactive map
     --all            Generate every page type

   options:
     --only N [N ...] Regenerate only the pages for cast N (one or more)
     --force          Regenerate all pages regardless of modification times
     --skip-existing  Skip pages whose HTML already exists (fill missing pages only)
     --dry-run        Print what would be done without writing any files

   The process exits non-zero if any requested page fails to build.
   The former ``--stations`` and ``--cast`` spellings still work as hidden,
   deprecated aliases for ``--casts`` and ``--only``; they emit a warning.

**Examples**::

   ctdcast report config.yaml                   # generate all enabled page types
   ctdcast report config.yaml --casts           # cast pages only
   ctdcast report config.yaml --only 42 --force # rebuild one cast page
   ctdcast report config.yaml --skip-existing   # fill any missing pages
   ctdcast report config.yaml --dry-run

----

ctdcast run
-------------

Run convert then report in one step (most common workflow).

.. code-block:: text

   ctdcast run <config> [options]

   positional arguments:
     config           Path to config.yaml

   options:
     --ctd            Also run CNV → netCDF conversion before building profiles
                      (requires data.cnv_dir in config)
     --only N [N ...] Rebuild only the pages for cast N (skips profiles step)
     --force          Force regeneration of all outputs regardless of modification times
     --skip-existing  Skip pages whose HTML already exists
     --dry-run        Print what would be done without writing any files

Equivalent to running ``ctdcast convert`` then ``ctdcast report`` in sequence.
``run`` is the recommended everyday command — it builds ``profiles.nc`` first, so it
works from a fresh checkout; use ``report`` when the profiles are already current and
you only want to regenerate specific pages.  (The former ``--cast`` spelling still
works as a deprecated alias for ``--only``.)

**Examples**::

   ctdcast run config.yaml                      # smart update (skips up-to-date pages)
   ctdcast run config.yaml --force              # rebuild everything
   ctdcast run config.yaml --only 42            # rebuild one cast page
   ctdcast run config.yaml --ctd --force        # full pipeline including CNV conversion
   ctdcast run config.yaml --dry-run
