.. _cli_reference:

=============
CLI reference
=============

All subcommands are available via the ``ctdcast`` entry point.
Run ``ctdcast <command> --help`` for the full flag list at any time.

----

ctdcast draft
---------------

Quick look: read CNV files (stage 1), compile ``profiles.nc``, and build the cast pages, index,
map, sensors and processing pages in one step.  No ``config.yaml`` required.  Section and time
series pages stay empty: they need a groupings file saying which casts belong together.

.. code-block:: text

   ctdcast draft <cnv_dir> [out_dir] [options]

   positional arguments:
     cnv_dir          Directory of raw SBE CNV files (required)
     out_dir          Output directory (default: ./ctd_draft/)

   options:
     --cruise ID      Cruise ID shown in the report header
                      (default: the files' cruise attribute, else UNKCRUISE)
     --ship NAME      Ship name shown in the report header
     --keep-nc DIR    Save converted netCDF files to DIR instead of discarding after the run
     --pattern GLOB   Filename glob selecting CNV files within cnv_dir (default: '*.cnv')
     --sal MIN MAX    Salinity range for plot trimming: records whose salinity
                      (ctd_salinity, else ctd_salinity_1) is outside it are left out
                      of the cast-page plots
     --trim-soak      Leave the surface soak and back-on-deck records out of the
                      cast-page plots, found as stage 2 finds them (last scan above
                      10 dbar before the descent, searched back 20 s; the deck from
                      the pressure of the last 20 s)
                      (both plotting filters only; the netCDF files are not changed)
     --force          Regenerate existing pages regardless of modification times
     --dry-run        Print what would be done without writing any files

Requires ``seasenselib`` for CNV conversion (``pip install "ctdcast[cnv]"``).

**Examples**::

   ctdcast draft /data/cnv/
   ctdcast draft /data/cnv/ ./out/ --cruise odb2026 --ship RRS_Discovery
   ctdcast draft /data/cnv/ --keep-nc ./nc_out/ --force
   ctdcast draft /data/cnv/ --dry-run

----

ctdcast inspect
-----------------

Render a data-inventory page for a **single** netCDF file — every variable with its
dimensions, units and attributes — or print a Sea-Bird CNV's processing steps (below).  No ``config.yaml`` required.  Useful for checking
what a stage actually wrote — which QC flags are present, whether an attribute
survived a stage, what the compiled product contains.

.. code-block:: text

   ctdcast inspect <nc_file> [options]

   positional arguments:
     nc_file          The netCDF file to inventory, or a .cnv

   options:
     -o, --out PATH   Output HTML path
                      (default: <nc_file stem>_inventory.html, beside the input)
     --title TEXT     Page title (default: the file name)

Unlike ``ctdcast clock``, which is cruise-scope and reads every stage-1 file, this
looks at one file and writes one page.

**Examples**::

   ctdcast inspect /data/ctd_nc/stage1/msm_142_1_001_stage1.nc
   ctdcast inspect /data/ctd_nc/profiles.nc -o profiles_inventory.html
   ctdcast inspect /data/ctd_nc/profiles.nc --title "MSM142 compiled product"

**A Sea-Bird CNV.**  Given a ``.cnv``, ``inspect`` reads the SBE Data Processing steps from
its header instead and prints the equivalent ``data_processing:`` block: the modules in the
order they ran, each with its parameters and ctdcast's variable names, ready to paste into
``config.yaml``.  Modules that are not ctdcast steps (``datcnv``, ``Derive``) are listed as
comments.  Nothing is written beside the CNV; with ``-o``, the block is also written as a page
with a copy button, followed by each module's fields as the header records them::

   ctdcast inspect /data/cnv_24Hz/mixsed2_017.cnv
   ctdcast inspect /data/cnv_24Hz/mixsed2_017.cnv -o mixsed2_017_processing.html

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
     --sections            Also write a template ctd_groupings.yaml
     --interactive         Prompt for all data paths and cruise metadata,
                           then offer to auto-detect sections/timeseries
     --auto-section        Re-run section/timeseries detection from an existing
                           config and write ctd_groupings_draft.yaml (an existing
                           draft is overwritten only with --force).  Reads
                           <ctd_root>/profiles.nc, or data.profiles_nc when set;
                           does not touch config.yaml.
     --force               Overwrite existing files

   detection thresholds (used only with --interactive or --auto-section; ignored otherwise):
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

Output is ``ctd_groupings_draft.yaml`` (alongside ``groupings_yaml`` from the
config, or in the config's directory).  Review and rename to
``ctd_groupings.yaml`` before use.

**Examples**::

   ctdcast init                          # write config.yaml in current directory
   ctdcast init /data/cruise/
   ctdcast init --sections               # also write a template ctd_groupings.yaml
   ctdcast init --interactive config.yaml --force   # guided setup with auto-detection
   ctdcast init --auto-section config.yaml --force  # re-detect sections only

----

ctdcast validate
------------------

Check a config and the files it names before the first run: the YAML, the output folder
(created if missing), the stage root and ``profiles.nc`` (warnings when absent), and the
groupings file.  It does not check the raw input folders (``hex_dir``, ``cnv_dir``,
``ladcp_dir``).

.. code-block:: text

   ctdcast validate <config> [options]

   positional arguments:
     config           Path to config.yaml

   options:
     --strict         Also check that every cast number the sections in
                      ctd_groupings.yaml name is present in ctd_root

**Examples**::

   ctdcast validate config.yaml
   ctdcast validate config.yaml --strict

----

ctdcast process
-----------------

Run one or more pipeline stages, across every configured data source.  A stage
runs for whichever sources are configured: with both CTD and LADCP paths set,
``--stage 1`` ingests both (``.hex`` or CNV → nc *and* ``.mat`` → nc) and ``--stage profiles``
compiles both (``profiles.nc`` *and* ``ladcp_profiles.nc``).  A source whose paths
are absent is silently skipped.

.. code-block:: text

   ctdcast process <config> --stage {1,2,3,profiles} [more] [options]

   positional arguments:
     config           Path to config.yaml

   required:
     --stage ...      One or more of: 1, 2, 3, profiles.  Multiple values run in
                      canonical order (1 → 2 → 3 → profiles) regardless of the
                      order given.

   options:
     --only N [N ...]  Restrict cast-scope stages (1, 2, 3) to these casts
     --force           Rebuild every stage file, even when it is up to date
     --dry-run         Print what would be done without writing any files
     --gebco NC        GEBCO netCDF for the water depth at each cast in profiles.nc
                       (data.gebco_nc is not read by this stage)
     --backend NAME    CNV reader (default: seasenselib); a hex_dir cruise reads .hex
     --pattern GLOB    Filename glob for CNV files (default: from config, else '*.cnv');
                       not used for .hex

   (The former ``--cast`` spelling still works as a deprecated alias for ``--only``.)

   stage 2 trim tuning (all optional; the defaults are the documented behaviour):
     --near-surface-dbar D    Pressure threshold for the last near-surface crossing
                              (default: 10 dbar)
     --search-seconds S       Backward-crawl window for the pre-descent surface minimum
                              (default: 20 s)
     --deck-window-seconds S  Tail window for the on-deck reference pressure estimate
                              (default: 20 s)
     --margin-dbar D          Added to the on-deck median to form the cut threshold
                              (default: 0.5 dbar)
     --max-deck-dbar D        If the on-deck median exceeds this, no end-trim is applied
                              (default: 20 dbar)

A trim flag overrides the corresponding ``processing.trim`` key in the config for that
run only; nothing is written back.  Use them to test a threshold before committing it
to the config.

Stage 1 reads the raw ``.hex`` or CNV files to per-cast netCDF; stage 2 flags the soak and
deck records and applies the clock block; stage 3 applies the conductivity slope and offset,
the ``data_processing`` steps, salinity, SBE 43 oxygen and QC, then makes the products (LADCP
has no stage 2 or 3); ``profiles`` compiles the per-cast files into the gridded files.  A stage
file is rebuilt only when it is missing or its input is newer.

**Examples**::

   ctdcast process config.yaml --stage 1                # ingest CTD + LADCP
   ctdcast process config.yaml --stage 1 2 3 profiles   # full pipeline
   ctdcast process config.yaml --stage profiles         # compile products only
   ctdcast process config.yaml --stage 1 --only 42      # re-ingest one cast

----

ctdcast convert (deprecated)
------------------------------

.. note::

   ``ctdcast convert`` is deprecated and will be removed in 0.5.0 — use
   ``ctdcast process --stage ...``.  ``convert --ctd`` → ``process --stage 1``;
   ``convert --profiles`` → ``process --stage profiles``; ``convert --ladcp`` →
   ``process --stage 1 profiles``.  The command still runs, with a notice, but it is not
   the same: on a config with only ``ctd_root`` (no ``data.profiles_nc``) it may do
   nothing, and ``--ctd`` does not stamp ``cruise_info`` or the sensor overrides.

Convert raw data to netCDF inputs without generating HTML.

.. code-block:: text

   ctdcast convert <config> [options]

   positional arguments:
     config           Path to config.yaml

   step selection (default: --profiles only if data.profiles_nc is configured):
     --ctd            Convert per-cast CNV files to netCDF (requires data.cnv_dir in config)
     --profiles       Compile per-cast netCDF files into profiles.nc
     --ladcp          Convert LADCP .mat files and compile ladcp_profiles.nc

   options:
     --backend NAME   CTD conversion backend (currently only 'seasenselib')
     --pattern GLOB   Filename glob for CNV files (default: '*.cnv'); --ctd only
     --only N         Convert only cast N (implies --ctd)
     --force          Overwrite existing output files
     --dry-run        Print what would be done without writing any files

   (The former ``--cast`` spelling still works as a deprecated alias for ``--only``.)

**Examples**::

   ctdcast convert config.yaml                  # build profiles.nc (default)
   ctdcast convert config.yaml --ctd            # CNV → nc (no profiles.nc)
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
     --sections       Generate section pages (requires profiles.nc and groupings_yaml)
     --timeseries     Generate timeseries pages (requires profiles.nc and groupings_yaml)
     --index          Generate the cruise-wide pages: index, casts, sections and
                      timeseries index pages, each compiled file's inventory, SBE
                      sensors, processing, and T/S corrections when fits.nc exists
     --map            Generate leaflet.html interactive map
     --all            Generate every page type

   options:
     --only N [N ...] Regenerate only these casts' pages (no other page type)
     --force          Regenerate all pages regardless of modification times
     --skip-existing  Skip pages whose HTML already exists (fill missing pages only)
     --dry-run        Print what would be done without writing any files

   plotting (affect the figures only; no netCDF file is modified):
     --sal MIN MAX    Salinity range for plot trimming: records whose salinity
                      (ctd_salinity, else ctd_salinity_1) is outside it are left out
                      of the cast-page plots
     --trim-soak      Leave the surface soak and back-on-deck records out of the
                      cast-page plots, found as stage 2 finds them (last scan above
                      10 dbar before the descent, searched back 20 s; the deck from
                      the pressure of the last 20 s)
     --dbar-step N    Plot every Nth dbar level from profiles.nc in section and
                      timeseries figures (default: 1, full resolution).  The
                      compiled product always stores 1 dbar; this thins the plot,
                      not the data
     --drop-stub      Drop cast-page sections whose figures all failed to render.
                      By default such a section stays visible as a warning, so a
                      failed figure is noticed rather than silently absent

   A page is rebuilt only when the files it is drawn from are newer, so ``--sal``,
   ``--trim-soak`` and ``--drop-stub`` change an up-to-date page only with ``--force``.
   A top-level ``force: true`` in the config does the same as ``--force``.
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

Run the processing pipeline then the reports in one step (most common workflow).

.. code-block:: text

   ctdcast run <config> [options]

   positional arguments:
     config           Path to config.yaml

   options:
     --stage ...      Stage(s) to run before reporting, across every configured
                      source (default: all — 1 2 3 profiles). E.g. --stage profiles
                      to only compile and report.
     --only N [N ...] Process only these cast(s): cast-scope stages (1 2 3) run for
                      them and only their pages rebuild; profiles is skipped
     --force          Force regeneration of all outputs regardless of modification times
     --skip-existing  Skip pages whose HTML already exists
     --dry-run        Print what would be done without writing any files
     --trim-soak      Leave the soak and deck records out of the cast-page plots (see
                      ``report --trim-soak``)

Runs ``ctdcast process --stage ...`` and then ``ctdcast report``.  ``run`` is the
recommended everyday command: by default it runs every stage (ingest → QC →
compile) across every configured source, then builds the HTML — so it works from
raw on a fresh checkout.  Narrow with ``--stage`` when you do not want the full
pipeline (``--stage profiles`` compiles and reports without re-ingesting raw).  Use
``report`` when the compiled products are already current and you only want to
regenerate pages.  (The former ``--cast`` spelling is a deprecated alias for
``--only``; the former ``--ctd`` flag is deprecated — ``run`` now ingests raw by
default.)

**Examples**::

   ctdcast run config.yaml                      # full pipeline (all stages) + reports
   ctdcast run config.yaml --stage profiles     # compile + report only (skip ingest)
   ctdcast run config.yaml --stage 1 profiles   # ingest + compile + report (skip QC)
   ctdcast run config.yaml --force              # rebuild everything
   ctdcast run config.yaml --only 42            # reprocess + rebuild one cast page
   ctdcast run config.yaml --dry-run

----

ctdcast clock
---------------

Diagnose the acquisition-clock error for a cruise.  Each SBE cast records two
clocks in its header — the acquisition PC's System clock and the GPS-derived NMEA
clock — and their difference is the offset by which the recorded ``time`` may be
wrong.  ``clock`` reads that pair off every stage-1 cast, classifies the cruise,
and prints a verdict, the coordinate-source line, a per-segment table, and a
paste-ready ``clock`` block.  It writes nothing — applying a correction
is a separate stage-2 step.

.. code-block:: text

   ctdcast clock <config> [options]

   positional arguments:
     config           Path to config.yaml (the CTD root is read from data.ctd_root)

   options:
     -f, --figure PNG Also write the offset-vs-cast figure to this path

The verdict is one of ``constant``, ``step`` (one row per level, a changepoint at
each boundary), ``drift`` (only when a rate positively fits — the note quotes
slope, R² and residual sd), ``no_clock_pair`` or ``insufficient``.  The
coordinate-source line is orthogonal to the verdict: a cruise can show a real
offset yet need no correction because its ``time`` coordinate was already anchored
to GPS.  The suggested block is shown only when the coordinate is on the System
clock, and its sign is emitted as a comment so it is copied, never hand-computed.

**Examples**::

   ctdcast clock config.yaml                       # print the verdict + suggested config
   ctdcast clock config.yaml --figure clock.png    # also write the offset-vs-cast figure

----

ctdcast fit
-------------

Suggest conductivity-alignment and cell-thermal-mass parameters for a cruise.  ``fit`` reads every
native-rate stage-2 cast, scores each conductivity line's salinity-spike cost (alignment) and
down/up salinity-mismatch cost (cell thermal mass), writes the per-cast cost surfaces to
``<ctd_root>/fits.nc``, and prints a paste-ready ``data_processing:`` block with the recommended
``alignctd`` and ``celltm`` values.  It writes no stage file — the values reach stage 3 only when
you paste them into the config.  ``ctdcast report`` draws the *T/S corrections* page from
``fits.nc``.

.. code-block:: text

   ctdcast fit <config> [options]

   positional arguments:
     config               Path to config.yaml (the CTD root is read from data.ctd_root, or data.nc_dir)

   options:
     --only N [N ...]     Fit only these cast number(s)
     --dry-run            List the casts that would be fitted, write nothing

The recommended ``(alpha, tau)`` is the grid point within ``fit.ctm_tolerance`` (default
2%) of the cost minimum closest to Sea-Bird's default (0.03, 7 s); any value within the tolerance is
equivalent.  A cast at a non-native scan rate, or one Sea-Bird already aligned or ran cell thermal
mass on, is reported as not fitted and left out.  Tune the finder (cost windows, tolerance, block
size) with the ``fit`` block (see :ref:`config_yaml`).

**Examples**::

   ctdcast fit config.yaml                         # print the suggested data_processing: block
   ctdcast fit config.yaml --only 11 12            # just two casts
   ctdcast fit config.yaml --dry-run               # list what would be fitted

----

ctdcast list
--------------

Show what the institution, platform and role registries hold, so you do not have to
open a YAML file inside ``site-packages`` to find a slug.

.. code-block:: text

   ctdcast list {institutions|platforms|roles} [CONFIG] [options]

   positional arguments:
     registry         Which registry to list; omit to see the three names.
     config           Optional config.yaml — also shows what this cruise adds.

   options:
     --search TEXT    Case-insensitive filter across slug and name.
     --vocabulary N   For `roles`: show one vocabulary only (C89, G04, C59, W08).

Give a ``CONFIG`` to see what *your* cruise adds on top of the shipped defaults: a
``cruise_info.institutions_file`` and inline ``cruise_info.institutions`` entries, and an
inline ``cruise_info.platform`` vessel.  The ``Source`` column says where each entry came
from (``packaged``, ``user``, the config file, or ``inline``), so you can tell "my entry did
not load" from "you did not give me a config".  ``list platforms`` also prints the
``ambiguous_slugs`` and ``forbidden_codes`` traps with the reason each is refused; ``list
roles`` groups the four vocabularies by axis (person vs institution) and marks each axis's
default.

**Examples**::

   ctdcast list                              # the three registries
   ctdcast list institutions config.yaml     # shipped + user + this config's entries
   ctdcast list platforms --search meteor    # filter by slug or name
   ctdcast list roles --vocabulary W08        # one vocabulary
