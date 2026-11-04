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

Processing settings (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Five top-level blocks set how the pipeline treats the data, each by what it does, plus a small
``processing:`` block for the stage-2 trim and the profiles grid.  Every key is optional and falls
back to a built-in default.

.. code-block:: yaml

   preferred_sensor:      # which sensor the plain ctd_temperature / ctd_salinity / ctd_oxygen use
     tc: primary
     oxygen: primary
   clock: {...}           # stage-2 acquisition-clock correction, from `ctdcast clock`
   qc: {...}              # stage-3 gross-range and spike tests
   fit: {...}             # how `ctdcast fit` searches; nothing here is applied
   data_processing:       # what ctdcast applies to the data at stage 3
     slope_offset: {...}
     oxygen: {...}
     steps: [...]
   processing:
     trim: {...}
     profiles_dbar: 1

**From the 0.4 layout.** Everything used to sit under ``processing:``.  ``processing.preferred_pair`` /
``preferred_oxygen``, ``processing.clock``, ``processing.qc`` and
``processing.calibration.conductivity_slope`` are still read, with a deprecation warning, until the
release after this one; the slope then applies to both sensors with offset 0.  Ranges in a
preferred-sensor declaration now take ``value:`` (``use:`` is read with a warning).

``data_processing`` block
^^^^^^^^^^^^^^^^^^^^^^^^^

What stage 3 applies, after stage 2's soak and deck flags.  ``ctdcast inspect <file>.cnv`` prints the
block that reproduces a cruise's own Sea-Bird processing; ``ctdcast fit`` suggests the ``alignctd`` and
``celltm`` values.

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Key
     - Description
   * - ``slope_offset.conductivity_<N>``
     - Per conductivity sensor, ``conductivity = slope * conductivity + offset``, applied first (where
       Sea-Bird applies them, at conversion); salinity is re-derived.  A bare ``{slope:, offset:}``
       (``offset`` defaults to 0) or a ``{default:, ranges:}`` declaration, for a sensor swapped
       mid-cruise.
   * - ``oxygen.tau_window_seconds``
     - Window (s) for the SBE 43 tau correction's dV/dt when stage 3 derives ``ctd_oxygen`` from the
       voltage (``.hex`` casts).  Default ``2``.
   * - ``steps``
     - The processing steps, run in the order listed; a step may appear more than once.  Each entry
       is one step name with its parameters.  A step is applied only if it is listed.
   * - ``products``
     - Files made from the stage-3 data by further steps, each ``{name, steps}``: a 1 dbar
       downcast, a 1 s series.  A product may use any step; ``split`` and ``binavg`` are
       product-only, since the stage-3 file keeps every scan, and ``binavg`` comes last.  Written
       to ``<ctd_root>/products/<name>/<cast>_<name>.nc``.  ``ctdcast inspect`` puts a CNV's
       Split and Bin Average into a product (two, one per leg, after a Split).  The stage-3 file
       records each product made and its steps in ``products_made``.
   * - ``allow_unapplied``
     - ``true`` to run when ``steps`` lists a step stage 3 does not apply yet (it is skipped).
       Default ``false``: such a config is refused.

The steps, as Sea-Bird names its modules:

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Step
     - Parameters
   * - ``wildedit``
     - ``pass1_nstd``, ``pass2_nstd``, ``mindelta``, ``scans_per_block``, ``exclude_flagged``,
       ``variables`` (defaults 2, 20, 0, 100, true, and pressure, temperature, conductivity and the
       SBE 43 voltages).  Marks outliers QARTOD 4 in each variable's ``_qc``; the values are kept.
       Applied with ``seabirdscientific``, Sea-Bird's Python package, which appears to differ from
       SBE Data Processing, Sea-Bird's Windows program, on near-constant blocks: with
       ``mindelta`` 0 the Windows program marks a whole 100-scan block where a channel sits at one
       or two A/D levels, seabirdscientific only the values off the main level.  Set ``mindelta``
       to a few A/D steps on such channels (SBE 43 voltage, altimeter, fluorescence).
   * - ``alignctd``
     - Seconds to advance a channel relative to pressure, as Sea-Bird's Align CTD.  Channels:
       ``conductivity``, ``oxygen`` (every sensor), or ``conductivity_1/2``, ``oxygen_1/2`` (one
       sensor; wins over the family key).  Each a **bare value** or a ``{default:, ranges:}``
       mapping (``ranges: - {casts: [[first, last]], value: 0.021}``).  Conductivity values are a
       residual on top of the deck unit's hardware advance, which is already in the raw data; oxygen
       acts on the SBE 43 voltage (``oxygen_raw_<N>``).  Values shifted past either end of a cast
       become NaN, flagged 9; no scan is removed.
   * - ``celltm``
     - Cell thermal mass correction of conductivity, ``{alpha: 0.03, tau: 7.0}`` (Sea-Bird's alpha,
       and tau = 1/beta in seconds), with the temperature of the same sensor pair.  Keyed
       ``conductivity`` or ``conductivity_<N>``, each a bare ``{alpha, tau}`` or a
       ``{default:, ranges:}`` mapping.
   * - ``filter``
     - Sea-Bird's low-pass filter, run forward and backward (no lag): ``time_constant`` (s) and
       ``variables``.  Sea-Bird's Filter with time constants A and B is two ``filter`` steps.
       Values an earlier Wild Edit marked are filtered across and kept as they were.  Applied with
       ``seabirdscientific``.
   * - ``window_filter``
     - ``type`` (``boxcar``, ``cosine``, ``triangle``, ``gaussian``, ``median``), ``width``
       (scans), ``variables``, ``exclude_flagged`` (default true; leaves out scans an earlier Loop
       Edit marked), and for a gaussian ``half_width`` and ``offset`` (s).  Applied with
       ``seabirdscientific``.
   * - ``loopedit``
     - Marks whole scans where the package reversed, moved slower than ``min_velocity`` (dbar/s,
       default 0.25; or ``mean_speed_percent`` of the mean speed over ``window_seconds``), or was
       still in the surface soak (``surface_soak: {min_depth, max_depth, deck_pressure,
       starts_below}``, default 5 m, 20 m, true, ``skip``; or ``false``, which marks no soak: the
       downcast starts at the shallowest scan before the deepest).  A cast whose recording is
       below the soak window before it is in it (a yo-yo cut into casts at depth) has no soak to
       remove: ``starts_below: skip`` runs it without the soak test and records why
       (``loop_edit_soak_not_applied``; an amber row on the processing page), ``fail`` refuses
       the cast.  The marks go into ``loop_edit_flag`` and QARTOD 4 in every
       ``_qc``; values are kept, and later steps with ``exclude_flagged`` leave the scans out.
       ``deck_pressure: true`` offsets the soak window by the first scan's depth, as
       seabirdscientific does; on OdB's CNVs (``useDeckPress = 1``, recordings starting in the
       water) SBE Data Processing matched no offset, which ``deck_pressure: 0`` reproduces.
   * - ``split``
     - Product only: ``down`` or ``up`` keeps that leg (to and from the deepest scan).
   * - ``binavg``
     - Product only, and last: ``bin`` (``decibars``, ``seconds``, ``scans``), ``size``, and
       optionally ``min_scans``, ``max_scans``, ``skip_over``, ``omit``, ``surface_bin: {min, max, value}`` and
       ``interpolate``.  A value whose ``_qc`` is 4 or 9 is left out of its own bin only, so one
       marked oxygen value does not remove that scan's temperature — unlike
       ``seabirdscientific``, which drops the whole scan (:ref:`sbe_differences`); a scan whose
       pressure is flagged 4 or 9 has no bin at all.  Scans Loop Edit marked are always left out
       (``exclude_flagged: false`` is refused).  Salinity is re-derived from
       the binned values.  Applied with ``seabirdscientific``.  Stage 3 refuses a config that lists one, because the
       steps after it would run on data it was meant to change first; set
       ``data_processing.allow_unapplied: true`` to run anyway, skipping it.  The skip is named in
       a warning, in ``history``, and in the stage-3 file's ``data_processing_steps`` attribute
       (the order the steps ran in).

