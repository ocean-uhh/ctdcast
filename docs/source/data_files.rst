.. _data_files:

===================
Data files (netCDF)
===================

Layout
~~~~~~

Each instrument has one **root** that ctdcast owns — ``ctd_root`` and
``ladcp_root`` in the config's ``data:`` block. Inside it, one directory per
processing stage, the products, and the compiled file at the top:

.. code-block:: text

   <ctd_root>/
       stage1/  mixsed2_017_stage1.nc     the raw .hex or .cnv read to netCDF
       stage2/  mixsed2_017_stage2.nc     + soak / back-on-deck flags
       stage3/  mixsed2_017_stage3.nc     + Sea-Bird's steps, calibration and QC
       products/<name>/  mixsed2_017_<name>.nc   made from stage 3 (e.g. 1 dbar downcast)
       profiles.nc                        the casts compiled on a pressure grid

   <ladcp_root>/
       stage1/  ladcp_017_stage1.nc       LADCP has one stage
       ladcp_profiles.nc

Stages are **non-destructive**: each reads its predecessor and writes a new file,
so a stage can be re-run without redoing the ones before it, and the full lineage
stays on disk. See :doc:`processing_framework` for what each stage does.

**Stage 1 is faithful; stage 2 is curated.** Stage 1 is a faithful translation —
*every* column in the CNV, or every channel in the ``.hex``, reaches the stage-1 file,
dropping nothing. SeaBird-computed
quantities (density, depth, sound velocity, ``timeJ``/``timeS``, the per-scan flag,
oxygen saturation) are kept under an ``sbe_`` prefix so they cannot be mistaken for
ctdcast's own (ctdcast writes ``sigma0`` via TEOS-10, not SBE density); an unrecognised
channel is kept under its source name and warned about once per cast (so a rig with an
unmodelled channel warns on every cast until a ``VARIABLES`` entry is added). Stage 2 then removes the
``sbe_`` set by default — the drop is deliberate and recorded (a ``history`` line and a
``dropped_channels`` attribute), driven by the config ``trim.drop_sbe:`` list rather than a
flag so the output is reproducible from the config alone. Stage-2 output is therefore not a
strict superset of stage 1: the stage-1 file is the faithful record, and every drop is written
down (a ``history`` line and the ``dropped_channels`` attribute) so a removed channel is always
traceable to the stage-1 file that still holds it.

The stage appears in the **directory and the filename**. The redundancy is
deliberate: a file copied out of ``stage2/`` still says what it is, whereas
provenance living only in the path is lost the first time someone moves a file.
For that reason ``parse_stage`` reads the suffix from the filename and does not
trust the parent directory.

.. note::

   A directory of **unsuffixed** per-cast files, written before the stage layout
   existed, is still read — as stage 1. Point ``ctd_root`` at it and nothing
   needs regenerating.

Best-available selection
~~~~~~~~~~~~~~~~~~~~~~~~

Anything *reading* per-cast files — ``build_profiles``, the report — takes the
highest stage present for each cast: stage 3 if it exists, else stage 2, else
stage 1. So a cruise part-way through processing compiles honestly rather than
failing, and casts may legitimately sit at different stages.

Anything *writing* is stricter: a stage reads **only** its immediate predecessor
(stage 3 from stage 2, never from stage 1). A missing predecessor skips that cast
with a warning. The asymmetry is deliberate — ``mixsed2_017_stage3.nc`` must mean
one thing, and if stage 3 could silently consume stage 1 the same filename would
sometimes mean "QC'd, soak flagged" and sometimes "QC'd, not soak flagged".

Cast identity is the ``(number, suffix)`` pair, so ``017`` and ``017b`` are
distinct events rather than one cast listed twice.

Per-cast files
~~~~~~~~~~~~~~

