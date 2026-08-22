.. _cruise_metadata:

=================================
Cruise metadata (``cruise_info``)
=================================

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
