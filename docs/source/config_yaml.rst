.. _config_yaml:

===========
config.yaml
===========

``data`` block
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 10 70

   * - Key
     - Required
     - Description
   * - ``nc_dir``
     - yes
     - Path to a directory of per-cast netCDF files (one ``.nc`` per cast).
   * - ``profiles_nc``
     - no
     - Path to the compiled ``profiles.nc`` file on a 1 dbar grid.  Required for
       section and time series pages.
   * - ``section_yaml``
     - no
     - Path to the ``ctd_sections.yaml`` file defining transect groups.  Required
       for section pages.
   * - ``gebco_nc``
     - no
     - Path to a GEBCO NetCDF bathymetry file.  Maps render without bathymetry if
       this is omitted or the file is not found — not an error.

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
     - Generate transect section pages.  Requires ``profiles_nc`` and
       ``section_yaml``.
   * - ``timeseries``
     - ``true``
     - Generate the cruise-wide time series page.  Requires ``profiles_nc``.
   * - ``force``
     - ``false``
     - If ``true``, regenerate all pages even if they already exist.

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
     section_yaml: /data/cruise/config/ctd_sections.yaml
     gebco_nc:     /data/GEBCO_2025.nc

   output:
     dir: /data/cruise/report

   generate:
     stations:   true
     sections:   true
     timeseries: true
     force:      false
