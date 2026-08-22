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

Global attributes used: ``raw_filename``, ``cruise``.

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
   * - ``expocode``
     - The cruise EXPOCODE, per profile. A file may hold more than one cruise, so
       CCHDO stores this per profile rather than as a global attribute, and
       ctdcast follows that.
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