Each file covers one CTD cast.  The required dimension and variables are:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Name
     - Description
   * - ``time`` (dim)
     - Time coordinate (1-D, one value per scan).
   * - ``pressure``
     - Sea pressure in dbar.
   * - ``ctd_temperature`` / ``ctd_temperature_1`` / ``ctd_temperature_2``
     - In-situ temperature in °C (ITS-90). Plain name for single-sensor instruments; ``_1``/``_2`` suffix for dual-sensor rigs.
   * - ``ctd_salinity`` / ``ctd_salinity_1`` / ``ctd_salinity_2``
     - Practical salinity (PSS-78), derived by ctdcast from C, T and P with TEOS-10.  Stored
       with ``units: "1"``, as CF writes a dimensionless quantity.
   * - ``ctd_oxygen`` / ``ctd_oxygen_1`` / ``ctd_oxygen_2``
     - Dissolved oxygen in µmol kg⁻¹.
   * - ``ctd_fluor``
     - Fluorescence in mg m⁻³ (chlorophyll-a equivalent; 1 mg m⁻³ = 1 µg L⁻¹).
   * - ``ctd_turbidity``
     - Turbidity, in NTU by the sensor's calibration; stored with ``units: "1"``, as CF has no
       NTU unit.
   * - ``ctd_altimeter``
     - Altimeter distance to seafloor in m.
   * - ``conductivity_1`` / ``conductivity_2``
     - Electrical conductivity in mS cm⁻¹ (no CCHDO equivalent; keeps ``_1``/``_2`` suffix always).
   * - ``transmissometer``
     - Beam transmittance in % (WET Labs C-Star; no CCHDO equivalent).
   * - ``par``
     - Photosynthetically active radiation in µmol photons m⁻² s⁻¹ (Biospherical/Licor/Chelsea).
   * - ``spar``
     - Surface PAR in µmol photons m⁻² s⁻¹ (deck-mounted reference sensor).
   * - ``volt{N}_raw``
     - Raw voltage (V) for sensors whose conversion is not implemented (e.g. pH) or whose calibration coefficients are absent. ``N`` is the zero-based voltage channel index. A cast read from ``.hex`` keeps every voltage channel this way, converted or not.
   * - ``oxygen_raw_1`` / ``oxygen_raw_2``
     - Raw SBE 43 oxygen sensor voltage (V); the input stage 3 derives ``ctd_oxygen`` from.
   * - ``sbe_oxygen_1`` / ``sbe_oxygen_2``
     - ``.hex`` casts only: quick-look SBE 43 oxygen in µmol kg⁻¹, converted at read time by ctdcast with Sea-Bird's ``seabirdscientific`` toolkit (uncorrected T/S, no tau or hysteresis correction). Dropped at stage 2 with the other ``sbe_`` channels.
   * - ``pump_status``, ``bottom_contact_status``, ``bottle_confirm_status``, ``modem_status``, ``data_integrity``
     - ``.hex`` casts only: the SBE 911plus deck unit's per-scan status bits and data-integrity counter. Neither these nor the ``volt{N}_raw`` channels get a ``_qc`` flag at stage 2: they are not measurements a flag could describe. ``oxygen_raw_N`` does, as stage 3 derives oxygen from it.
   * - ``<var>_qc``
     - From stage 2: the QARTOD flag of each measurement, ``int8``, ``flag_values`` 1 2 3 4 9
       (pass, not evaluated, suspect, fail, missing) with ``conventions: QARTOD``.  Stage 3
       records each test's thresholds on the flag variable (``qc_gross_range_suspect_min``,
       ``qc_spike_fail_threshold``, …).  A flagged value is kept; the flag says what is wrong
       with it.
   * - ``loop_edit_flag``
     - Stage 3, when ``loopedit`` runs: ``1`` on a scan Loop Edit marked (a pressure reversal,
       too slow, or the surface soak), with the parameters (``loop_edit``) and, on a cast that
       ran without the soak test, why (``loop_edit_soak_not_applied``).  The same scans are
       flagged 4 in every ``_qc``.

A cast read from ``.hex`` is at the native scan rate (24 Hz on a 911plus), with no
Sea-Bird processing applied; its conductivity, temperature and pressure carry the
``.xmlcon`` Slope and Offset they were converted with (``xmlcon_slope``,
``xmlcon_offset``) and the conversion function (``conversion_method``).

