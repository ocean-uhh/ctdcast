"""ctdcast's concrete report stylesheet, from the package-neutral ``emit_css``.

This is the package-specific wiring the vendored :mod:`ctdcast.reports._css`
deliberately omits: the single place ctdcast's name is applied to the shared
generator.  Another package supplies its own name the same way; the vendored
``_css.py`` carries no package-specific edit.
"""

from __future__ import annotations

from ctdcast.reports._css import _JS_TOP_LINKS, emit_css

#: The generated stylesheet, ready to concatenate into a page ``<style>`` block.
SHARED_CSS: str = emit_css("ctdcast")

__all__ = ["SHARED_CSS", "_JS_TOP_LINKS"]
