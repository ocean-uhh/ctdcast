"""Shared report layer, vendored byte-identical across sibling packages.

The modules in this directory (``design_tokens``, ``figure_png``, ``css``,
``page_model``, the ``templates`` and ``leaflet`` assets) are the shared report
presentation layer used by ctdcast, oceanarray and glidertest. They are kept
byte-identical across the three repositories.

ctdcast ``main`` is the source of truth. An edit is made here in ctdcast and
re-vendored out to the siblings (see ``README.md`` for the recipe); it is never
edited in a consumer repository. ``scripts/check_vendored.py`` is the gate that
hashes this directory against ``VENDORED.txt`` and the siblings.

This package re-exports nothing: a consumer imports the specific module it
needs (``from ...reports._vendored import design_tokens``), so each dependency
is visible at its import site.
"""
