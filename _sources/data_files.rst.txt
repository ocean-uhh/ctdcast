.. _data_files:

===================
Data files (netCDF)
===================

Per-cast files (``nc_dir``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

Profiles file (``profiles_nc``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Compiled on a 1 dbar pressure grid, dimensions ``N_PROF × pressure``:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Name
     - Description
   * - ``cast_number``
     - Integer cast number.
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
