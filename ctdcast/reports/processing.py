"""Tier-2: the cruise "Processing" page — every step applied, over which casts.

Reads the per-profile ``processing_record`` that
:func:`ctdcast.processors.profiles.build_profiles` writes into ``profiles.nc`` (one JSON list of
steps per cast, from :mod:`ctdcast.analysis.processing_record`) and draws, per stage, one row per
run of consecutive casts that used the same setting.  A step whose setting changes more than
:data:`VARIES_AFTER` times is drawn as one "varies cast to cast" row with the range of its values
and a figure.  A row whose setting differs from SBE's documented value is amber.  What a step did
on one cast (values marked, scans flagged) is on that cast's page, not here.

:func:`read_processing_tables` extracts the rows as plain data;
:func:`generate_processing_page` renders them to HTML.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from ctdcast._version import __version__ as _VERSION
from ctdcast.analysis.processing_record import STAGES, ProcessingRow, rows_from_json
from ctdcast.config.cnv_header import CONFORMANCE_DIFFER, CONFORMANCE_MATCH
from ctdcast.identity import format_cast_id
from ctdcast.plotters.processing import draw_setting_by_cast_fig
from ctdcast.processors.editing import SOAK_NOT_APPLIED
from ctdcast.reports._env import get_template
from ctdcast.reports._figdebug import render_b64
from ctdcast.reports._format import report_generated_at
from ctdcast.reports._navs import nav_for
from ctdcast.reports._vendored.design_tokens import W_HALF
from ctdcast.reports.design import _JS_TOP_LINKS, SHARED_CSS

#: The page's href, beside the other pages built from ``profiles.nc``.
PROCESSING_HREF = "processing.html"

#: A step with more runs of casts than this is drawn as one "varies cast to cast" row.
VARIES_AFTER = 5

#: How each stage is headed on the page.
STAGE_TITLES = {
    "stage 1": "Stage 1 — reading the raw file",
    "Sea-Bird": "Sea-Bird — before ctdcast (from the raw header)",
    "stage 2": "Stage 2 — soak and deck",
    "stage 3": "Stage 3 — corrections",
    "product": "Products",
}

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


@dataclass
class Run:
    """A run of consecutive casts that used one setting of a step."""

    first: str
    last: str
    first_number: int
    row: ProcessingRow | None  # None: the step did not run on these casts

    @property
    def casts(self) -> str:
        """Return the run as ``011`` or ``011–014``."""
        return self.first if self.first == self.last else f"{self.first}–{self.last}"


@dataclass
class StepRows:
    """One step of one stage over the cruise: its runs, or a "varies" summary."""

    stage: str
    step: str
    runs: list[Run] = field(default_factory=list)
    varies: dict[str, Any] | None = None
    figure: str | None = None
    # Casts on which the step ran differently from its setting, and how (an amber row).
    exception_casts: str = ""
    exception_count: int = 0
    exception: str = ""


def _label_runs(labels: list[str], picked: list[bool]) -> str:
    """Return the picked casts as runs of consecutive casts: ``051–055, 057–060, 122b``."""
    runs: list[list[str]] = []
    prev = False
    for label, on in zip(labels, picked, strict=True):
        if on:
            if prev:
                runs[-1].append(label)
            else:
                runs.append([label])
        prev = on
    return ", ".join(r[0] if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in runs)


def _step_keys(records: list[list[ProcessingRow]]) -> list[tuple[str, str, int]]:
    """Return every (stage, step, occurrence) seen, in stage order then first position."""
    seen: dict[tuple[str, str, int], tuple[int, int]] = {}
    for rows in records:
        count: dict[tuple[str, str], int] = {}
        for pos, r in enumerate(rows):
            k = (r.stage, r.step)
            n = count.get(k, 0)
            count[k] = n + 1
            key = (r.stage, r.step, n)
            rank = (STAGES.index(r.stage) if r.stage in STAGES else len(STAGES), pos)
            seen[key] = min(seen.get(key, rank), rank)
    return sorted(seen, key=lambda k: seen[k])


def _row_at(
    rows: list[ProcessingRow], key: tuple[str, str, int]
) -> ProcessingRow | None:
    stage, step, n = key
    matches = [r for r in rows if r.stage == stage and r.step == step]
    return matches[n] if n < len(matches) else None


def _same(a: ProcessingRow | None, b: ProcessingRow | None) -> bool:
    """Return whether two casts' rows count as the same setting."""
    if a is None or b is None:
        return a is b
    return (a.setting, a.producer, a.version, a.state, a.variables) == (
        b.setting,
        b.producer,
        b.version,
        b.state,
        b.variables,
    )


def _varies(runs: list[Run], numbers: list[int]) -> dict[str, Any]:
    """Summarise a step whose setting changes cast to cast: its shape and value ranges."""
    present = [r for r in runs if r.row is not None]
    settings = [r.row.setting for r in present]
    shapes = {_NUMBER.sub("#", s) for s in settings}
    summary: dict[str, Any] = {
        "n_settings": len(set(settings)),
        "casts": f"{runs[0].first}–{runs[-1].last}",
        "missing": sum(1 for r in runs if r.row is None),
        "row": present[0].row,
        "setting": None,
        "values": None,
        "state_differs": any(r.row.state == CONFORMANCE_DIFFER for r in present),
    }
    if len(shapes) == 1:
        # The same text with different numbers: show each varying number as its range.
        columns = list(
            zip(*(map(float, _NUMBER.findall(s)) for s in settings), strict=True)
        )
        parts = _NUMBER.split(settings[0])
        text = parts[0]
        varying = []
        for i, col in enumerate(columns):
            lo, hi = min(col), max(col)
            text += f"{lo:g}" if lo == hi else f"{lo:g}–{hi:g}"
            if lo != hi:
                varying.append(i)
            text += parts[i + 1]
        summary["setting"] = text
        if len(varying) == 1:
            i = varying[0]
            by_run = {
                r.first_number: float(_NUMBER.findall(r.row.setting)[i])
                for r in present
            }
            summary["values"] = (numbers, [by_run.get(n, np.nan) for n in numbers])
    return summary


