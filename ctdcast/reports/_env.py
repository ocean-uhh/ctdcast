"""Jinja2 environment factory for ctdcast report templates.

Two environments are required:

- ``_env`` (autoescape=True) — for the seven HTML report pages where all
  context values must be escaped.  Use ``get_template()`` on this instance.
- ``_env_raw`` (autoescape=False) — for ``leaflet.html`` only, which embeds
  Leaflet JS and raw GeoJSON that must not be escaped.

Both load templates from the owned ``templates/`` subdirectory first, then the
vendored ``_vendored/templates/`` (so ``_nav.html`` and other shared partials
resolve); an owned template shadows a vendored one of the same name.

Usage::

    from ctdcast.reports._env import get_template, get_template_raw
    html = get_template("index.html").render(**ctx)
    html = get_template_raw("leaflet.html").render(**ctx)
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, Template

from ctdcast.reports import _figdebug
from ctdcast.reports._anchors import legacy_anchor_spans

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_VENDORED_TEMPLATES_DIR = Path(__file__).parent / "_vendored" / "templates"

# Owned templates first, then the vendored shared partials (``_nav.html``).
_loader = ChoiceLoader(
    [
        FileSystemLoader(str(_TEMPLATES_DIR)),
        FileSystemLoader(str(_VENDORED_TEMPLATES_DIR)),
    ]
)

_env: Environment = Environment(
    loader=_loader,
    autoescape=True,
)
# Per-figure debug overlay (opt-in via CTDCAST_REPORT_DEBUG); figdbg() returns "" when off,
# so the template macro guarding on it emits nothing in normal builds.
_env.globals["figdbg"] = _figdebug.figdbg
# Legacy anchor shim: emit empty <span id="s-old"> aliases for a rendered section's
# retired anchors so committed deep-links keep resolving.  Returns markup, used with |safe.
_env.globals["legacy_anchor_spans"] = legacy_anchor_spans

_env_raw: Environment = Environment(
    loader=_loader,
    autoescape=False,
)


def get_template(name: str) -> Template:
    """Return an autoescaped Jinja2 template by filename."""
    return _env.get_template(name)


def get_template_raw(name: str) -> Template:
    """Return a non-autoescaped Jinja2 template by filename (leaflet only)."""
    return _env_raw.get_template(name)
