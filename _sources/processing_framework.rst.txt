.. _processing_framework:

============================
ctdcast processing framework
============================

This page describes **what each processing stage does and why**, as distinct from
:doc:`cli_reference`, which describes how to invoke them. It is the ctdcast
counterpart to oceanarray's processing framework: where oceanarray moves
instrument → mooring → array, ctdcast moves **cast → cruise**.

Those two levels are not an informal grouping — they are the ``scope`` field on
every row of the stage registry (``ctdcast.processors.STAGES``), which is the
single source of truth for execution order, the ``--stage`` choices, and the
re-run rule. A ``"cast"`` stage runs once per cast; a ``"cruise"`` stage runs once
per compiled product.

**Principles**

- **Modular** — each stage has defined inputs and outputs, and one job.
- **Cruise-ready** — usable for quick-look processing at sea, with enough
  structure to carry into scientific analysis afterwards.
- **Reproducible** — every transformation records itself in ``history`` with the
  parameters it used, not merely its name.
- **Incremental** — a stage's output is storable and reloadable, so processing can
  stop and resume rather than being one long run.

Output files use CF-netCDF conventions with ACDD discovery metadata; the compiled
products additionally carry an ``expocode`` coordinate in the CCHDO manner.

----

The stage ladder
----------------

Two rules govern what may be a *stage* rather than a *product*:

**Monotone in corrections.** Each stage adds information — flags, calibrations,
derived variables — and removes none. Stage 2 marks the soak; it does not delete
those scans. This is why a later stage can always be re-run from an earlier one,
and why the lineage on disk is meaningful rather than lossy.

A sharper form of the same rule is worth stating, because it says exactly where
in the ladder numbers start moving: **stages 1 and 2 change no measured value.**
Stage 1 renames and normalises units; stage 2 selects and flags. Neither alters a
temperature, a conductivity or a pressure. **Stage 3 is the first rung where a
measured value changes** — calibration adjusts conductivity, and salinity is
re-derived from it. (Trimming a moored record does shift the ``time`` *coordinate*
under a clock correction, which is why the rule is about measured values rather
than about all numbers.) So a disagreement between two people's stage-2 output is
a disagreement about *selection*; a disagreement at stage 3 is a disagreement
about *calibration*, and the two are diagnosed differently.

**Constant in representation.** A stage leaves the sampling representation
untouched: same scans, same vertical axis. Anything that *changes* the
representation — binning to a pressure grid, splitting into downcast and upcast
halves, stacking casts into one array — is a **terminal product**, not a rung.

**Parameters are found outside the ladder and applied inside it.** A stage never
derives its own correction coefficients. For ctdcast they come from two places:

- the **conductivity slope**, from comparing CTD conductivity against **bottle
  salinities** analysed from the rosette samples;
- the **align lags** and **cell-thermal-mass coefficients**, from finder tools
  that use nothing but the CTD data itself.

Both are recorded in config and *applied* at stage 3. oceanarray does the same
thing one rung earlier: a clock offset is *found* by comparing the computer and
instrument clocks at recovery, recorded in YAML as
``computer_clock_at_recovery`` / ``instrument_clock_at_recovery``, and *applied*
at its stage 2. (Calibration-dip processing —
`caldip <https://github.com/ocean-uhh/caldip>`_ — is oceanarray's route for moored
instruments, and is not part of the CTD workflow.)

The align and cell-thermal-mass finders are the interesting case, because they
read the very data the stage is processing — so why not derive them inside the
stage? Three reasons the separation is structural rather than incidental:

- **the scopes differ.** A finder examines *many casts* to settle one coefficient
  for the cruise; the applier then uses it on *one cast*. A cast-scope stage
  cannot see what a cruise-scope determination needs;
- **judgement.** The result is inspected and chosen, once, not re-decided
  silently on every run;
- **reproducibility.** A stage that re-derived its own parameters could give a
  different answer from the same input as the surrounding casts change, which is
  exactly what the ladder exists to prevent.

The slope has a fourth, simpler reason: bottle salinities are analysed data the
stage has never seen.

That second rule is what makes ``profiles.nc`` a product rather than "stage 4".
It grids to 1 dbar and splits each cast into two profiles, so it cannot be an
input to further per-cast processing. Terminal products sit beside the stage
directories, not inside them.

----

Cast-level processing
---------------------

One cast in, one cast out, once per cast.