def read_processing_tables(profiles_path: Path) -> dict[str, Any]:
    """Return the processing page's tables from ``profiles.nc``, as plain data.

    Parameters
    ----------
    profiles_path : pathlib.Path
        A compiled ``profiles.nc``.

    Returns
    -------
    dict
        ``filename``, ``n_casts``, ``has_record`` and ``stages``: a list of
        ``(stage, title, [StepRows])`` in processing order.
    """
    meta: dict[str, Any] = {"filename": Path(profiles_path).name, "stages": []}
    with xr.open_dataset(profiles_path, engine="netcdf4") as ds:
        if "processing_record" not in ds.variables:
            meta.update(has_record=False, n_casts=0)
            return meta
        direction = ds["cast_direction"].values.astype(str)
        down = [i for i, d in enumerate(direction) if d == "down"]
        numbers = [int(ds["cast_number"].values[i]) for i in down]
        suffixes = (
            [str(ds["cast_suffix"].values[i]) for i in down]
            if "cast_suffix" in ds.variables
            else [""] * len(down)
        )
        records = [rows_from_json(str(ds["processing_record"].values[i])) for i in down]
    labels = [format_cast_id(n, s) for n, s in zip(numbers, suffixes, strict=True)]
    meta.update(has_record=any(records), n_casts=len(records))
    steps: list[StepRows] = []
    for key in _step_keys(records):
        per_cast = [_row_at(rows, key) for rows in records]
        runs: list[Run] = []
        for label, number, row in zip(labels, numbers, per_cast, strict=True):
            if runs and _same(runs[-1].row, row):
                runs[-1].last = label
            else:
                runs.append(Run(label, label, number, row))
        step = StepRows(stage=key[0], step=key[1], runs=runs)
        soak_skipped = [
            row is not None and SOAK_NOT_APPLIED in row.outcome for row in per_cast
        ]
        if any(soak_skipped):
            step.exception_casts = _label_runs(labels, soak_skipped)
            step.exception_count = sum(soak_skipped)
            step.exception = (
                "soak test not applied: the recording starts below the soak window "
                "(surface_soak.starts_below: skip)"
            )
        if sum(1 for r in runs if r.row is not None) > VARIES_AFTER:
            step.varies = _varies(runs, numbers)
            values = step.varies.pop("values")
            if values is not None:
                step.figure = render_b64(
                    draw_setting_by_cast_fig,
                    values[0],
                    values[1],
                    f"{key[1]} setting",
                    width_in=W_HALF,
                    optional=True,
                    source="processing.py:draw_setting_by_cast_fig",
                )
        steps.append(step)
    meta["stages"] = [
        (stage, STAGE_TITLES.get(stage, stage), [s for s in steps if s.stage == stage])
        for stage in STAGES
        if any(s.stage == stage for s in steps)
    ]
    meta["any_differ"] = any(
        r.row is not None and r.row.state == CONFORMANCE_DIFFER
        for s in steps
        for r in s.runs
    )
    meta["any_exception"] = any(s.exception for s in steps)
    meta["match"] = CONFORMANCE_MATCH
    meta["differ"] = CONFORMANCE_DIFFER
    meta["varies_after"] = VARIES_AFTER
    return meta


def generate_processing_page(
    profiles_path: Path,
    out_path: Path,
    *,
    cruise: str = "",
    nav_prefix: str = "",
    show_nav: bool = False,
    inventory_pills: list[dict[str, str]] | None = None,
    current_href: str = PROCESSING_HREF,
    generated_at: str | None = None,
) -> Path:
    """Render the cruise processing page for *profiles_path* to *out_path*.

    Parameters
    ----------
    profiles_path : pathlib.Path
        A compiled ``profiles.nc`` carrying ``processing_record``.
    out_path : pathlib.Path
        The HTML file to write; parent directories are created.
    cruise : str, optional
        Cruise identifier for the title and footer.
    nav_prefix : str, optional
        Relative path to the report root for the page-nav links.
    show_nav : bool, default False
        Render the full report page-nav (the in-report page).
    inventory_pills : list of dict, optional
        ``{"label", "href"}`` entries for the pages built from files.
    current_href : str, default :data:`PROCESSING_HREF`
        This page's own pill, rendered as the non-link active one.
    generated_at : str, optional
        Page build stamp; ``None`` uses the current UTC time.

    Returns
    -------
    pathlib.Path
        The written *out_path*.
    """
    meta = read_processing_tables(profiles_path)
    nav = (
        nav_for(
            None,
            prefix=nav_prefix,
            inventory=inventory_pills or (),
            inventory_current=current_href,
        )
        if show_nav
        else None
    )
    html = get_template("processing.html").render(
        meta=meta,
        page_title=f"Processing — {cruise}" if cruise else "Processing",
        cruise=cruise,
        css=SHARED_CSS,
        js_top_links=_JS_TOP_LINKS,
        nav_prefix=nav_prefix,
        nav=nav,
        masthead_role="component",
        version=_VERSION,
        generated_at=report_generated_at(generated_at),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