Each stage-3 step records what it did on the variables it changed: Wild Edit
(``wild_edit``, ``wild_edit_marked``, …), filters (``filters``), alignment
(``alignment_offset_seconds``, …), cell thermal mass (``cell_thermal_mass_alpha``,
``cell_thermal_mass_tau_seconds``, ``cell_thermal_mass_temperature``, …), the SBE 43 oxygen
derivation (``oxygen_tau_window_seconds``, ``oxygen_hysteresis_method``, …), each with the
function that applied it (``*_method``).  The processing record and the report pages are
built from these attributes and ``history``.

Storage dtypes, in every file ctdcast writes: science values ``float32`` (about 10⁻⁷
relative, far below the sensors' resolution), QARTOD flags ``int8``, ``time``,
``latitude`` and ``longitude`` ``float64``.  Processing reads them back as ``float64``.

Global attributes: cruise identity (``cruise``, ``platform_*``, ``expocode``),
``raw_filename``, ``raw_filesize_bytes``, ``raw_mtime_utc``, ``raw_metadata``, a stamped
``history``, and the upstream correction ledger (``sbe_*``, ``correction_*``,
``time_coordinate_source``, ``time_clock_offset_seconds``). Each is described in the table
below. A ``.hex`` cast adds ``input_format`` (``"hex"``), ``sample_interval_seconds``,
``sample_interval_kind``, ``sbe_n_scans``, ``seabirdscientific_version``, and
``time_bottle_log_check`` when a ``.bl`` bottle log was beside it; its ``raw_metadata``
holds the ``.hex`` header and the ``.xmlcon`` verbatim. Stage 2 adds ``dropped_channels``;
stage 3 adds ``data_processing_steps`` (the steps in the order they ran), ``products_made``
(each product and its steps) and, when a product's Bin Average kept part of a flagged scan,
``products_bin_average_partly_flagged``.

File identity and lineage
~~~~~~~~~~~~~~~~~~~~~~~~~~

Every file ctdcast writes carries a ``tracking_id`` (a UUID4, ACDD/OceanSITES
convention) and, from stage 2 on, a ``source_tracking_id`` naming the file it was made
from — so the chain back to the raw CNV is readable from any single output.

- ``tracking_id`` answers *which instance of this file this is*, **not** *whether the
  content changed*. It is **not a content hash**: a fresh id is written on **every** write,
  so a re-run of stage 3 produces a new id even if nothing else moved. Stability would be the
  bug — a stable id could not detect a rewrite.
- ``source_tracking_id`` (stage 2, stage 3) holds the ``tracking_id`` of the stage file that
  was read. In ``profiles.nc`` it is a per-``N_PROF`` variable, naming the source cast file
  per profile (the compiled file has its own ``tracking_id`` global attribute).  A product
  currently carries the ``source_tracking_id`` of the stage-3 data's own source (the stage-2
  file), because it is made before the stage-3 file is written; pointing it at the stage-3
  file is planned.
- Stage 1 has no upstream netCDF, so it records the raw source filename in a distinct
  attribute instead — ``source_cnv`` for a CNV cast, ``source_hex`` and ``source_xmlcon``
  for a ``.hex`` cast, ``source_mat`` for LADCP.
- ``processing_stage`` (``1``/``2``/``3``) records the stage in the file itself, not only in
  the filename, so a file copied out of its stage directory still declares what it is — the
  form a cross-package consumer (caldip) reads.  Products carry ``3`` today, the stage of the
  data they were made from.
- ``cast_id`` records the cast identity (the canonical zero-padded form, e.g. ``011`` or
  ``011b``) in the file for the same reason; it is stamped at stage 1 and carried forward.
- ``date_created`` is set once (first write) and preserved across re-runs; ``date_modified``
  moves on every write. So a stage-3 rewrite records *when* it was rewritten without resetting
  the creation time.

To read the best-available ctdcast file per cast from another package, call
``ctdcast.select_best_available(root)`` (stage 3, else stage 2, else stage 1) rather than
reimplementing the precedence — see :doc:`api`.

Processing state
~~~~~~~~~~~~~~~~~

