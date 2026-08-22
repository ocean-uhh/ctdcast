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

Cruise metadata (``cruise_info``)
---------------------------------

The optional top-level ``cruise_info:`` block in ``config.yaml`` supplies the
cruise-level metadata written into the **compiled files** (``profiles.nc`` and
``ladcp_profiles.nc``) as ACDD-1.3 global attributes — discovery fields, people,
platform, access policy — plus the EXPOCODE. The same block also feeds the report
page headers. Everything in it is optional: a config without it still builds, just
without the extra metadata.

Coverage bounds (``geospatial_*``, ``time_coverage_*``) and ``date_created`` are
**computed from the data** at write time and are never authored here.

.. note::

   YAML is indentation-sensitive and this block is easy to get wrong by hand
   (mismatched indent, a missing ``-`` on a list item, a stray second
   ``cruise_info:``). ``ctdcast init --interactive`` can build the block for you,
   including offering the controlled list of contributor roles, and ``ctdcast
   validate config.yaml`` checks it (delimiters, roles, ORCIDs, duplicate keys)
   before you process anything.

.. code-block:: yaml

   cruise_info:
     cruise_id: ab2026               # page headers + the file's `cruise` attribute
     ship: "RV Example"              # free-text display name in the report masthead
     platform: odb                   # platforms.yaml slug -> ICES code for the EXPOCODE
     project: "Example Project"

     start_date: 2026-07-09          # DEPARTURE from port (feeds the EXPOCODE), not first cast
     end_date: 2026-07-31            # drives the default embargo release date

     # Who produced the file (singular; ACDD creator_*). Not a PI list.
     creator:
       name: "Jane Doe"
       type: person                  # person | group | institution | position
       orcid: null                   # bare id or orcid.org URL

     # Everyone with a named role. Each person appears ONCE; a role may apply to
     # every file or to one product. Written as semicolon-separated parallel
     # strings, so no value may contain ';' or ','.
     contributors:
       - name: "Jane Doe"
         orcid: null
         roles: [PS, PI]             # both roles, on every compiled file
       - name: "John Smith"
         orcid: null
         role: PI                    # shorthand for roles: [PI]
       - name: "Sam Rivera"
         orcid: null
         roles:
           all: [PI]                 # every compiled file
           ctd: [MC]                 # profiles.nc only
           ladcp: [DI]               # ladcp_profiles.nc only

     acknowledgement: >
       Funding text, written verbatim into the `acknowledgement` attribute.

     # An embargo is NOT a licence. CC BY is irrevocable, so it is named only as
     # the licence that applies ON RELEASE; during the embargo `license` is a
     # self-describing moratorium statement.
     embargo:
       policy: "SDN:L08::MO"         # NERC L08 moratorium
       until: 2028-07-31             # null -> derived as end_date + 2 years
       contact: null                 # PI email for access requests
     license_after_embargo: "CC-BY-4.0"

Contributors follow the two compiled products, but the scoping lives on the
**role**, not on a separate list. A role under ``all:`` (or a bare ``role:`` /
``roles: [...]``) is written to both ``profiles.nc`` and ``ladcp_profiles.nc``;
a role under ``ctd:`` or ``ladcp:`` is written only to that product's file. So
whoever processed the CTD never appears on the LADCP file and vice versa, while
someone who worked on both is listed once with a role under each key.

A person with no role in a given scope is absent from that file entirely. An
unrecognised scope key is a validation error, since a typo would otherwise drop
someone silently.