- **Stage 0 (planned):** acquire and convert raw instrument files — hex → CNV for
  Sea-Bird CTDs. Not implemented in ctdcast; today ctdcast starts from calibrated
  CNV. **This is what** `ctdam <https://github.com/ocean-uhh/ctdam>`_ **does**: it
  drives the Sea-Bird processing chain (``wildedit``, ``wfilter``, ``alignctd``,
  ``celltm``, bottle-file creation, gsw derivations) from a ``proc_template.toml``
  and writes CNV. Stage 0 is therefore a *boundary* with a sibling package rather
  than a module to be written here.

  .. important::

     **What arrives at stage 1 is not raw.** ctdam's chain does two different
     kinds of work. ``datcnv`` is conversion — hex to engineering units — which is
     stage-0/1 work. But ``wildedit`` (despike), ``wfilter`` (median filter),
     ``filter`` (low-pass), ``alignctd`` (sensor time alignment) and ``celltm``
     (cell thermal mass) all **change measured values**, which by the ladder's
     second invariant makes them **stage-3-class corrections applied upstream**,
     with per-variable parameters recorded only in the CNV header::

         # wfilter_action t090C = median, 10
         # filter_low_pass_tc_A = 0.030
         # filter_low_pass_A_vars = altM flECO-AFL turbWETntu0 …

     Two consequences follow, and both matter more than the provenance:

     - **Re-run scope is asymmetric.** Changing a ctdcast stage-3 parameter
       invalidates stage 3. Changing a *ctdam* parameter regenerates the CNV and
       invalidates the ctdcast ladder **from stage 1**, because the corrections
       sit below it. That is the practical cost of these steps living outside the
       framework.
     - **Stage 3 must know what was already done.** Applying a cell-thermal-mass
       correction or a time alignment twice is a silent error that produces
       plausible numbers. Stage 3 reading the upstream chain is a safety check,
       not only a record.

     The longer-term shape is to express these as ctdcast stage-3 modules with
     their parameters in ctdcast's config, ingesting unfiltered ``datcnv`` output
     — one place for the parameters, and re-runnable within the ladder.
     Importantly this needs **no file round-trip**: ctdam is a Python library
     whose appliers (``AlignCTD``, ``WFilter``, ``CellTM``, ``LoopRemoval``)
     accept and return an in-memory ``CTDData``, so ctdcast would call them
     directly rather than exporting CNV, invoking a tool, and re-reading. The
     cost is an xarray ↔ ``CTDData`` adapter, not an export/import cycle. Not a
     near-term change; noted so the current arrangement is understood as a
     boundary compromise rather than the design.

  .. important::

     **The boundary contract: ctdam runs without ``binavg`` and without
     ``downcast_only``.** Both are legitimate in ctdam's own terms, but a CNV
     produced with either is **already a terminal product** by this framework's
     second rule — ctdcast would be splitting downcast from upcast on a file that
     has neither, or re-binning binned data. Those two jobs belong to stage 2 and
     to the ``profiles`` compile, where they are reversible and recorded. A CNV
     arriving at stage 1 carries every scan of the full cast.
- **Stage 1 — standardisation.** Convert raw CNV to CF-netCDF, faithfully: no
  trimming and no QC. Canonical variable names, unit normalisation (conductivity
  to mS/cm, pressure to dbar), and single-sensor renaming — ``ctd_temperature_1``
  becomes ``ctd_temperature`` when there is no second sensor to distinguish it
  from. The backend is pluggable (``CtdBackend``); ``seasenselib`` is the current
  implementation.
- **Stage 2 — trim.** Decide which scans belong to the real cast: downcast/upcast
  splitting, soak detection at the start, back-on-deck detection at the end. This
  is the profile analogue of trimming a moored record to its deployment window —
  same rung, same question, different domain (see the note below).
  QARTOD flag 4 is set on soak and post-recovery records — **marked, not deleted**,
  per the monotonicity rule — and the detection parameters are recorded in
  ``history``.
- **Stage 3 — QC and calibration.** Gross-range QC, then any conductivity
  calibration named in the cruise config, then salinity re-derived from the
  calibrated conductivity. Deliberately **iterative**: re-run it as calibration
  improves, which is why it must not consume its own output.

LADCP has a single cast-level stage: the LDEO ``.mat`` solution is converted to
per-cast netCDF. Its upstream processing happens outside ctdcast.

----

Cruise-level processing
-----------------------

Many casts in, one file out, once per product.

- **profiles** — compile the per-cast files into ``profiles.nc``: each cast split
  into downcast and upcast, binned to a common pressure grid, and stacked on an
  ``N_PROF`` dimension. The pressure coordinate is the **bin centre**, so a binned
  value sits at the mean depth of the samples it averages.
- **ladcp_profiles** — the LADCP equivalent, gridded on depth in metres rather
  than pressure.

Both carry the cruise-level metadata: ACDD discovery fields, contributors and
institutions with their controlled-vocabulary roles, licence and embargo, derived
spatiotemporal coverage, and the ``expocode`` coordinate.

----

Summary table
-------------

.. list-table::
   :header-rows: 1

   * - Step
     - Scope
     - Name
     - Description
   * - 0
     - cast
     - Acquisition (planned)
     - Raw instrument files to CNV
   * - 1
     - cast
     - Standardisation
     - CNV to CF-netCDF; canonical names and units; values preserved as-is
   * - 2
     - cast
     - Trim
     - Downcast/upcast split; soak and back-on-deck flagged (not removed)
   * - 3
     - cast
     - QC and calibration
     - Gross-range QC; conductivity calibration; salinity re-derived
   * - profiles
     - cruise
     - Compile (CTD)
     - Bin to a pressure grid, stack on ``N_PROF``, attach cruise metadata
   * - profiles
     - cruise
     - Compile (LADCP)
     - As above, gridded on depth

.. note::

   **The rungs line up with oceanarray's**, which processes moored time series
   rather than profiles:

   .. list-table::
      :header-rows: 1

      * - Stage
        - Both packages
        - ctdcast (a profile)
        - oceanarray (a moored record)
      * - 1
        - Standardisation — raw to CF-netCDF, values preserved
        - CNV to netCDF
        - ``.cnv``/``.rsk``/``.aqd`` to netCDF
      * - 2
        - **Trim** — decide which records belong to the real measurement
        - soak and back-on-deck
        - deployment window, plus clock offset/drift
      * - 3
        - QC and derived variables
        - gross-range QC, conductivity calibration, salinity
        - QARTOD QC, pressure interpolation, salinity, velocity rotation

   The alignment is not a coincidence of numbering: each rung is a *kind* of
   transformation, so the same three appear whether the thing being processed is
   a cast or a mooring record. What differs is the domain — a cast's "real
   measurement" begins after the soak, a mooring's after deployment — and
   therefore the specific operations, not the intent of the rung.

   What genuinely does not transfer is the level above: oceanarray continues to
   mooring- and array-level steps (stack, grid, concatenate, boundary merge)
   where ctdcast has a single cruise level.
