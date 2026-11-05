.. ctdcast documentation master file

=====================================================================
ctdcast: processing and reports for shipboard CTD and LADCP data
=====================================================================

**ctdcast** takes shipboard CTD data from the raw Sea-Bird files to a compiled, documented
dataset and a set of self-contained HTML reports:

- **Processing** — the raw ``.hex`` (with its ``.xmlcon``) or ``.cnv`` is read to netCDF
  (stage 1), the surface soak and deck records are flagged (stage 2), and Sea-Bird's processing
  steps, calibration and QC are applied (stage 3), with products such as 1 dbar averages made
  from the result. Every step and its parameters are recorded in the files. LADCP profiles are
  converted alongside.
- **profiles.nc** — the casts compiled on a common pressure grid, with CF and CCHDO variable
  names, the sensor catalog and each cast's processing record.
- **Reports** — HTML pages that work fully offline at sea (every figure embedded, no external
  requests): a summary page and map, a page per cast, section and time-series pages for the
  groups of casts you define, an interactive map, the sensors used, every processing step by
  run of casts, and an inventory of each compiled file.

The pages are described in :doc:`report_output`, the files in :doc:`data_files`, and the stages
in :doc:`processing_framework`.

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   quickstart
   demo
   Demo report <https://ocean-uhh.github.io/ctdcast/_static/demo/index.html>

.. toctree::
   :maxdepth: 2
   :caption: Concepts

   processing_framework
   provenance_roadmap

.. toctree::
   :maxdepth: 2
   :caption: Configuration

   config_yaml
   cruise_metadata
   ctd_groupings
   registries

.. toctree::
   :maxdepth: 2
   :caption: Outputs

   data_files
   report_output

.. toctree::
   :maxdepth: 2
   :caption: Interfaces

   cli_reference
   api

.. toctree::
   :maxdepth: 1
   :caption: Development and releases

   development
   migrating_0_4_0

.. toctree::
   :maxdepth: 1
   :caption: Links

   GitHub repository <https://github.com/ocean-uhh/ctdcast>


Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
