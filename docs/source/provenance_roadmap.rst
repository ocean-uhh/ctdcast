Provenance roadmap
==================

ctdcast is the first of three packages in one chain: ctdcast processes CTD casts to
per-stage netCDF; `caldip <https://github.com/ocean-uhh/caldip>`_ compares mooring
instruments against a ctdcast CTD file at calibration-dip bottle stops;
`oceanarray <https://github.com/ocean-uhh/oceanarray>`_ applies the resulting offsets to
mooring instruments. This page records how provenance travels along that chain, what is
implemented, and what is planned.

Status labels: **done** — in the released or merged code; **in progress** — being built;
**planned** — designed and agreed, not yet built.

The principle
-------------

Two rules shape every decision below.

**A file must be interpretable on its own.** Given one output file, a reader should be able to
recover which input produced it, what was done to it, and with which parameters — without a
directory listing, a configuration file, or a conversation.

**Each fact is recorded once, by the package that first observes it, and passed through
unchanged.** ctdcast observes the CTD's sensors and identity; caldip observes which of them it
used as reference and the comparison itself; oceanarray consumes and records what it applied.
A package that re-derives a fact another already recorded is duplicating, not validating —
and shared facts keep the same attribute names the whole way down, so no consumer needs a
translation layer.

File identity and lineage — done
--------------------------------

Every file ctdcast writes carries a ``tracking_id`` (UUID4, ACDD/OceanSITES convention),
fresh on every write, and from stage 2 onward a ``source_tracking_id`` naming the file it was
made from. Stage 1 records the raw file instead, since it has no upstream netCDF:
``source_cnv`` for a CNV cast, ``source_hex`` and ``source_xmlcon`` for a ``.hex`` cast,
``source_mat`` for LADCP. ``profiles.nc`` carries ``source_tracking_id`` per
profile alongside ``source_file``.

``tracking_id`` answers *which instance of this file this is* — it is deliberately **not** a
content hash, and it changes even when a re-run produces identical values. Comparing
``tracking_id`` tells you the file was rewritten; comparing the recorded processing parameters
tells you whether anything actually moved.

A cross-stage test asserts that the sensor catalog, the raw instrument header, the cruise and
cast identity and the lineage attributes all survive stage 1 → 2 → 3. It runs on the
canonical Linux job, where the CNV reader is installed; it is skipped on the other test-matrix
cells, so an operating-system-specific fault in the conversion path is not covered by it.

Cross-package discovery — done
------------------------------

``ctdcast.select_best_available`` is the supported entry point for other packages: it returns,
per cast, the best-available stage file and which stage it came from. It exists so downstream
packages do not reimplement the stage-3-else-2-else-1 precedence, which would drift the first
time a stage is added.

Processing state — done
-----------------------

Two OceanSITES fields, rather than bespoke ones.

``data_mode`` (reference table 4) says whether a file is the product of record. It is on
every file — the per-cast stage files as well as the compiled products — so a consumer that
reads a stage file through ``select_best_available`` (caldip does) sees the mode without
opening ``profiles.nc``. The default is ``P`` provisional; ``D`` delayed-mode is a claim that
all calibrations and quality control have been applied, so it is **declared** in the config
(``cruise_info.data_mode: D``), never inferred — and a ``D`` declared on a cast where no
calibration was applied (none of its variables carries the calibration ``processing_level``)
warns and names the cast. Quick-look output (``ctdcast draft``) is ``P`` regardless of
configuration.

``processing_level`` (reference table 3) says what has been done, **per variable**, using that
table's wording. The stage-1 conversion value is stamped on every measured channel — the ones
that map to a sensor in the CNV ``<Sensors>`` block or the ``.xmlcon`` — and on no computed channel, since
salinity, density and the rest were derived from already-converted inputs and were never
instrument data. Later procedures append their own values: range-flagging at stages 2 and 3,
and calibration at stage 3, which propagates to re-derived salinity. Several values can apply
to one variable at once, so they are joined with ``"; "`` in the order applied, as an ordered
set — re-running a stage never duplicates a value — which makes the attribute double as the
per-variable sequence. No value in that table describes a clock correction, so the time
coordinate does not claim one; the shift is recorded in ``history``, in the clock-offset
variable and in the retained original time coordinate.

Note that ``processing_level`` names a *procedure that was applied*, not a guarantee about the
data. "Ranges applied, bad data flagged" means a range test ran and its failures were flagged;
the thresholds it used are recorded on the flag variables, which is what makes the scope of the
claim checkable.

Mixed processing states — done
------------------------------

Compiling casts that sit at different stages is permitted: re-running two casts to check a
change should not mean re-processing a cruise. Two kinds of heterogeneity are kept distinct,
because stage is not data mode:

- **Mixed stages.** Casts compiled from different stages warn loudly, naming every cast and
  its stage; the per-profile ``source_stage`` already carries the fact. Stages 1, 2 and 3 are
  all provisional, so this does **not** make the file ``M`` — an all-provisional compile is
  ``data_mode = "P"``.
- **Mixed data modes.** ``data_mode = "M"`` appears only when the casts genuinely differ (a
  declared ``D`` compiled alongside ``P`` ones). ``M`` then triggers the manual's obligation
  to say which data is in which mode, satisfied by a per-``N_PROF`` ``source_data_mode``
  variable read from each cast's own attribute.

Sensor calibration coefficients — done
---------------------------------------

Each sensor's complete configuration block, with every calibration coefficient, is carried on
its catalog entry (``sensor_config_xml``) into ``profiles.nc``, so the raw-to-physical
conversion is reconstructable from the compiled file alone (see :doc:`data_files`).

Processing record — done
------------------------

Every step applied to a cast — stage 1, the Sea-Bird steps in the raw header, stage 2, stage
3 and the products — is compiled into ``profiles.nc`` as a per-cast ``processing_record``,
with the setting kept apart from what the step did on that cast; ``processing.html`` shows it
by run of casts.

Known limits
------------

**Stage 3 calibrates conductivity only.** It applies a per-sensor conductivity slope and
offset (``data_processing.slope_offset``); there is no temperature or pressure correction. A
downstream package's temperature reference therefore cannot be corrected by ctdcast as it
stands, whichever stage it reads. Any check that enumerates ctdcast's correction fields is
complete only until another correction is added.

**Calibration-dip integration is not yet implemented in either direction.** caldip's
machine-readable output is moving to one netCDF per cast, with the statistics CSV retained as a
derived export for cruise reports; oceanarray then applies those corrections at the front of
its stage 3. Until that lands, corrections determined from calibration dips are not applied
automatically anywhere in the chain.
