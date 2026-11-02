"""The corrections page for temperature and salinity: alignment and cell thermal mass fits.

Drawn from the ``fits.nc`` file ``ctdcast fit`` writes under the CTD root: a summary table and the
suggested ``processing:`` block, then the figures — the cruise alignment wells and the per-cast
alignment, the cell thermal mass casts and cost surface, and the fits for blocks of consecutive
casts.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis import fits as F
from ctdcast.plotters.corrections import (
    draw_alignment_fig,
    draw_alignment_hist_fig,
    draw_alignment_wells_fig,
    draw_blocks_fig,
    draw_ctm_casts_fig,
    draw_ctm_param_hist_fig,
    draw_ctm_surface_fig,
)
from ctdcast.processors.fit import LineSummary, suggested_yaml, summarise
from ctdcast.reports._env import get_template
from ctdcast.reports._figdebug import render_b64
from ctdcast.reports._format import report_generated_at
from ctdcast.reports._navs import CORRECTIONS_TS_HREF, nav_for
from ctdcast.reports._vendored.design_tokens import W_FULL, W_HALF
from ctdcast.reports.design import _JS_TOP_LINKS, SHARED_CSS

_NAMES = {1: "primary", 2: "secondary"}


def _summary_rows(
    fits: xr.Dataset, summaries: list[LineSummary]
) -> list[dict[str, str]]:
    deck = (
        fits["deck_advance"].values
        if "deck_advance" in fits
        else np.full(fits.sizes["line"], np.nan)
    )
    rows = []
    for s in summaries:
        base = float(deck[s.line - 1]) if np.isfinite(deck[s.line - 1]) else 0.0

        def _f(v: float, fmt: str) -> str:
            return "–" if not np.isfinite(v) else format(v, fmt)

        rows.append(
            {
                "line": _NAMES[s.line],
                "advance": _f(s.residual + base, ".4f"),
                "advance_up": _f(s.residual_up + base, ".4f"),
                "align_n": str(s.alignment_n),
                "ctm": "–"
                if not np.isfinite(s.alpha_rec)
                else f"({s.alpha_rec:g}, {s.tau_rec:g})",
                "alpha_at_tau": _f(s.alpha_at_tau, "g"),
                "tau_at_alpha": _f(s.tau_at_alpha, "g"),
                "ctm_n": str(s.ctm_n),
            }
        )
    return rows


def generate_corrections_page(
    fits_path: Path,
    out_path: Path,
    *,
    cruise: str = "",
    nav_prefix: str = "",
    inventory_pills: list[dict[str, str]] | None = None,
    generated_at: str | None = None,
) -> Path:
    """Render ``corrections_ts.html`` from a ``fits.nc`` file.

    Parameters
    ----------
    fits_path : pathlib.Path
        The ``fits.nc`` written by ``ctdcast fit``.
    out_path : pathlib.Path
        The HTML file to write; parent directories are created.
    cruise : str, optional
        Cruise identifier for the title.
    nav_prefix : str, optional
        Relative path to the report root for the page-nav links.
    inventory_pills : list of dict, optional
        The pills from :func:`ctdcast.reports._navs.inventory_pills`, including this page's.
    generated_at : str, optional
        Page build stamp; ``None`` uses the current UTC time.

    Returns
    -------
    pathlib.Path
        The written *out_path*.
    """
    with xr.open_dataset(fits_path, engine="netcdf4") as ds:
        fits = ds.load()
    summaries = summarise(fits)
    figs = {
        name: render_b64(
            draw,
            fits,
            width_in=w,
            optional=True,
            source=f"corrections.py:{draw.__name__}",
        )
        for name, draw, w in (
            ("wells", draw_alignment_wells_fig, W_FULL),
            ("alignment", draw_alignment_fig, W_FULL),
            ("align_hist", draw_alignment_hist_fig, W_HALF),
            ("ctm_casts", draw_ctm_casts_fig, W_FULL),
            ("ctm_surface", draw_ctm_surface_fig, W_FULL),
            ("ctm_hist", draw_ctm_param_hist_fig, W_HALF),
            ("blocks", draw_blocks_fig, W_FULL),
        )
    }
    not_fitted = (
        fits["not_fitted"].values if "not_fitted" in fits else [""] * fits.sizes["cast"]
    )
    skipped = [
        (str(c), str(r or nf))
        for c, r, nf in zip(
            fits["cast_id"].values, fits["skipped"].values, not_fitted, strict=True
        )
        if r or nf
    ]
    speed = fits["speed"].values if "speed" in fits else np.full((1, 2), np.nan)
    with np.errstate(invalid="ignore"):
        speeds = [
            "–"
            if not np.isfinite(speed[:, leg]).any()
            else f"{np.nanmedian(speed[:, leg]):.2f}"
            for leg in (0, 1)
        ]
    nav = nav_for(
        None,
        prefix=nav_prefix,
        inventory=inventory_pills or (),
        inventory_current=CORRECTIONS_TS_HREF,
    )
    html = get_template("corrections_ts.html").render(
        page_title=f"T/S corrections — {cruise}" if cruise else "T/S corrections",
        cruise=cruise,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav=nav,
        nav_prefix=nav_prefix,
        masthead_role="aggregate-a",
        version=_VERSION,
        generated_at=report_generated_at(generated_at),
        source=fits_path.name,
        n_casts=int(fits.sizes["cast"]),
        n_skipped=len(skipped),
        skipped=skipped,
        pmin=float(fits.attrs.get("ctm_pmin_dbar", F.DEFAULT_CTM_PMIN)),
        gradient=float(
            fits.attrs.get("alignment_gradient_degC_per_dbar", F.DEFAULT_GRADIENT)
        ),
        block=int(fits.attrs.get("block", 10)),
        align_pmin=float(fits.attrs.get("alignment_pmin_dbar", F.DEFAULT_ALIGN_PMIN)),
        min_speed=float(
            fits.attrs.get("alignment_min_speed_dbar_per_s", F.DEFAULT_MIN_SPEED)
        ),
        speed_down=speeds[0],
        speed_up=speeds[1],
        fit_created=str(fits.attrs.get("date_created", "")),
        rows=_summary_rows(fits, summaries),
        yaml=suggested_yaml(summaries) if summaries else "",
        figs=figs,
        sbe_alpha=F.DEFAULT_ALPHA_SBE,
        sbe_tau=F.DEFAULT_TAU_SBE,
        valley_pct=round(F.VALLEY_FRACTION * 100),
        tol_pct=round(float(fits.attrs.get("ctm_tolerance", 0.02)) * 100),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