Two OceanSITES fields say what state a file is in, using that standard's own vocabulary.

``data_mode`` (reference table 4) is a **global** attribute on every file: ``P``
provisional (the default — some processing may have been done, but the file is not the
product of record), ``D`` delayed-mode (all calibrations and QC applied), ``M`` mixed.
``D`` is **declared, never inferred**: it comes only from ``cruise_info.data_mode: D`` in
the config, because no code can know that *every* calibration a cruise needed was applied.
A quick-look (``ctdcast draft``) file is always ``P``. In ``profiles.nc`` the global value
is ``M`` only when the compiled casts genuinely differ; a per-``N_PROF`` ``source_data_mode``
variable always says which profile is in which mode. Casts merely compiled from different
*stages* do not make the file ``M`` (stages 1–3 are all provisional — ``source_stage``
records the stage difference). ``data_mode_meaning`` always accompanies it.

``processing_level`` (reference table 3) is a **per-variable** attribute recording what has
been done to that variable, using table 3's strings verbatim:

- ``Instrument data that has been converted to geophysical values`` — stamped at stage 1 on
  every **measured** channel (temperature, conductivity, pressure, oxygen, fluorescence,
  turbidity, beam transmission), identified by its link to a sensor in the CNV ``<Sensors>``
  block or the ``.xmlcon``.  The altimeter has no serial number, so no catalog entry and no
  link, and does not carry it.
  **Computed** channels (``ctd_salinity_*``, density, …) do not carry it: they were derived
  from already-converted inputs, never instrument data. Absence is not "raw" — table 3 has an
  explicit raw value; absence means *not stated*.
- ``Ranges applied, bad data flagged`` — stage-2 soak/deck flags and stage-3 gross-range and
  spike tests.
- ``Post-recovery calibrations have been applied`` — a stage-3 conductivity calibration; it
  **propagates** to re-derived salinity, whose values now embody the calibration.

When several apply to one variable they are joined with ``"; "`` in the order applied (comma
is unusable — ``Ranges applied, bad data flagged`` contains one), so the attribute doubles as
the procedure sequence. The list is an ordered **set**: re-running a stage never duplicates a
value. The rule behind the split is that a value-changing procedure (calibration, flagging)
propagates to variables derived from the changed inputs, while an origin claim (conversion)
does not. Spelling is lowercase ``processing_level`` throughout, matching the ``<PARAM>:``
template; do not "correct" a file to a capitalised variant from a stray manual example.

The compiled ``profiles.nc`` carries the per-variable ``processing_level`` too, so the archive
is interpretable without the stage files: for each variable it is the value the compiled casts
agree on, or — where they differ — an explicit "mixed across casts" marker, never a union of
their sentences (a union would claim a procedure on a cast that never had it). The per-profile
treatment stays reachable through ``source_stage`` / ``source_data_mode`` /
``source_tracking_id``.

