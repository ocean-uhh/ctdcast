.. _config_reference:

=======================
Configuration reference
=======================

ctdcast is configured through two YAML files: ``config.yaml`` (run-level settings) and
``ctd_sections.yaml`` (section and repeat-station definitions).

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

This file defines two kinds of cast group under two top-level keys: ``sections``
(named transects plotted as a vertical section against distance) and
``timeseries`` (repeat stations plotted against time — see below).

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

Section ordering: the two modes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A section plot places each cast at an x-position along the transect and fills the
space between casts.  How that x-position is computed is what the two modes
control.  The pitfall both modes navigate is **folding**: if consecutive
x-positions do not increase monotonically along the real geographic line, the
section doubles back on itself and the pcolour panels smear across the reversal.

**Mode 1 — config order (default, no ``key_cast``).**
The x-axis is *cumulative along-track distance*: the first cast in ``cast_numbers``
sits at ``x = 0``, and each subsequent cast is placed at the running sum of the
great-circle distance from the previous cast *in the written order*.  So the plot
faithfully walks the casts in the order you list them.

- This is exact when you list the casts in geographic order along the transect
  (which is the natural way to write them).
- It **folds** if you list them out of geographic order — e.g. jumping to a
  mid-line cast and back — because the cumulative path zig-zags.  The casts are
  numbered in the order they were *occupied*, which is not always the order along
  the line, so a section occupied out-and-back or from the middle can fold under
  cast-number order.  The fix is either to reorder ``cast_numbers`` geographically
  or to switch to mode 2.

**Mode 2 — distance from a key cast (``key_cast`` set).**
The written order is ignored.  Each cast's x-position is its *straight-line
great-circle distance from the key cast*, and the casts are sorted by that
distance (``x = 0`` at the key cast).  Because every cast is measured from one
fixed origin, the ordering no longer depends on how ``cast_numbers`` was written.

- This is **fold-free only when the key cast is a geographic endpoint** of the
  transect.  From an endpoint, distance increases monotonically along the line.
- If the key cast sits in the **middle**, casts on opposite sides land at the same
  distance and collapse onto each other — a different kind of fold.  So choose an
  end of the section as ``key_cast``.
- ``key_cast`` also fixes the axis origin and overrides the automatic
  west-left / north-left flip that mode 1 applies; the direction is whichever end
  you anchor to.

When ``init`` auto-detects sections it writes ``key_cast`` as the lowest cast
number in the group — a reasonable draft only if the section was occupied
end-to-end.  Treat the generated file as a starting point: point ``key_cast`` at a
true endpoint, or reorder ``cast_numbers``, for any section that was occupied out
of order.

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

Repeat stations (the ``timeseries`` block)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The same file also defines **repeat stations** — yoyo occupations where a station
is profiled repeatedly at one location — under a second top-level key,
``timeseries``.  A repeat-station page stacks its profiles against **time**, not
along-track distance.

Each entry takes the same fields as a section — ``description``, ``cast_numbers``,
``color`` — with the same ``cast_numbers`` syntax (ints, ``[first, last]`` ranges,
and ``"NNNb"`` sibling strings).

**Repeat stations have a single ordering mode.**  Unlike sections (which have the
two distance-based modes above), a repeat station is always ordered one way:
profiles are sorted by acquisition time (``time_start``), regardless of the order
casts are written in ``cast_numbers``.  There is therefore no ordering knob and no
``key_cast`` — a fixed occupation is one place through time, so there is no
geographic origin to anchor to.

Whether these groups are rendered is controlled by ``generate.timeseries`` in
``config.yaml``.

.. code-block:: yaml

   timeseries:
     FDYY:
       description: "Fardwo — 32-cast repeat station"
       cast_numbers: [[50, 81]]
       color: "#d62728"

     TR700:
       description: "Triangle ~700 m isobath"
       cast_numbers: [128, 129, 130, 132, 135, 137]
       color: "#bcbd22"

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
