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
products additionally carry an ``expocode`` variable over ``N_PROF``, in the CCHDO
manner. It is a variable rather than a coordinate: it names the one cruise every
profile already belongs to, so it indexes nothing.

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

Before the ladder: what the file already carries
------------------------------------------------

ctdcast does not receive raw measurements. A Sea-Bird CNV has usually been through
two rounds of processing before ctdcast opens it, and **neither of them announces
itself in a way the ladder can see**:

- the **deck unit**, at acquisition, in hardware;
- **SBE Data Processing**, ashore or at sea, as a chain of modules.

Both are recorded in the CNV header, in two different namespaces:

.. list-table::
   :header-rows: 1
   :widths: 16 44 40

   * - Lines
     - What they hold
     - Example

   * - ``*``
     - Seasave and deck-unit acquisition settings — **including the conductivity
       time alignment**, the system/NMEA clock pair, and the scan-averaging factor
     - ``* advance primary conductivity  0.073 seconds``

   * - ``* <Sensors>``
     - Sensor serials and calibration coefficients (kept verbatim as
       ``raw_metadata``)
     - ``* <sensor Channel="1" >``

   * - ``#``
     - The SBE Data Processing module chain, in execution order, with the
       parameters each module used
     - ``# celltm_alpha = 0.0300, 0.0300``

   * - ``**``
     - Free-text user header written on the ship
     - ``**  Station:  004``

Why the ``*`` block matters more than it looks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The SBE 11plus deck unit is factory-set to advance primary conductivity by 1.75
scans — at 24 Hz, 0.073 s — which is exactly the typical lag of conductivity behind
temperature for a 9plus with a TC duct and a 3000 rpm pump. The Sea-Bird manual is
explicit that this *"eliminates the need to run Align CTD"*.

So a cast whose ``#`` chain shows no ``alignctd`` module may nonetheless be fully
aligned. Applying an alignment on top of it does not fail loudly — it produces
plausible, wrong numbers. This is the reason ctdcast reads the header at all, and
the reason a stage may never assume that a correction absent from the module chain
was not applied.

Two consequences follow for the alignment specifically:

- **The 0.073 s figure is a configuration value, not a constant.** The lag is
  dominated by water transit through the pumped plumbing, so a faster pump or a
  shorter tube shortens it. This is why the align lag is *found* from the data
  (see the ladder rules above) rather than read from a table — the table value is
  the fallback and the sanity bound.
- **The advance is recorded per channel**, and older deck units do not always set
  the two conductivity channels alike. Where they differ, the secondary channel
  carries a residual the primary does not, and salinity computed from it will
  show spiking the primary does not.

The correction ledger
~~~~~~~~~~~~~~~~~~~~~

Stage 1 parses both namespaces and records what it finds as a **ledger** of
corrections already applied — see :ref:`data_files` for the attributes. The unit of
record is the *correction* rather than the module, because the most consequential
one — the deck-unit alignment — is not a module and lives in the other namespace
entirely. Every module in the chain then contributes an entry of its own, and the
order they ran in is recorded explicitly, since the deck-unit alignment carries no
timestamp and some writers give their modules none either.

The ledger is read, never merged. Config states what ctdcast *intends*; the header
states what is *already irreversibly true*. A later stage reconciles the two and
declines to act where they conflict — it does not combine them into one effective
parameter set, which would let a config value look applied when it was not. In
practice that means a stage **skips** work already done upstream rather than doing
it and undoing it later, which is also what keeps the QC flags monotone.

Where a file enters the ladder
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``binavg`` module is the one that decides this, and its ``bintype`` matters
more than its size:

- ``bintype = seconds`` — the file is still a time series, decimated. It enters at
  stage 1 and the whole ladder applies.
- ``bintype = decibars`` — the file has already been gridded onto a pressure axis.
  Its sampling representation has changed, which by the second ladder rule makes it
  a **terminal product** rather than a rung. Time-domain corrections cannot be
  applied to it: Sea-Bird states plainly that Align CTD *"cannot be run on files
  that have been averaged into pressure or depth bins"*, and Loop Edit needs three
  successive scans to compute velocity, which a 1 dbar grid has destroyed.

ctdcast still reports on such a file — it simply cannot offer it the corrections
that require a time axis, and says so rather than pretending.

Sea-Bird's own recommendation, for comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ledger says what *was* done. To judge whether that is ordinary, the useful
comparison is against Sea-Bird's **published recommendation for the instrument** —
short, specific and citable, where a list of everything *not* done would be
unbounded and mostly uninteresting. For an SBE 9plus with a TC duct and a 3000 rpm
pump (manual rev 7.26.8):

.. list-table::
   :header-rows: 1
   :widths: 26 34 40

   * - Module
     - Recommended for a 9plus
     - Reference

   * - Sequence
     - Data Conversion → Filter → Align CTD → Cell Thermal Mass → Loop Edit →
       Derive → Bin Average. Wild Edit is deliberately absent and may run at any
       point.
     - p.20

   * - Filter
     - pressure **0.15 s**; temperature and conductivity **not filtered** (the
       table gives no value for a 9plus). The pressure constant is four times the
       scan interval, and exists to feed Loop Edit.
     - p.100

   * - Align CTD
     - temperature **0**; conductivity **0**, because the deck unit already
       advances it; oxygen **+2 to +5 s** for an SBE 43.
     - pp.84–86

   * - Cell Thermal Mass
     - alpha **0.03**, 1/beta **7.0**
     - p.92

A departure is **not an error.** Sea-Bird gives these as *typical* values and says
plainly that judgement is required — a different pump, a different duct, or a
deliberate choice all produce legitimate departures. What the table is good for is
reading a cast's provenance by hand: it tells you which of the values in front of
you are the usual ones, and which were chosen.

Two limits are worth knowing when using it that way. The recommendation is
**instrument-specific** — a 19plus or a 25 has different values — so it applies
only once the header has identified the instrument. And it says nothing about
Window Filter: smoothing temperature and conductivity with ``wfilter`` instead of
``filter`` is a legitimate alternative the manual neither recommends nor warns
against.

A worked example
~~~~~~~~~~~~~~~~

Upstream pipelines commonly **fork**, and which prong ctdcast is pointed at
determines what work is left to do. A typical shipboard chain runs
``datcnv → wildedit → filter → celltm → Derive`` at full rate, then splits:

- one prong bin-averages to **1 second** — still a time series, all casts;
- the other splits into downcast and upcast, runs **Loop Edit**, then bin-averages
  to **1 dbar**.

Pointed at the first prong, ctdcast receives a file that has *not* been loop-edited,
so ship-heave reversals are still present and its own compiled product will carry
them unless it removes them itself. Pointed at the second, it receives a finished
gridded product and its ladder has nothing left to add. Neither is wrong — but the
difference is invisible without reading the header, which is the point.

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
