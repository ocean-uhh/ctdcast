"""Configuration file for the Sphinx documentation builder."""

import datetime

year = datetime.datetime.now(tz=datetime.timezone.utc).date().year

project = "ctdcast"
author = "Eleanor Frajka-Williams"
copyright = f"{year}, {author}"
release = "v0.1.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.mathjax",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build"]
pygments_style = "sphinx"

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["css/custom.css"]
html_logo = "_static/ctdcast.png"

source_suffix = [".rst", ".md"]
