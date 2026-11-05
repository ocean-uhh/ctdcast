.. _development:

===================================
Development and debugging switches
===================================

Settings for working on ctdcast itself, or for finding out why a report or a run looks the way it
does. None of them is needed to process a cruise, and ``ctdcast init`` writes none of them.

----

Debugging the reports
---------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Switch
     - What it does
   * - ``CTDCAST_REPORT_DEBUG=1``
       (environment variable)
     - Under every embedded figure, a line naming the page slot, the draw function, the figure
       size in inches and the PNG size in pixels.  Use it to find a figure drawn wider than the
       slot it is shown in, which shrinks its text.  Any value other than empty, ``0``,
       ``false`` or ``no`` turns it on; off, it costs nothing.
   * - ``CTDCAST_UNIT_LABEL_DEBUG=1``
       (environment variable)
     - Adds a ``*`` to every unit label that goes through ctdcast's units layer.  Regenerate a
       report with it set: an axis, colorbar or caption without the star builds its label some
       other way.
   * - ``RAISE_ON_PLOT_ERROR``
       (Python)
     - A figure that fails to draw is normally left out with a warning (most panels also show a
       note on the page saying why).  Set this to raise the error instead, with its traceback:

       .. code-block:: python

          from ctdcast.reports._vendored import design_tokens
          design_tokens.RAISE_ON_PLOT_ERROR = True

       It is read each time a figure is drawn, so set it before calling ``ctdcast.report``.
   * - ``FIGURE_SOURCE``
       (``reports/design.py``)
     - The ``source:`` line under each figure and table, naming the module and function that
       drew it.  On by default in ctdcast.  It is a constant read when the report templates
       load, so turning it off means editing ``FIGURE_SOURCE = False`` in
       ``ctdcast/reports/design.py``.

The shared report layer under ``ctdcast/reports/_vendored/`` is kept byte-identical with ctdcast's
sibling packages; ``python -m ctdcast.reports._vendored.check`` reports any difference from its
manifest.  Change those files only together with the siblings.

----

Processing switches
-------------------

``data_processing.allow_unapplied``
   ``true`` lets stage 3 run when ``data_processing.steps`` lists a Sea-Bird step it has no
   applier for: the step is skipped, named in a warning, in ``history`` and in the stage-3 file's
   ``data_processing_steps``.  The default, ``false``, refuses such a config, because the steps
   after it would run on data that step was meant to change first and the stage-3 file would look
   complete.  Every step ctdcast lists today has an applier, so the switch currently has no
   effect; it is kept for a step added to the table before its applier.  ``split`` and
   ``binavg`` listed under ``steps`` (instead of in a product) are refused either way.

``CTDCAST_CONFIG_DIR``
   The per-user folder the institution and platform registries are read from (default
   ``~/.config/ctdcast``); see :doc:`registries`.

----

The demo report
---------------

``scripts/make_demo.py`` rebuilds the published demo in ``docs/source/_static/demo/`` from the
committed fixture casts, writing its stage files to a temporary folder.  Run it from the repository
root after a change to the report pages, and commit the result:

.. code-block:: bash

   python scripts/make_demo.py

``ctdcast run config_demo.yaml --stage profiles`` builds the same report locally, into
``demo_report/``, with the compiled file in ``demo_work/``.