Field reference:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Key
     - Meaning
   * - ``cruise_id``
     - Cruise identifier. Written to the file as ``cruise`` — the key name is
       not itself an attribute — and used in the page headers. Falls back to the
       per-cast netCDF ``cruise`` attribute, then ``"UNK"``.
   * - ``ship``
     - Free-text display name shown in the report masthead.
   * - ``platform`` (or ``ship_slug``)
     - The vessel, resolved to the ICES code for the EXPOCODE and the
       ``platform_*`` attributes. Either a slug in ``platforms.yaml`` (e.g.
       ``odb``, ``msm``), **or** — for a vessel not in the registry — an inline
       mapping with at least ``ices_code`` (look up your ship at
       https://ocean.ices.dk/codes/ShipCodes.aspx , or the NVS mirror
       https://vocab.nerc.ac.uk/collection/C17/current/) and ``name``, plus
       optional ``platform_vocabulary``::

           platform:
             name: "RV Example"
             ices_code: "XXXX"
             platform_vocabulary: "https://vocab.nerc.ac.uk/collection/L06/current/31/"

       Never the free-text ``ship`` name — name lookup is ambiguous.
   * - ``start_date`` / ``end_date``
     - Cruise dates. ``start_date`` is the **departure from port** (feeds the
       EXPOCODE ``<ICES code><YYYYMMDD>``), which may precede the first cast.
   * - ``creator``
     - Mapping describing who produced the file (ACDD ``creator_*``). Singular:
       ``name``, ``type``, ``email``, ``orcid``. No ``institution`` — institutions
       are named only in ``institutions``, and the creator's ORCID already
       resolves to their affiliation. Setting it warns.
   * - ``contributors``
     - Ordered list of people, each appearing **once**, with ``name`` and either
       ``role`` (one role), ``roles: [...]`` (several) or ``roles: {all, ctd,
       ladcp}`` (scoped per product); optional ``email`` and ``orcid`` (bare or
       URL). Each ``(person, role)`` pair becomes one position in the parallel
       strings. ``institution`` is **not** accepted here — see ``institutions``.
   * - ``institution``
     - **Not a config key** — setting it is a validation error. The CF
       ``institution`` attribute ("where the original data was produced") is
       *derived* from the entries of ``institutions`` holding the lead role
       (``CONLEAD``), joined with ``"; "``. It is a lossy view of
       ``contributing_institutions``, kept for CF-only consumers (ERDDAP,
       THREDDS, NCEI) that never read the structured form; the list stays the
       single source of truth, so the two cannot disagree. It is deliberately
       **not** reduced to one organisation: a cruise really does have several
       contributing institutions, and only the authorship of a particular file
       resolves to one — and that one is not written as an attribute at all,
       because the creator's ORCID (``creator_id``) already resolves to their
       current affiliation. Nothing holding ``CONLEAD`` means the attribute is
       omitted, with a warning from ``ctdcast validate``.
   * - ``institutions``
     - Ordered list of contributing institutions, written to
       ``contributing_institutions``. Each entry is either an
       ``institutions.yaml`` slug (optionally ``{slug: uhh, role: CONLEAD}``),
       **or** — for one not in the registry — an inline
       ``{name, id, role}`` (look up the EDMO code at
       https://edmo.seadatanet.org/ , or use a ROR id). Roles: ``CONLEAD``
       (leads), ``CONMEM`` (takes part), ``FUND`` (funder). Independent of
       ``contributors``: one person may sit at several institutions and one
       institution may send several people, so the two lists are **not**
       positionally aligned.
   * - ``role_vocabulary``
     - Which vocabulary the roles are drawn from — ``C89`` (default, BODC
       dataset roles) or ``G04`` (ISO 19115 ``CI_RoleCode``). ctdcast validates
       and writes in the declared vocabulary and never converts between them.
   * - ``acknowledgement``
     - Free text written to the ``acknowledgement`` global attribute.
   * - ``embargo``
     - Mapping (``policy``, ``until``, ``contact``). Produces a moratorium
       ``license``; ``until`` defaults to ``end_date + 2 years`` when null.
   * - ``license_after_embargo``
     - The licence that applies on release (e.g. ``CC-BY-4.0``).

Contributor roles come from **NERC C89** (BODC dataset roles), given as the
concept code or the full prefLabel. The cruise-scoped terms are ``PS`` (Cruise
principal scientist — the chief scientist, and the definition allows the role to
be shared), ``DI`` (Cruise dataset principal investigator — responsible for one
subset of the cruise data), ``MC`` (Cruise data manager), ``TC`` (Cruise
technical contact), ``TS`` (Cruise technician) and ``CP`` (Cruise participant).
The project-scoped terms are ``PI``, ``CI``, ``CO``, ``DP``, ``MP``, ``PM``,
``PA``, ``PD``, ``PG`` and ``RA``; ``DM`` and ``DC`` are unscoped. Any other
value is a validation error.

A contributor may hold several roles, and a role may be scoped to one product::

   contributors:
     - name: "Jane Doe"
       orcid: https://orcid.org/0000-0000-0000-0000
       roles: [PS, PI]            # both roles, on every compiled file

     - name: "Sam Rivera"
       orcid: null
       roles:
         all: [PI]                # every file
         ctd: [DC]                # profiles.nc only
         ladcp: [DI]              # ladcp_profiles.nc only

Each ``(person, role)`` pair occupies one position in the parallel attribute
strings, so a two-role person appears twice in the netCDF with their name and
ORCID repeated. Stating them once in config is what guarantees the repeats
agree. A person with no role in a given scope is absent from that file.

``cruise_info.role_vocabulary`` selects the vocabulary: ``C89`` (default) or
``G04`` (ISO 19115 ``CI_RoleCode``, for a file that must satisfy an IOOS or ISO
checker). ctdcast never converts between them — any mapping is lossy, and the
file could not record that the detail was dropped.

Shared registries
~~~~~~~~~~~~~~~~~~~

Two package files back the slugs above, in the same spirit as
``sbe_sensors.yaml``:

- ``ctdcast/config/platforms.yaml`` — vessels keyed by slug, each with its ICES
  code, L06 platform category, and identity fields. It also carries
  ``forbidden_codes`` and ``ambiguous_slugs`` guards, so a deprecated or
  ambiguous code (e.g. bare ``meteor``) raises rather than silently producing a
  wrong EXPOCODE.
- ``ctdcast/config/institutions.yaml`` — institution slugs (e.g. ``uhh``) mapping
  to the EDMO name written to ``contributing_institutions`` and the EDMO/ROR
  record URI written to ``contributing_institutions_id``.

----

ctd_sections.yaml
-----------------

This file defines two kinds of cast group under two top-level keys: ``sections``
(named transects plotted as a vertical section against distance) and
``timeseries`` (repeat stations plotted against time — see below).

An optional ``cruise_info:`` block at the top level provides cruise and ship
metadata that appears in page headers and footers.  Values here take precedence
over any cruise metadata found in the netCDF file attributes:

.. code-block:: yaml

   cruise_info:
     cruise_id: msm142          # shown in every page header and footer
     ship: "Maria S. Merian"    # shown in page masthead

Both keys are optional.  If absent, the report falls back to the ``cruise``
attribute of the first netCDF file (defaulting to ``"odb2026"`` if that
attribute is not set), and ship shows as ``"UNK"``.

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
