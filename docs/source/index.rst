.. ctdreport documentation master file

==========================================================
ctdreport: HTML reports for shipboard CTD and LADCP data
==========================================================

**ctdreport** generates self-contained HTML report files from shipboard CTD and LADCP data.
All figures are embedded as base64 PNG images — no external requests are made at view time,
so the output files work fully offline on a research vessel.

Three report types are produced:

- **Station pages** — one page per cast, with hydrographic profiles, T-S diagram, and a
  cruise-track map highlighting the cast location.
- **Section pages** — transect sections showing T, S, σ₀, and O₂ across user-defined groups
  of casts.
- **Time series page** — cruise-wide hovmöller diagrams of T, S, and O₂ versus time and
  pressure.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   quickstart

.. toctree::
   :maxdepth: 2
   :caption: Demo

   demo


.. toctree::
   :maxdepth: 2
   :caption: Reference

   cli_reference
   config_reference
   output_structure
   api

.. toctree::
   :maxdepth: 1
   :caption: Links

   GitHub repository <https://github.com/ocean-uhh/ctdreport>


Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