Alignment, cell thermal mass, Wild Edit and the oxygen derivation act scan by scan, so they run only
on a cast at its instrument's native scan rate (24 Hz on a 911plus) that Sea-Bird has not already
processed the same way.  Any other cast skips them with a warning and a ``history`` note, and still
gets the slope, salinity and QC.

.. code-block:: yaml

   data_processing:
     slope_offset:
       conductivity_1: {slope: 1.0000452, offset: 0.0}
       conductivity_2:                       # a sensor swapped at cast 7
         default: {slope: 0.9999368}
         ranges:
           - casts: [[1, 6]]
             value: {slope: 1.0000120}
     steps:
       - wildedit:
           pass1_nstd: 2.0
           pass2_nstd: 20.0
           scans_per_block: 100
           variables: [pressure, ctd_temperature_1, conductivity_1, ctd_temperature_2, conductivity_2]
       - alignctd:
           conductivity: -0.015              # bare value: seconds for every cast (the usual case)
           conductivity_2:                   # a sensor swapped at cast 7: its own value from there on
             default: -0.040
             ranges:
               - casts: [[1, 6]]
                 value: -0.015
       - celltm:
           conductivity: {alpha: 0.0275, tau: 6.5}
       - loopedit: {min_velocity: 0.25, surface_soak: {min_depth: 5, max_depth: 20, deck_pressure: true}}
     products:
       - name: 1dbar_down
         steps:
           - split: down
           - binavg: {bin: decibars, size: 1}
       - name: 1sec
         steps:
           - binavg: {bin: seconds, size: 1}

