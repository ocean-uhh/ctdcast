.. _data_files:

===================
Data files (netCDF)
===================

Layout
~~~~~~

Each instrument has one **root** that ctdcast owns — ``ctd_root`` and
``ladcp_root`` in the config's ``data:`` block. Inside it, one directory per
processing stage, and the compiled product at the top:

.. code-block:: text

   <ctd_root>/
       stage1/  mixsed2_017_stage1.nc     raw CNV converted
       stage2/  mixsed2_017_stage2.nc     + soak / back-on-deck flags
       stage3/  mixsed2_017_stage3.nc     + QC and calibration
       profiles.nc                        compiled product

   <ladcp_root>/
       stage1/  ladcp_017_stage1.nc       LADCP has one stage
       ladcp_profiles.nc

Stages are **non-destructive**: each reads its predecessor and writes a new file,
so a stage can be re-run without redoing the ones before it, and the full lineage
stays on disk. See :doc:`processing_framework` for what each stage does.

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
     - Practical salinity (PSU).
   * - ``ctd_oxygen`` / ``ctd_oxygen_1`` / ``ctd_oxygen_2``
     - Dissolved oxygen in µmol kg⁻¹.
   * - ``ctd_fluor``
     - Fluorescence in µg L⁻¹ (chlorophyll-a equivalent).
   * - ``ctd_turbidity``
     - Turbidity in NTU.
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
     - Raw voltage (V) for sensors whose conversion is not implemented (e.g. pH) or whose calibration coefficients are absent. ``N`` is the zero-based voltage channel index.

Global attributes: cruise identity (``cruise``, ``platform_*``, ``expocode``),
``raw_filename``, ``raw_metadata``, a stamped ``history``, and the upstream
correction ledger (``sbe_*``, ``correction_*``, ``time_coordinate_source``,
``time_clock_offset_seconds``). Each is described in the table below.

Profiles file (``<ctd_root>/profiles.nc``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Compiled on a 1 dbar pressure grid, dimensions ``N_PROF × pressure``:

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
   * - ``time_start``
     - Start time of the cast (datetime64).
   * - ``time_end``
     - End time of the cast (datetime64).
   * - ``ctd_temperature`` / ``ctd_temperature_1``
     - In-situ temperature on the 1 dbar grid.
   * - ``ctd_salinity`` / ``ctd_salinity_1``
     - Practical salinity on the 1 dbar grid.
   * - ``ctd_oxygen`` / ``ctd_oxygen_1``
     - Dissolved oxygen in µmol kg⁻¹ on the 1 dbar grid.

Each cast contributes **two** profiles — downcast and upcast — so ``N_PROF`` is
twice the cast count. The LADCP product has one profile per cast, so the two
files' ``N_PROF`` axes do not align; join on ``(cast_number, cast_suffix)``
rather than by index.

The pressure coordinate is the **bin centre**, so a binned value sits at the mean
depth of the samples it averages rather than at the bin's shallow edge.

Samples flagged QARTOD suspect (``3``) or fail (``4``) — from the stage-2 soak /
back-on-deck trim and the stage-3 gross-range and spike tests — are dropped before
binning, so flagged data does not enter the bin means. Each science variable
records ``qc_input_samples`` (finite input samples) and ``qc_excluded_samples``
(dropped); the netCDF inventory page reports these per variable as a percentage of
pre-binning samples, so the figure is not confounded by binning's own reduction in
point count. Note the soak/deck trim flags the same scans on *every* variable, so a
variable can be excluded here without its own gross-range or spike test firing.

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
     - ``pressure_spacing_dbar``, ``source``, ``id``
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
  L05/L22/L35 vocabulary URIs, and ``model_source``). The serial identifies the
  device, so a cell used as both primary and secondary of one type is a single
  entry; ``sensor_shared_with`` cross-links one device serving two roles (e.g. a
  combined FLNTU as both fluorometer and turbidity).

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
rewiring tables.
