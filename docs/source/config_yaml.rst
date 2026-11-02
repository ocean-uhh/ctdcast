.. _config_yaml:

===========
config.yaml
===========

``data`` block
~~~~~~~~~~~~~~

Every path in this block is either an **input** ctdcast only reads, or an **output
root** ctdcast owns and writes into.  The distinction is worth holding onto, because
only the second kind is safe to delete and regenerate:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Inputs — read, never written
     - ``cnv_dir``, ``hex_dir``, ``ladcp_dir``, ``gebco_nc``, ``groupings_yaml``
   * - Output roots — created and written by ctdcast
     - ``ctd_root``, ``ladcp_root``

A cruise's raw CTD input is either its CNV files (``cnv_dir``) or its raw SBE 911plus
``.hex`` files (``hex_dir``), never both: ``ctd_raw_format`` names which one stage 1
reads, so a stray directory never changes what a cruise is read from.

.. list-table::
   :header-rows: 1
   :widths: 20 10 70

   * - Key
     - Required
     - Description
   * - ``ctd_root``
     - yes
     - The CTD root ctdcast owns.  It holds ``stage1/`` … ``stage3/`` (one file
       per cast per stage) and the compiled ``profiles.nc`` at its top, so a
       product cannot drift away from the stage files it was built from.
       Created for you.
   * - ``ladcp_root``
     - no
     - The same for LADCP: ``stage1/`` and ``ladcp_profiles.nc``.  Required only
       when ``ladcp_dir`` is set.
   * - ``cnv_dir``
     - no
     - Directory of calibrated CNV files, one per cast — an input ctdcast only
       reads.  Stage 1 needs ``cnv_dir`` or ``hex_dir``.
   * - ``hex_dir``
     - no
     - Directory of raw SBE 911plus ``.hex`` files, each with its ``.xmlcon`` beside
       it (same name, any case: ``MIXSED2_004_b.hex`` pairs with
       ``MIXSED2_004_B.XMLCON``).  Stage 1 reads them at the native 24 Hz with
       Sea-Bird's ``seabirdscientific`` toolkit, converting temperature,
       conductivity (mS/cm), pressure, and the ECO, altimeter and C-Star channels
       with the ``.xmlcon`` coefficients, Slope and Offset.  Every voltage channel
       is also kept as raw volts (``volt<N>_raw``; an SBE 43 as ``oxygen_raw_<N>``),
       with a quick-look ``sbe_oxygen_<N>`` until stage 3 derives ``ctd_oxygen``.
       Time is the header's ``NMEA UTC (Time)`` plus one scan interval per scan,
       falling back to the PC upload time (with a warning) when NMEA is missing
       or more than an hour off.  No Sea-Bird processing (filters, edits, cell
       thermal mass) is applied: a hex cast's profiles will not match a processed
       CNV's until stage 3 applies those steps.
   * - ``ctd_raw_format``
     - no
     - ``cnv`` or ``hex``: which raw input stage 1 reads.  May be left out when only
       one of ``cnv_dir`` / ``hex_dir`` is set; required when both are.
   * - ``ladcp_dir``
     - no
     - Directory of processed LADCP ``.mat`` files, one per cast — an input
       ctdcast only reads.  These are expected in the form written by the **LDEO
       LADCP processing software**, which is what turns the instrument's raw
       ``.000`` files into a velocity solution.  ctdcast reads that solution; it
       does not process raw LADCP data itself.
   * - ``groupings_yaml``
     - no
     - Path to the cast-groupings file (conventionally ``ctd_groupings.yaml``)
       defining ``sections:`` and ``timeseries:``.  Required for section pages.
       Superseded spelling: ``section_yaml``, still accepted.
   * - ``profiles_nc``
     - no
     - Override for the compiled profiles path.  Derived as
       ``<ctd_root>/profiles.nc``; set this only to read a product that lives
       elsewhere.
   * - ``gebco_nc``
     - no
     - Path to a GEBCO NetCDF bathymetry file.  Maps render without bathymetry if
       this is omitted or the file is not found — not an error.
   * - ``nc_dir``
     - no
     - Superseded spelling of ``ctd_root``, still accepted.  A directory written
       before the stage layout holds unsuffixed per-cast files; those are read as
       stage 1.

