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
     - ``cnv_dir``, ``ladcp_dir``, ``gebco_nc``, ``groupings_yaml``
   * - Output roots — created and written by ctdcast
     - ``ctd_root``, ``ladcp_root``

Reading raw Sea-Bird ``.hex`` is planned; it will arrive as a further input key
(``hex_dir``) beside ``cnv_dir``, not as a change to the roots.

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
       reads.  Required to run stage 1.
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
   * - ``force``
     - ``false``
     - If ``true``, regenerate all pages even if they already exist.

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
       turbidity:
         sensor_model: "WET Labs ECO FLNTU(RT)D"
         sensor_model_vocabulary: "https://vocab.nerc.ac.uk/collection/L22/current/TOOL1531/"
     aliases:
       "3508": "FLNTURTD-3508"          # one device recorded under two serial spellings

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
