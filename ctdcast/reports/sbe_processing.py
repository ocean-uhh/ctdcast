"""A page showing a CNV's SBE Data Processing steps and the equivalent ``data_processing:`` block.

Written by ``ctdcast inspect <file>.cnv -o page.html``: the modules in the order they ran, each
with the parameters the header records, and the block to paste into the config, with a copy
button.  Self-contained, like every ctdcast page.
"""

from __future__ import annotations

from pathlib import Path

from ctdcast._version import __version__ as _VERSION
from ctdcast.config.cnv_header import (
    _module_date_parts,
    parse_processing_chain,
    stacked_advances,
)
from ctdcast.config.sbe_steps import header_text_of, processing_yaml
from ctdcast.reports import design
from ctdcast.reports._env import get_template
from ctdcast.reports._format import report_generated_at

__all__ = ["generate_sbe_processing_page"]

# Fields that say where a module read its input, not how it processed it.
_NOT_PARAMETERS = ("date", "in")


def generate_sbe_processing_page(
    cnv_path: Path,
    out_path: Path,
    *,
    title: str | None = None,
    generated_at: str | None = None,
) -> Path:
    """Render a CNV's SBE Data Processing steps and its ``data_processing:`` block to *out_path*.

    Parameters
    ----------
    cnv_path : pathlib.Path
        The Sea-Bird CNV.
    out_path : pathlib.Path
        Destination HTML path (parent directories are created).
    title : str, optional
        Page title; defaults to the file name.
    generated_at : str, optional
        Page build stamp; ``None`` uses the current UTC time.

    Returns
    -------
    pathlib.Path
        The written *out_path*.
    """
    header = header_text_of(cnv_path)
    stacked = stacked_advances(header)
    steps = [
        {
            "module": s.module,
            "run": _module_date_parts(s.params),
            "amber": s.module.casefold() == "alignctd" and bool(stacked),
            "params": [
                (k, v) for k, v in s.params.items() if k.lower() not in _NOT_PARAMETERS
            ],
        }
        for s in parse_processing_chain(header).steps
    ]
    html = get_template("sbe_processing.html").render(
        page_title=title or cnv_path.name,
        filename=cnv_path.name,
        steps=steps,
        stacked=[st.sentence() for st in stacked],
        yaml=processing_yaml(header),
        cruise="",
        css=design.SHARED_CSS,
        js_top_links=design._JS_TOP_LINKS,
        nav_prefix="",
        nav=None,
        masthead_role="component",
        version=_VERSION,
        generated_at=report_generated_at(generated_at),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