``output`` block
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 10 70

   * - Key
     - Required
     - Description
   * - ``dir``
     - yes
     - Directory where all HTML output is written.  Created if it does not exist.

``generate`` block
~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 10 70

   * - Key
     - Default
     - Description
   * - ``stations``
     - ``true``
     - Generate per-cast station pages.
   * - ``sections``
     - ``true``
     - Generate transect section pages.  Requires a compiled ``profiles.nc``
       and ``groupings_yaml``.
   * - ``timeseries``
     - ``true``
     - Generate the cruise-wide time series page.  Requires a compiled
       ``profiles.nc``.
   * - ``index``
     - ``true``
     - Generate the navigation pages (``index.html``, ``casts.html``,
       ``sections.html``).
   * - ``leaflet``
     - ``true``
     - Generate the interactive Leaflet map page.

``force`` (regenerate all pages even if they already exist) is a **top-level**
config key, not part of the ``generate`` block; it defaults to ``false`` and is
overridden by ``--force`` on the command line.

``processing`` block (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Per-cruise overrides for the pipeline stages.  Every key is optional and falls
back to a built-in default.

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Key
     - Description
   * - ``profiles_dbar``
     - Vertical bin size (dbar) for the compiled ``profiles.nc`` grid.  Default ``1``.
   * - ``trim.near_surface_dbar``
     - Pressure threshold for stage-2 soak detection (dbar).  Default ``10``.
   * - ``trim.drop_sbe``
     - Stage-2 curated drop: the list of SeaBird-derived ``sbe_*`` channels to remove
       (recorded in ``history`` and the ``dropped_channels`` attribute).  Omit for the
       default — every ``sbe_*`` channel present.  May name only ``sbe_*`` channels; a
       non-``sbe_`` name is refused.  ``[]`` keeps them all.
   * - ``qc.gross_range.{suspect,fail}.<var>``
     - Stage-3 gross-range bounds ``[min, max]`` per variable, in two tiers:
       ``suspect`` (QARTOD flag 3) and ``fail`` (flag 4).  Anything not listed
       keeps its built-in default; the cast page's QC panel shows the tiers
       actually applied.  Bounds are in the variable's **stored units** —
       conductivity mS/cm, salinity PSU, temperature deg C, oxygen umol/kg,
       pressure dbar.
   * - ``qc.spike.{suspect,fail}.<var>``
     - Stage-3 spike thresholds on ``|v[i] - (v[i-1]+v[i+1])/2|``, in two tiers
       (flag 3 / flag 4), same units.  Fluorescence and turbidity have no spike
       test by default (natural fine-scale variability).
   * - ``calibration.conductivity_slope``
     - Multiplicative conductivity calibration applied at stage 3; salinity is
       re-derived from the calibrated conductivity.
   * - ``alignctd.<channel>``
     - Stage-3 alignment: seconds to advance a channel relative to pressure, as Sea-Bird's
       Align CTD does, applied with ``seabirdscientific``.  Channels: ``conductivity``,
       ``oxygen`` (every line), or ``conductivity_1/2``, ``oxygen_1/2`` (one line; wins over
       the family key).  Each takes a ``default`` and/or ``ranges``
       (``- {casts: [[first, last]], value: 0.021}``).  Conductivity values are a residual on
       top of the deck unit's hardware advance, which is already in the raw data; oxygen acts
       on the SBE 43 voltage (``oxygen_raw_<N>``), never on a converted oxygen.  Values shifted
       past either end of a cast become NaN, flagged 9 (missing); no scan is removed.
   * - ``celltm.default`` / ``celltm.ranges`` / ``celltm.conductivity_<N>``
     - Stage-3 cell thermal mass correction of conductivity: ``{alpha: 0.03, tau: 7.0}``
       (Sea-Bird's alpha and tau = 1/beta in seconds), with the temperature of the same line.
       A per-line key wins over the block's own ``default`` / ``ranges``.
   * - ``oxygen.tau_window_seconds``
     - Window (s) for the SBE 43 tau correction's dV/dt when stage 3 derives ``ctd_oxygen``
       from the voltage (``.hex`` casts).  Default ``2``.

   * - ``preferred_pair.default`` / ``preferred_pair.ranges``
     - On a dual-sensor cast, which temperature/conductivity pair (and the salinity derived
       from it) is the better one: ``primary`` (the ``_1`` channel) or ``secondary`` (``_2``).
       A cruise-wide ``default`` plus per-cast-range exceptions
       (``- {casts: [[first, last]], use: secondary}``).  Stage 3 builds the plain
       ``ctd_temperature`` / ``ctd_salinity`` / ``conductivity`` as a per-cast copy of the
       selected channel and records the chosen sensor in ``sensor_<role>_preferred``.  Values
       are exactly ``primary`` / ``secondary``; a single-sensor cast has no choice and is left
       untouched; an undeclared dual cast gets no plain name (never a silent ``_1``).
   * - ``preferred_oxygen.default`` / ``preferred_oxygen.ranges``
     - The same grammar for the oxygen sensor, declared independently of the pair (oxygen
       preference can flip cast-to-cast on fouling/drift — a single-cast range
       ``[[15, 15]]`` is valid).  Builds the plain ``ctd_oxygen``.
   * - ``clock.segments``
     - Stage-2 acquisition-clock correction: a list of
       ``{casts: [[first, last]], clock_offset_seconds: N}`` entries, each shifting
       the ``time`` coordinate of the casts in range by ``N`` seconds
       (``NMEA - System``).  Each entry also carries ``n_casts`` and
       ``clock_offset_sd_seconds`` — the evidence that justified the offset, recorded
       with the correction so its uncertainty travels with it.  **Generated by
       ``ctdcast clock``** — paste it in as-is rather than hand-computing the sign.
       Applied only where the coordinate is on the System clock (a cruise already on
       GPS is refused); a ``drift`` verdict has no applier.

Alignment, cell thermal mass and the oxygen derivation act scan by scan, so they run only
on a cast at its instrument's native scan rate (24 Hz on a 911plus) that Sea-Bird has not
already corrected the same way.  Any other cast skips them with a warning and a
``history`` note, and still gets the slope, salinity and QC.  Stage 3 runs: alignment,
cell thermal mass, conductivity slope, salinity, oxygen, then gross-range and spike QC on
the corrected values.

.. code-block:: yaml

   processing:
     qc:
       gross_range:
         suspect: { ctd_salinity_1: [30.0, 38.0] }   # tighten for a cruise
         fail:    { ctd_salinity_1: [0.0, 42.0] }
       spike:
         suspect: { pressure: 10.0 }                 # dbar
         fail:    { pressure: 50.0 }
     clock:                                          # from `ctdcast clock config.yaml`
       segments:                                     # one entry per segment found
         - casts: [[1, 3]]
           clock_offset_seconds: 4.33
           n_casts: 3                                 # the evidence for the offset
           clock_offset_sd_seconds: 0.47
         - casts: [[4, 32]]
           clock_offset_seconds: 7.76
           n_casts: 29
           clock_offset_sd_seconds: 0.57
         - casts: [[33, 182]]
           clock_offset_seconds: -2.07
           n_casts: 150
           clock_offset_sd_seconds: 0.69

Preferred sensor
^^^^^^^^^^^^^^^^

A dual-sensor cast records both a primary (``_1``) and a secondary (``_2``) channel; which
is the better one is a judgement about noise that only the operator can make.  Declare it
cruise-wide with per-cast exceptions:

.. code-block:: yaml

   processing:
     preferred_pair:                 # temperature + conductivity + salinity move together
       default: primary              # cruise-wide; "primary" | "secondary"
       ranges:                       # exceptions by cast number; [[first, last]] inclusive
         - casts: [[31, 60]]
           use: secondary
     preferred_oxygen:               # independent oxygen choice, same grammar
       default: primary
       ranges:
         - casts: [[15, 15]]         # a single-cast range is valid
           use: secondary

Notes:

* Values are exactly ``primary`` / ``secondary`` — a digit or any other spelling is refused
  at stage 3 (a clear error, not a silent guess).
* ``casts`` needs an explicit last number (no open-ended range).  So declare the
  **latest / ongoing** configuration as the unbounded ``default`` and the **earlier** casts
  as explicit ``ranges`` — then the config need not be edited as new casts are added.
* Declaring one group, both, or neither is valid, and ``preferred_oxygen`` may differ from
  ``preferred_pair``.  An **explicit range** naming a channel a single-sensor cast lacks is
  an error; a **default** that lands on a single-sensor cast is silently skipped.
* Where the per-cast serials of a declared range do not match where the hardware actually
  changed, the compile and ``ctdcast validate`` warn (never block) — reconcile the range
  with the sensor-change log on the cast page.

``sensors`` block (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Per-cruise sensor provenance that the CNV header cannot supply: sensors it cannot
identify (the altimeter and user-polynomial channels carry no make/model) and
model refinements (a combined FLNTU(RT)D reads as a generic fluorometer plus
turbidity from its SensorID alone).  The universal SensorID → model table ships
in ``ctdcast/config/sbe_sensors.yaml``; this block adds only what is
cruise-specific.  Overrides are keyed by **role** (not SensorID, which the newer
Sea-Bird XML drops); use ``role:serial`` only to disambiguate two different-model
devices in one role.

.. code-block:: yaml

   sensors:
     overrides:
       altimeter:                       # SensorID 0 records no make/model
         sensor_model: "Benthos PSA-916T"
         sensor_model_vocabulary: "https://vocab.nerc.ac.uk/collection/L22/current/TOOL0134/"
         sensor_maker: "Teledyne Benthos"
         model_source: operator
       fluorometer:                     # sharpen the generic default to the combined unit
         sensor_model: "WET Labs ECO FLNTU(RT)D"
         sensor_model_vocabulary: "https://vocab.nerc.ac.uk/collection/L22/current/TOOL1531/"
         model_source: operator
       turbidity:
         sensor_model: "WET Labs ECO FLNTU(RT)D"
         sensor_model_vocabulary: "https://vocab.nerc.ac.uk/collection/L22/current/TOOL1531/"
         model_source: operator
     aliases:
       # the value is the canonical serial spelling and becomes the catalog entry
       # name, so both recorded spellings fold onto SENSOR_FLUOROMETER_3508 /
       # SENSOR_TURBIDITY_3508 rather than the long ..._FLNTURTD_3508 names
       "FLNTURTD-3508": "3508"

Roles: ``temperature_1``/``_2``, ``conductivity_1``/``_2``, ``oxygen_1``/``_2``,
``pressure``, ``fluorometer``, ``turbidity``, ``transmissometer``, ``ph``,
``altimeter``.  A sensor left unresolved (no override, and the SensorID gives no
model) is recorded with ``sensor_model: "UNK"`` and a build-time warning —
ctdcast never guesses a model.

Example
~~~~~~~

.. code-block:: yaml

   data:
     ctd_root:     /data/cruise/CTD/ctd_nc     # stage1/…stage3/ + profiles.nc
     ladcp_root:   /data/cruise/LADCP/ladcp_nc
     cnv_dir:      /data/cruise/CTD/cnv_cal    # external input
     groupings_yaml: /data/cruise/config/ctd_groupings.yaml
     gebco_nc:     /data/GEBCO_2025.nc

   output:
     dir: /data/cruise/report

   generate:
     stations:   true
     sections:   true
     timeseries: true
     force:      false
