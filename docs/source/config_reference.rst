.. _config_reference:

=================
Configuration reference
=================

ctdcast is configured through two YAML files: ``config.yaml`` (run-level settings) and
``ctd_sections.yaml`` (section definitions).

----

config.yaml
-----------

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

Example
~~~~~~~

.. code-block:: yaml

   data:
     nc_dir:       /data/cruise/CTD/cnv_nc
     profiles_nc:  /data/cruise/CTD/profiles.nc
     section_yaml: /data/cruise/config/ctd_sections.yaml
     gebco_nc:     /data/GEBCO_2025.nc

   output:
     dir: /data/cruise/report

   generate:
     stations:   true
     sections:   true
     timeseries: true
     force:      false

----

ctd_sections.yaml
-----------------

This file defines named transects — groups of casts that are plotted together as a
vertical section.

Top-level key: ``sections``

Each entry under ``sections`` is a named transect with the following fields:

.. list-table::
   :header-rows: 1
   :widths: 20 10 70

   * - Key
     - Required
     - Description
   * - ``description``
     - no
     - Human-readable label shown in the section card and page header.
   * - ``color``
     - no
     - Hex colour used for the transect line on the cruise-track map (e.g.
       ``"#e41a1c"``).
   * - ``cast_numbers``
     - yes
     - List of casts belonging to this section.  Each item is either an integer
       (single cast), a two-element list ``[first, last]`` (inclusive range), or
       a quoted string such as ``"10b"`` naming a lettered sibling cast.  An
       integer or range selects the plain casts only; a lettered sibling (a
       second event occupied at the same station number, from a ``NNNb`` or
       ``NNN_b`` file) must be named explicitly as a string.  Order is preserved
       as written, so casts may be listed in geographic order.
   * - ``key_cast``
     - no
     - A single cast (integer, or a ``"NNNb"`` string) that anchors the section
       x-axis.  When set, casts are ordered by geographic distance from this cast
       and the x-axis is distance-from-key (``0`` at the key cast).  When unset
       (the default), casts keep the order written in ``cast_numbers`` and the
       x-axis is cumulative along-track distance from the first listed cast.  Use
       ``key_cast`` set to a **geographic endpoint** of the transect when the
       station was occupied out of cast-number order, so the section does not
       fold back on itself.  Must be one of the section's ``cast_numbers``.

The two ordering modes
~~~~~~~~~~~~~~~~~~~~~~~~

- **Default (no ``key_cast``):** list the casts in geographic order in
  ``cast_numbers``; the x-axis is cumulative along-track distance in that order.
- **``key_cast`` set:** the written order does not matter — casts are sorted by
  distance from the key cast and the x-axis is that distance.  Fold-free as long
  as the key cast sits at one end of the transect.

Example
~~~~~~~

.. code-block:: yaml

   sections:
     KTout:
       description: "Kögur Transect outflow"
       color: "#e41a1c"
       cast_numbers: [[1, 12], 15]

     FARDWO:
       description: "FARDWO mooring array"
       color: "#377eb8"
       cast_numbers: [[20, 35]]
       key_cast: 20               # x-axis = distance from cast 20 (a transect end)

     SingleStation:
       description: "Test cast at mooring site"
       color: "#4daf4a"
       cast_numbers: [42]

     WithSibling:
       description: "Line including a repeat occupation at station 10"
       color: "#984ea3"
       cast_numbers: [[9, 12], "10b"]   # plain 9-12 plus the 10b sibling event

----

Input netCDF format
-------------------

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
   * - ``temperature_1``
     - In-situ temperature in °C (ITS-90).
   * - ``salinity_1``
     - Practical salinity (PSU).
   * - ``oxygen_1``
     - Dissolved oxygen in percent saturation.
   * - ``fluorescence``
     - Fluorescence (arbitrary instrument units).
   * - ``turbidity``
     - Turbidity (arbitrary instrument units).

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
   * - ``cast_type``
     - ``"down"`` or ``"up"``.
   * - ``latitude``
     - Latitude in decimal degrees north.
   * - ``longitude``
     - Longitude in decimal degrees east.
   * - ``time_start``
     - Start time of the cast (datetime64).
   * - ``time_end``
     - End time of the cast (datetime64).
   * - ``temperature_1``
     - In-situ temperature on the 1 dbar grid.
   * - ``salinity_1``
     - Practical salinity on the 1 dbar grid.
   * - ``oxygen_1``
     - Dissolved oxygen (percent saturation) on the 1 dbar grid.