Profiles file (``<ctd_root>/profiles.nc``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Compiled on a pressure grid (1 dbar unless ``processing.profiles_dbar`` says otherwise,
recorded in ``pressure_spacing_dbar``), dimensions ``N_PROF × pressure``.  Per profile:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Name
     - Description
   * - ``cast_number``
     - Integer cast number.
   * - ``cast_suffix``
     - Letter suffix for a repeated cast (``"b"``), empty otherwise. Identity is
       the ``(cast_number, cast_suffix)`` pair.
   * - ``cast_id``
     - The same identity as one string, ``011`` or ``011b``.
   * - ``source_file``, ``source_tracking_id``, ``source_data_mode``
     - The stage file each profile was compiled from, its ``tracking_id``, and its
       ``data_mode``.
   * - ``source_stage``
     - Which processing stage this profile was compiled from — ``int8`` with
       ``flag_values``/``flag_meanings``, the same idiom as the QARTOD flags:
       ``1`` converted, ``2`` soak flagged, ``3`` QC and calibration, and ``0``
       *unknown*. ``0`` means the source was an unsuffixed file read through the
       flat-layout shim, which does not state its own stage — recorded as unknown
       rather than assumed to be 1.
   * - ``cast_direction``
     - ``"down"`` or ``"up"`` (``cast_type`` is a deprecated alias for the same values).
   * - ``latitude``
     - Latitude in decimal degrees north.
   * - ``longitude``
     - Longitude in decimal degrees east.
   * - ``time_start``, ``time_end``
     - Start and end of the profile's leg, stored as seconds since 1970 (read as datetimes).
   * - ``max_pressure_dbar``
     - The deepest pressure of the cast.
   * - ``gebco_depth_m``
     - Water depth at the cast position from GEBCO, when the compile was given a file
       (``ctdcast process --gebco``).
   * - ``<var>_<parameter>``
     - A correction parameter that differs between casts (for example a per-cast cell thermal
       mass ``alpha``), one value per profile; when every cast agrees it is an attribute of the
       variable instead.
   * - ``processing_record``
     - The cast's processing steps, as a JSON list (the same on its down and up profiles): one
       entry per step with ``stage``, ``step``, ``producer``, ``version``, ``setting`` (what was
       configured), ``outcome`` (what it did on this cast), ``exception`` (a fixed phrase when the
       step ran differently from its setting on this cast: Loop Edit without its soak test, Bin
       Average keeping the good values of a partly flagged scan), ``variables``, and how the
       setting compares with SBE's documented value (``state``, ``reference``, ``source``).  Built from
       the stage file's ``history`` and per-variable attributes, so it holds only what the file
       records; ``processing.html`` is drawn from it.

On the grid: every measured and derived variable of the stage files (``ctd_temperature_1``,
``ctd_salinity``, ``ctd_oxygen``, ``conductivity_1``, ``ctd_fluor``, the raw voltages, …).

Each cast contributes **two** profiles — downcast and upcast — so ``N_PROF`` is
twice the cast count. The LADCP product has one profile per cast, so the two
files' ``N_PROF`` axes do not align; join on ``(cast_number, cast_suffix)``
rather than by index.

The deck unit's status words (``pump_status``, …) are gridded too today; their bin means
carry no meaning, and leaving them out of the compile is planned.

The pressure coordinate is the **bin centre**, so a binned value sits at the mean
depth of the samples it averages rather than at the bin's shallow edge.

Samples flagged QARTOD fail (``4``) or missing (``9``) — from the stage-2 soak /
back-on-deck trim and the stage-3 edits, gross-range and spike tests — are dropped
before binning, so failed data does not enter the bin means; a suspect (``3``) sample is
kept, as in a product's Bin Average. Each science variable
records ``qc_input_samples`` (finite input samples) and ``qc_excluded_samples``
(dropped); the netCDF inventory page reports these per variable as a percentage of
pre-binning samples, so the figure is not confounded by binning's own reduction in
point count. Note the soak/deck trim flags the same scans on *every* variable, so a
variable can be excluded here without its own gross-range or spike test firing.

Product files (``<ctd_root>/products/<name>/``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Made at stage 3 from each cast's stage-3 data by the steps in ``data_processing.products``
(see :doc:`config_yaml`), one file per cast: ``<cast>_<name>.nc``.  A product with a Bin
Average has dimension ``bin`` instead of ``time``, an ``nbin`` variable (scans in each bin),
salinity re-derived from the binned C, T and P, and no ``_qc`` variables (flagged 4 and 9
values were left out of their bins).  It keeps the stage file's global attributes and adds:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Attribute
     - Meaning
   * - ``product_name``, ``product_steps``, ``product_leg``
     - The product's name, its steps in order, and the leg a ``split`` kept.
   * - ``bin_average``, ``bin_average_method``
     - The Bin Average parameters, and the function and rule that applied them.
   * - ``bin_average_partly_flagged_scans``, ``bin_average_partly_flagged``
     - How many scans entering the bins had a value flagged 4 or 9 beside good values, by
       variable — the scans seabirdscientific's own Bin Average would have dropped whole
       (:ref:`sbe_differences`).

Where each attribute is written
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A fact is attached at the earliest stage at which it is *true*, so a
per-cast stage file is self-describing and the compiled product mostly
**inherits** rather than **originates**. The test is not "is it knowable at stage
1" but "can it still change after the ship docks" — a value written into 200
frozen stage files and then edited in config is a stale copy in 200 places.

.. list-table::
   :header-rows: 1
   :widths: 22 30 48

   * - Class
     - Examples
     - Where, and why

   * - **Identity**
     - ``cruise``, ``platform_*``, ``expocode``
     - Written at **stage 1** on every per-cast file, and lifted unchanged into
       the compiled products. Fixed the moment a cast is taken, and a file copied
       out of its directory must still say which cruise and which ship.

   * - **Derived from data**
     - ``geospatial_*``, ``time_coverage_*``, vertical bounds
     - **Computed at every level.** Not moved early: per-cast bounds describe
       that cast, compiled bounds describe the cruise. Same function, different
       scope.

   * - **Authored, and revisable**
     - contributors, ``license``, ``embargo``, ``acknowledgement``, ``title``
     - **Compile time only.** ORCIDs get corrected and embargo dates shift for
       years afterwards; per-cast copies would be plausible and wrong.

   * - **About the product**
     - ``pressure_spacing_dbar``, ``source``, ``id`` (only when ``cruise_info`` sets an
       ``expocode``)
     - **Compile time only.** They describe the gridded artefact, not the
       measurement, so there is nothing earlier to originate them.

   * - **Upstream provenance**
     - ``sbe_processing_order``, ``correction_*``, ``time_coordinate_source``,
       ``sbe_acquisition``, ``sbe_processing``
     - Written at **stage 1**, read from the CNV header. Describes what was done
       to the cast *before* ctdcast — see the ledger below.

   * - **Stage-local**
     - ``history``
     - **Each stage appends.** The model the rest of this table follows.

Lifting is strict
^^^^^^^^^^^^^^^^^

When the compiled product takes identity from the per-cast files, disagreement on
a **cruise-defining** attribute is an **error**, not a merge: a compiled product
describes one cruise, so two values of ``cruise`` or ``expocode`` mean either a
cast from another cruise in the directory or two legs sharing one root. (Legs
depart on different dates, so they have different EXPOCODEs — compile each into
its own root.)

The rest of the identity layer — the ``platform_*`` block — describes the *ship*,
and casts disagreeing there is ordinary registry drift: a ``platform_vocabulary``
URI edited between two stage-1 runs, a vessel renamed mid-programme. That says
nothing about whether these casts are one cruise, so it **warns** rather than
failing: ``cruise_info``'s value is used where it states one, and the attribute
is omitted where it does not, rather than picking one cast's answer arbitrarily.

An attribute no per-cast file states falls back to ``cruise_info`` with a
warning, which is the path for files written before identity was recorded at
stage 1.

Where the two sources disagree about identity, **the files win** — a stage file
records the cruise the cast was actually taken on, and a config can be edited
years later. The compiled product's ``title`` is built from the same lifted value,
so a file cannot be titled for one cruise and attributed to another. Re-run stage 1
if it is the per-cast files that are wrong.

For everything outside identity, config remains the source of truth: writing
identity at stage 1 makes the per-cast file *portable*, not the authority on what
the cruise is called in the report.

The correction ledger
~~~~~~~~~~~~~~~~~~~~~

A CNV usually arrives already processed — by the deck unit at acquisition and by
SBE Data Processing afterwards. Stage 1 reads the header and records what it finds,
so a stage file states not only what ctdcast did to it but what had already been
done. See :ref:`processing_framework` for why this matters; this section is the
attribute reference.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Attribute
     - Meaning

   * - ``sbe_acquisition``
     - The ``*`` block, **verbatim**, minus the ``<Sensors>`` XML (which is kept
       separately as ``raw_metadata``). Archival ground truth: no interpretation,
       so it cannot be wrong, and a key a future SBE release adds is preserved
       even though this version's parser has never heard of it.

   * - ``sbe_processing``
     - The ``#`` module block, verbatim, same rationale.

   * - ``sbe_processing_order``
     - The corrections in the order they were applied, e.g.
       ``align(deck) datcnv wildedit filter celltm Derive binavg``. Recorded
       explicitly rather than left to be re-derived: the deck-unit alignment
       carries no timestamp of its own, and some module writers emit none either,
       so file order is the only reliable ordering key.

   * - ``correction_align``
     - The deck-unit advance, per channel, e.g. ``SBE 11plus V 5.0 deck unit:
       primary conductivity +0.073 s, secondary conductivity +0.043 s,
       voltage 0 +0.000 s``. Per channel because older deck units do not always
       set the two conductivity channels alike, and a channel advanced less than
       the physical lag carries a residual the other does not.

       Written whenever the deck unit stated an advance at all — including one
       set to ``+0.000`` on every channel, since "present and set to zero" is a
       different fact from "no deck unit". In that case ``align(deck)`` is
       **absent** from ``sbe_processing_order``, because nothing was applied.

   * - ``correction_celltm``, ``correction_wildedit``, ``correction_binavg``, …
     - **One attribute per module in the chain**, naming the agent and the
       parameters it used. There is no curated subset: deciding which modules
       "count" as corrections would mean predicting them, and real headers carry
       modules that were not predicted. A module that ran **more than once** —
       which Sea-Bird explicitly sanctions for Wild Edit — is suffixed
       ``correction_wildedit``, ``correction_wildedit_2``, in file order, so no
       run's parameters are lost.

       **Absence means "not recorded", never "not done"** — a file whose chain
       ctdcast could not parse has the verbatim blocks and no ``correction_*``
       entries at all.

   * - ``time_coordinate_source``
     - Which clock the ``time`` coordinate is anchored to, and to which moment:
       ``System UTC, first data scan``, ``NMEA time, header``, and so on. SBE
       records this in a bracket on its ``start_time`` line and it **varies
       between cruises**, so a file that does not state it leaves the reader
       unable to tell GPS time from a possibly-drifting acquisition clock.

   * - ``time_clock_offset_seconds``
     - ``NMEA UTC`` minus ``System UTC``, where the header carries both. Several
       seconds is normal and the sign varies. It is *reported*, not applied — a
       single cast cannot distinguish a drifting clock from a stale NMEA sentence;
       that takes the whole cruise.

The unit of record is the **correction**, not the module — which matters because
the most consequential one, the deck-unit conductivity alignment, is not a module
at all and lives in a different part of the header. Every module in the chain then
contributes a correction of its own, so in practice the ledger is one entry per
module plus one for the deck unit.

Parameters keep the SBE channel names the header uses (``t090C``, ``c0S/m``) rather
than being translated to ctdcast's canonical names: the file states what its source
stated, and translation happens where the mapping is needed.

Sensor provenance
~~~~~~~~~~~~~~~~~

``profiles.nc`` also records which physical sensor produced each measurement,
using three families of variables. The capitalisation and the ``_channel_``
infix are meaningful — keep them distinct:

``SENSOR_<TYPE>_<SERIAL>`` — upper-case, dimensionless
  One variable per **distinct physical device** used anywhere in the cruise,
  e.g. ``SENSOR_TEMPERATURE_5806`` or ``SENSOR_FLUOROMETER_FLNTURTD_3219``. It
  holds no data; all provenance is in its attributes (``sensor_model``,
  ``sensor_serial_number``, ``sensor_calibration_date``, ``sensor_maker``, the
  L05/L22/L35 vocabulary URIs, ``model_source``, and its ``sensor_role`` and
  ``sensor_channel``). A **frequency** sensor (temperature, conductivity,
  pressure) also carries ``sensor_calibration_slope`` and
  ``sensor_calibration_offset`` — the ``datcnv`` drift/span correction already
  baked into the data before ctdcast read it; a value away from the identity
  (slope 1, offset 0) means a correction was applied. Every entry (frequency and
  voltage alike) also carries ``sensor_config_xml`` — the whole ``<sensor>``
  block from the CNV ``<Sensors>`` header, verbatim: every base calibration
  coefficient and its type context, so the raw→physical conversion is
  reconstructable from the compiled file alone, not only from the stage-1
  ``raw_metadata``. The serial identifies the device, so a cell used as both
  primary and secondary of one type is a single entry; ``sensor_shared_with``
  cross-links one device serving two roles (e.g. a combined FLNTU as both
  fluorometer and turbidity).

  Each measured **data variable** carries a single ``sensor`` attribute naming
  the ``SENSOR_*`` entry that produced it (e.g. ``ctd_temperature_1``'s
  ``sensor = "SENSOR_TEMPERATURE_5806"``). That one link is all a variable
  holds; its role and channel live on the entry. A device ctdcast does not convert
  (pH, a user polynomial) is linked to its raw voltage on a ``.hex`` cast
  (``volt3_raw``'s ``sensor = "SENSOR_PH_339"``); a device with no stored variable at
  all still records its role and channel. This is what lets the compile aggregate the
  catalog without re-reading the header.

``sensor_<role>`` — lower-case, dimension ``N_PROF``
  Per profile, a **string** naming the ``SENSOR_*`` variable that filled each
  role — e.g. ``sensor_temperature_1`` may be ``"SENSOR_TEMPERATURE_5806"`` on
  early casts and ``"SENSOR_TEMPERATURE_4823"`` after a swap. This answers
  "which sensor's calibration applies to this cast?"; diffing it down the casts
  gives the sensor-change log.

``sensor_channel_<role>`` — lower-case, dimension ``N_PROF``
  Per profile, the **integer** raw acquisition channel that role's sensor was
  wired into (``-1`` where unused). A change here while ``sensor_<role>`` holds
  constant is a re-cabling, not a hardware swap.

Roles use ctdcast's canonical names: ``temperature_1``/``_2``,
``conductivity_1``/``_2``, ``oxygen_1``/``_2``, ``pressure``, ``fluorometer``,
``turbidity``, ``transmissometer``, ``ph``, ``altimeter``. The universal
SensorID → model table ships in ``ctdcast/config/sbe_sensors.yaml``; per-cruise
refinements come from the ``sensors:`` block in ``config.yaml`` (see above). The
``SBE sensors`` report page presents all of this as configuration, inventory and
rewiring tables, plus the per-cast preferred T/C pair and oxygen (where a cast carries
two); the inventory lists each temperature, conductivity and pressure sensor's datcnv
Slope and Offset. The page ends with the ``SENSOR_*``, ``sensor_<role>`` and
``sensor_channel_<role>`` variables themselves; the ``profiles.nc`` netCDF inventory
page explains the three families and links there rather than repeating them.

Where it is built, and two kinds of provenance
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The catalog is resolved **once, at stage 1** — the per-cast netCDF files carry
their own ``SENSOR_*`` entries — and the compile simply aggregates them; nothing
re-reads the SBE header downstream. This splits each entry's attributes into two
provenances that mean different things when two casts disagree:

- **Header-native** (``sensor_calibration_date``, ``sensor_calibration_slope``,
  ``sensor_calibration_offset``) are fixed for a serial. A mismatch across casts
  cannot be a real recalibration at sea, so it is flagged as a parsing or data
  error.
- **Config-resolved** (``sensor_model``, ``sensor_maker``, the vocabulary URIs)
  come from the SensorID registry and the ``sensors:`` overrides. A mismatch
  just means the casts were stamped under different config versions — expected,
  and fixed by re-running stage 1 (or a future ``enrich`` step) to restamp, not
  by treating it as a data error.

Because provenance lives on the file, the per-cast page's **Sensors and
calibration state** table reads the catalog directly — one row per device,
joined to the variable it produced and showing its model, calibration date and
any applied slope/offset — rather than re-parsing the SBE header. A file that
predates the catalog falls back to the header parse.

A per-cast file that carries **no** ``SENSOR_*`` catalog predates this
provenance. The ``build_profiles`` library call still compiles it, with a
warning and a ``sensor_catalog`` attribute recording the gap; ``ctdcast process
--stage profiles`` and ``ctdcast run`` instead refuse, because re-running stage
1 to build the catalog is the actionable fix before a product is shipped.
