"""Jinja2 environment factory for ctdcast report templates.

Two environments are required:

- ``_env`` (autoescape=True) — for the seven HTML report pages where all
  context values must be escaped.  Use ``get_template()`` on this instance.
- ``_env_raw`` (autoescape=False) — for ``leaflet.html`` only, which embeds
  Leaflet JS and raw GeoJSON that must not be escaped.

Both load templates from the ``templates/`` subdirectory of this package.

Usage::

    from ctdcast.reports._env import get_template, get_template_raw
    html = get_template("index.html").render(**ctx)
    html = get_template_raw("leaflet.html").render(**ctx)
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env: Environment = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=True,
)

_env_raw: Environment = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=False,
)


def get_template(name: str) -> Template:
    """Return an autoescaped Jinja2 template by filename."""
    return _env.get_template(name)


def get_template_raw(name: str) -> Template:
    """Return a non-autoescaped Jinja2 template by filename (leaflet only)."""
    return _env_raw.get_template(name)