``qc``, ``clock`` and ``fit`` blocks
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Key
     - Description
   * - ``qc.gross_range.{suspect,fail}.<var>``
     - Stage-3 gross-range bounds ``[min, max]`` per variable, in two tiers: ``suspect`` (QARTOD
       flag 3) and ``fail`` (flag 4).  Anything not listed keeps its built-in default; the cast
       page's QC panel shows the tiers actually applied.  Bounds are in the variable's **stored
       units** — conductivity mS/cm, salinity PSU, temperature deg C, oxygen umol/kg, pressure dbar.
   * - ``qc.spike.{suspect,fail}.<var>``
     - Stage-3 spike thresholds on ``|v[i] - (v[i-1]+v[i+1])/2|``, in two tiers (flag 3 / flag 4),
       same units.  Fluorescence and turbidity have no spike test by default (natural fine-scale
       variability).
   * - ``clock.segments``
     - Stage-2 acquisition-clock correction: a list of
       ``{casts: [[first, last]], clock_offset_seconds: N}`` entries, each shifting the ``time``
       coordinate of the casts in range by ``N`` seconds (``NMEA - System``).  Each entry also
       carries ``n_casts`` and ``clock_offset_sd_seconds`` — the evidence that justified the
       offset, recorded with the correction.  **Generated by ``ctdcast clock``** — paste it in as-is
       rather than hand-computing the sign.  Applied only where the coordinate is on the System
       clock; a ``drift`` verdict has no applier.
   * - ``fit.<setting>``
     - ``ctdcast fit`` settings (the finder that suggests ``alignctd`` / ``celltm`` values; nothing
       here is applied): the cell-thermal-mass window top (``ctm_pmin``, dbar), the thermocline
       threshold for the alignment cost (``gradient``, deg C/dbar), the alignment window top and
       minimum along-leg speed (``align_pmin`` dbar, ``min_speed`` dbar/s), the down/up weighting
       scale (``gap_seconds``), the recommended-value tolerance (``ctm_tolerance``, a fraction of the
       cost minimum; default ``0.02``), and the casts per block (``block``).

.. code-block:: yaml

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
         n_casts: 3                                # the evidence for the offset
         clock_offset_sd_seconds: 0.47
       - casts: [[4, 182]]
         clock_offset_seconds: 7.76
         n_casts: 179
         clock_offset_sd_seconds: 0.57

``processing`` block
^^^^^^^^^^^^^^^^^^^^

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
     - Stage-2 curated drop: the list of SeaBird-derived ``sbe_*`` channels to remove (recorded in
       ``history`` and the ``dropped_channels`` attribute).  Omit for the default — every ``sbe_*``
       channel present.  May name only ``sbe_*`` channels; a non-``sbe_`` name is refused.  ``[]``
       keeps them all.

Preferred sensor
^^^^^^^^^^^^^^^^

A dual-sensor cast records both a primary (``_1``) and a secondary (``_2``) channel; which is the
better one is a judgement about noise that only the operator can make.  Declare it cruise-wide with
per-cast exceptions.  ``tc`` is the temperature/conductivity pair (and the salinity derived from it);
stage 3 builds the plain ``ctd_temperature`` / ``ctd_salinity`` / ``conductivity`` (and, for
``oxygen``, ``ctd_oxygen``) as a per-cast copy of the selected channel and records the chosen sensor in
``sensor_<role>_preferred``.

.. code-block:: yaml

   preferred_sensor:
     tc:                             # temperature + conductivity + salinity move together
       default: primary              # cruise-wide; "primary" | "secondary"
       ranges:                       # exceptions by cast number; [[first, last]] inclusive
         - casts: [[31, 60]]
           value: secondary
     oxygen:                         # independent oxygen choice, same grammar
       default: primary
       ranges:
         - casts: [[15, 15]]         # a single-cast range is valid
           value: secondary

Notes:

* Values are exactly ``primary`` / ``secondary`` — a digit or any other spelling is refused at
  stage 3 (a clear error, not a silent guess).  A single-sensor cast has no choice and is left
  untouched; an undeclared dual cast gets no plain name (never a silent ``_1``).
* ``casts`` needs an explicit last number (no open-ended range).  So declare the **latest /
  ongoing** configuration as the unbounded ``default`` and the **earlier** casts as explicit
  ``ranges`` — then the config need not be edited as new casts are added.
* Declaring one, both, or neither is valid, and ``oxygen`` may differ from ``tc``.  An **explicit
  range** naming a channel a single-sensor cast lacks is an error; a **default** that lands on a
  single-sensor cast is silently skipped.
* Where the per-cast serials of a declared range do not match where the hardware actually changed,
  the compile and ``ctdcast validate`` warn (never block) — reconcile the range with the
  sensor-change log on the cast page.

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
