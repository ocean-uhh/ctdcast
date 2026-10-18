Migrating to 0.4.0
==================

0.4.0 changes two output attributes, drops Python 3.10, and renames one public
function. This page lists what changed, whether you must reprocess, and one
worked example.

What changed
------------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Was
     - Now
     - Where
   * - ``label_units`` (variable attribute and registry column)
     - derived from ``units`` by ``config.unit_tables.unit_label``
     - every netCDF variable; ``config.parameters.VARIABLES``
   * - ``cnv_original_name`` (CNV), ``source_variable`` (LADCP)
     - ``original_name``
     - every variable's source-name attribute
   * - ``config.sensors.sanitize_serial``
     - ``config.sensors.serial_slug``
     - public function (old name deprecated, removed in 0.5.0)
   * - Python 3.10 supported
     - Python 3.11–3.14 (3.14 allowed to fail in CI)
     - ``requires-python = ">=3.11"``

Reading old files still works: ``original_name`` is read with ``cnv_original_name``
and ``source_variable`` as fallbacks, so a file written before 0.4.0 is read
without change. The ``label_units`` attribute on an old file is ignored (the
display unit is derived from ``units``).

Do I need to reprocess?
-----------------------

Only to change what is *written*. Nothing is read incorrectly from an old file.

- **Reports from existing stage files** — no reprocessing. The inventory and
  axes read ``original_name`` (falling back to the old attributes) and derive the
  display unit from ``units``.
- **To drop ``label_units`` and write ``original_name`` into the files** — re-run
  the pipeline (``ctdcast process config.yaml --stage 1 2 3 profiles --force``).
  The units strings on disk do not change for files ctdcast already wrote (they
  were already canonical); what changes is that ``label_units`` is gone and the
  source name is ``original_name``.

A reader that keyed off the old attribute names must be updated:

.. code-block:: python

   # Before 0.4.0
   source = ds["ctd_salinity_1"].attrs.get("cnv_original_name")   # "sal00"
   display = ds["ctd_salinity_1"].attrs["label_units"]            # "PSU"

   # 0.4.0
   from ctdcast.config.unit_tables import unit_label

   source = ds["ctd_salinity_1"].attrs.get("original_name")       # "sal00"
   display = unit_label(
       ds["ctd_salinity_1"].attrs.get("units", ""),               # "1"
       ds["ctd_salinity_1"].attrs.get("standard_name"),           # sea_water_practical_salinity
   )                                                              # "PSU"

Units are now canonicalised at the write boundary
-------------------------------------------------

``processors.units.to_canonical_units`` runs as each stage file is written: a
recognised non-canonical spelling is rewritten to its canonical form, and its
values are converted when the conversion factor is not 1 (``S/m`` → ``mS cm-1``,
×10). A spelling the tables do not recognise raises ``UnitsError`` and stops the
run rather than being silently stamped over. For files ctdcast already wrote this
is a no-op — they were already canonical — but a file from another reader is now
checked, not assumed.

Deprecated, removed in 0.5.0
----------------------------

The config ``data:`` key ``section_yaml`` still works but emits a
``DeprecationWarning``; rename it to ``groupings_yaml`` (the file holds both
``sections:`` and ``timeseries:``). The ``section_yaml`` fallback and the retired
``#s-*`` page-anchor aliases are both removed in 0.5.0.
