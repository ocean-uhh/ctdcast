"""What was done to one cast, step by step, as plain rows: the cast's processing record.

One list per cast, in the order the steps ran: how stage 1 read the raw file, the Sea-Bird steps
recorded in its header (the deck unit's advance and each SBE Data Processing module, with the
conformance check against SBE's documented values), stage 2's soak and deck rule, and ctdcast's
stage-3 steps and products.  Each row separates the *setting* (what was configured, the same on
every cast processed alike) from the *outcome* (what the step did on this cast, such as how many
values Wild Edit marked), so casts can be compared on their settings.

The cast page draws a cast's rows; the profiles compile stores every cast's rows in
``profiles.nc`` (:func:`record_json`), and the cruise processing page draws them as runs of casts.
Everything is read from the stage file alone.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
import xarray as xr

from ctdcast.config.cnv_header import (
    CONFORMANCE_DIFFER,
    CONFORMANCE_NO_REFERENCE,
    ConformanceTick,
    Correction,
    celltm_reference_tick,
    conductivity_advance_reference_tick,
    conformance_ticks,
    correction_records,
    header_from_raw_metadata,
    no_reference_tick,
    pressure_filter_reference_tick,
)
from ctdcast.readers.metadata import source_to_canonical

#: The stages a row can belong to, in the order they run.
STAGES = (
    "stage 1",
    "Sea-Bird",
    "stage 2",
    "stage 3",
    "product",
)


@dataclass(frozen=True)
class ProcessingRow:
    """One step applied to a cast.

    Attributes
    ----------
    stage : str
        One of :data:`STAGES`.
    step : str
        The step's name (``wildedit``, ``alignctd``, ``celltm``, ``binavg (1dbar_down)``…).
    producer : str
        What applied it (Sea-Bird's software, or ctdcast and the seabirdscientific function).
    version : str
        The producer's version, when the file records it.
    setting : str
        What was configured; casts processed alike have the same setting.
    outcome : str
        What the step did on this cast (counts), not compared across casts.
    variables : str
        The variables the step changed or marked.
    state : str
        The conformance check: ``match``, ``differ`` or ``no_reference``.
    reference : str
        The documented value checked against, when there is one.
    source : str
        Where that value comes from.
    exception : str
        How the step ran differently from its setting on this cast, as a fixed phrase that reads
        the same on every cast it applies to (``""`` when it ran as set).  Not part of the
        setting, so it does not split casts into runs; the processing page lists it apart.
    """

    stage: str
    step: str
    producer: str
    version: str
    setting: str
    outcome: str = ""
    variables: str = ""
    state: str = CONFORMANCE_NO_REFERENCE
    reference: str = ""
    source: str = ""
    exception: str = ""


#: The exception a product's Bin Average records on a cast where it kept part of a flagged scan.
BINAVG_KEPT_PARTLY_FLAGGED = (
    "kept the good values of scans with a flagged value; seabirdscientific's bin_average "
    "drops such a scan whole"
)


def _exception_of(step: str, outcome: str) -> str:
    """Return the fixed phrase for how *step* ran differently from its setting, from *outcome*."""
    if step == "loopedit":
        found = re.search(r"surface soak not applied: [^(;]*", outcome)
        return found.group(0).strip() if found else ""
    if step.startswith("binavg (") and outcome.split(" ", 1)[0].isdigit():
        return BINAVG_KEPT_PARTLY_FLAGGED
    return ""


def ctdcast_versions(ds: xr.Dataset, method: str) -> str:
    """Return ``"ctdcast X, seabirdscientific Y"`` for a stage-3 step, from the file alone."""
    found = re.search(r"ctdcast (\S+) stage3:", str(ds.attrs.get("history", "")))
    parts = [f"ctdcast {found.group(1)}"] if found else []
    sbs = re.search(r"seabirdscientific (\S+)", method)
    if sbs:
        parts.append(f"seabirdscientific {sbs.group(1)}")
    return ", ".join(parts)


def _stage3_rows(
    ds: xr.Dataset,
) -> list[tuple[Correction, ConformanceTick, str, str]]:
    """Return ctdcast's own stage-3 corrections as ``(record, tick, setting, outcome)``, in order.

    *setting* is what was configured (the same on every cast processed alike); *outcome* is what
    the step did on this cast (Wild Edit's and Loop Edit's counts).  The record's parameters are
    the two joined, as the cast page shows them.

    Read from the variables' attributes and put in the order stage 3 applied them, which it
    records in the file's ``data_processing_steps`` attribute (the configured steps can come in
    any order); without it, the rows keep the order they are read in.  Each row
    carries a conformance tick against the same SBE references as the rows above it: cell
    thermal mass against (0.03, 7), alignment by the channel's total advance (deck unit +
    ctdcast) against 0.073 s; the slope, Wild Edit and the oxygen conversion have no reference
    and show a dash.
    """
    rows: list[tuple[Correction, ConformanceTick, str, str]] = []
    # A preferred-sensor composite copies its source channel's attrs; listing it would show
    # each correction twice.
    names = [
        str(v)
        for v in ds.data_vars
        if not str(ds[v].attrs.get("comment", "")).startswith("preferred ")
    ]

    ran = [
        part.strip()
        for part in str(ds.attrs.get("data_processing_steps", "")).split(";")
        if part.strip()
    ]
    order: list[int] = []

    def add(
        label: str,
        producer: str,
        method: str,
        params: str,
        tick_of: Callable[[str], ConformanceTick],
        outcome: str = "",
    ) -> None:
        key = f"ctdcast_{len(rows) + 1}"
        rows.append(
            (
                Correction(
                    label,
                    key,
                    producer,
                    ctdcast_versions(ds, method),
                    "; ".join(part for part in (params, outcome) if part),
                ),
                tick_of(key),
                params,
                outcome,
            )
        )
        # The SBE 43 oxygen is derived after every step; anything not in the record keeps its place.
        order.append(ran.index(label) if label in ran else len(ran) + len(order))

    for v in names:
        a = ds[v].attrs
        if "calibration_slope" in a:
            params = f"× {a['calibration_slope']}"
            if float(a.get("calibration_offset", 0.0) or 0.0):
                params += f" {float(a['calibration_offset']):+g}"
            add(
                "slope_offset",
                "ctdcast stage 3",
                "",
                params,
                lambda k, v=v: no_reference_tick(k, "slope_offset", v),
            )
    edited = [v for v in names if "wild_edit" in ds[v].attrs]
    if edited:
        a = ds[edited[0]].attrs
        counts = {v: int(ds[v].attrs.get("wild_edit_marked", 0)) for v in edited}
        marked = (", ".join(f"{v} {n}" for v, n in counts.items() if n) or "none") + (
            "; none in the others"
            if 0 in counts.values() and any(counts.values())
            else ""
        )
        edited_names = ", ".join(edited)
        add(
            "wildedit",
            "ctdcast stage 3 (seabirdscientific wild_edit)",
            str(a.get("wild_edit_method", "")),
            str(a["wild_edit"]),
            lambda k, vs=edited_names: no_reference_tick(k, "wildedit", vs),
            outcome=f"values marked (QARTOD 4, kept): {marked}",
        )

    # Filters: one row per filter, naming every variable it changed, in the order applied.
    by_filter: dict[str, list[str]] = {}
    for v in names:
        for part in str(ds[v].attrs.get("filters", "")).split(";"):
            if part.strip():
                by_filter.setdefault(part.strip(), []).append(v)
    history_text = str(ds.attrs.get("history", ""))

    def _ran_at(text: str) -> int:
        # Each filter's history line, e.g. "filter: low-pass time constant 0.03 s on ...".
        phrase = text.replace("low-pass ", "low-pass time constant ").replace(
            "window ", "window_filter: ", 1
        )
        at = history_text.find(phrase)
        return at if at >= 0 else len(history_text)

    for text, variables in sorted(by_filter.items(), key=lambda kv: _ran_at(kv[0])):
        label = "window_filter" if text.startswith("window") else "filter"
        tc = re.match(r"low-pass ([0-9.eE+-]+) s", text)
        joined = ", ".join(variables)
        if tc and "pressure" in variables:
            tc_seconds = float(tc.group(1))
            tick_of = lambda k, t=tc_seconds, vs=joined: (  # noqa: E731
                pressure_filter_reference_tick(k, "filter", t, vs)
            )
        else:
            tick_of = lambda k, lab=label, vs=joined: no_reference_tick(k, lab, vs)  # noqa: E731
        add(
            label,
            f"ctdcast stage 3 (seabirdscientific {'window_filter' if label == 'window_filter' else 'low_pass_filter'})",
            str(ds[variables[0]].attrs.get("filters_method", "")),
            text,
            tick_of,
        )
    if "loop_edit_flag" in ds:
        a = ds["loop_edit_flag"].attrs
        n_marked = int(np.asarray(ds["loop_edit_flag"].values).sum())
        add(
            "loopedit",
            "ctdcast stage 3 (seabirdscientific loop_edit)",
            str(a.get("loop_edit_method", "")),
            str(a.get("loop_edit", "")),
            lambda k: no_reference_tick(k, "loopedit", "all channels (whole scans)"),
            outcome=f"{n_marked} of {ds['loop_edit_flag'].size} scans marked (QARTOD 4, kept)"
            + (
                f"; {a['loop_edit_soak_not_applied']}"
                if a.get("loop_edit_soak_not_applied")
                else ""
            ),
        )
    for v in names:
        a = ds[v].attrs
        if "alignment_offset_seconds" in a:
            offset = float(a["alignment_offset_seconds"])
            params = f"advance {offset:+.3f} s"
            deck = a.get("alignment_deck_unit_advance_seconds")
            if deck is not None:
                params += f" (deck unit's {float(deck):+.3f} s already in the data)"
            if v.startswith("conductivity") and deck is not None:
                total = offset + float(deck)
                tick_of = lambda k, v=v, t=total: conductivity_advance_reference_tick(  # noqa: E731
                    k, "alignctd", t, v
                )
            else:
                tick_of = lambda k, v=v: no_reference_tick(k, "alignctd", v)  # noqa: E731
            add(
                "alignctd",
                "ctdcast stage 3 (seabirdscientific align_ctd)",
                str(a.get("alignment_method", "")),
                params,
                tick_of,
            )
    for v in names:
        a = ds[v].attrs
        if "cell_thermal_mass_alpha" in a:
            alpha = float(a["cell_thermal_mass_alpha"])
            tau = float(a["cell_thermal_mass_tau_seconds"])
            add(
                "celltm",
                "ctdcast stage 3 (seabirdscientific cell_thermal_mass)",
                str(a.get("cell_thermal_mass_method", "")),
                f"alpha={alpha:g} tau={tau:g} s, with {a.get('cell_thermal_mass_temperature', '?')}",
                lambda k, v=v, al=alpha, ta=tau: celltm_reference_tick(
                    k, "celltm", al, ta, v
                ),
            )
    for v in names:
        a = ds[v].attrs
        if a.get("oxygen_tau_correction"):
            add(
                "SBE 43 oxygen",
                "ctdcast stage 3 (tau, Application Note 64-3 hysteresis; "
                "seabirdscientific convert_sbe43_oxygen)",
                str(a.get("conversion_method", "")),
                f"tau window {a.get('oxygen_tau_window_seconds', '?')} s; "
                f"from {a.get('derived_from', '?')}",
                lambda k, v=v: no_reference_tick(k, "SBE 43 oxygen", v),
            )

    # A product's Bin Average that kept part of a flagged scan: where ctdcast parts ways with
    # seabirdscientific, which would drop the whole scan.  Products come after stage 3.
    # ``products_made`` lists every product with its steps; a file written before it existed
    # names only the products that met a partly flagged scan.
    def _by_name(attr: str) -> dict[str, str]:
        out = {}
        for line in str(ds.attrs.get(attr, "")).split(" | "):
            name, _, text = line.partition(": ")
            if text:
                out[name] = text
        return out

    partly = _by_name("products_bin_average_partly_flagged")
    made = _by_name("products_made") or dict.fromkeys(partly, "binavg")
    for name, steps in made.items():
        if "binavg" not in steps:
            # A product with no Bin Average (a split leg, a filtered copy): named for what it is.
            add(
                f"product ({name})",
                f"ctdcast product {name}",
                "",
                steps,
                lambda k, name=name: no_reference_tick(k, f"product ({name})", ""),
            )
            continue
        text = partly.get(name, "")
        if text:
            tick_of = lambda k, name=name, text=text: ConformanceTick(  # noqa: E731
                k,
                f"binavg ({name})",
                CONFORMANCE_DIFFER,
                "a scan with any flagged value is dropped whole",
                "seabirdscientific processing.bin_average",
                text.split(";")[0],
                "",
            )
        else:
            tick_of = lambda k, name=name: no_reference_tick(k, f"binavg ({name})", "")  # noqa: E731
            text = "no scan entering the bins had a flagged value beside good ones"
        add(
            f"binavg ({name})",
            f"ctdcast product {name} (seabirdscientific bin_average)",
            "",
            steps,
            tick_of,
            outcome=text,
        )
    ranked = sorted(range(len(rows)), key=lambda i: (order[i], i))
    out = []
    for n, i in enumerate(ranked, 1):
        rec, tick, setting, outcome = rows[i]
        key = f"ctdcast_{n}"
        out.append(
            (
                Correction(rec.label, key, rec.producer, rec.version, rec.parameters),
                ConformanceTick(
                    key,
                    tick.label,
                    tick.state,
                    tick.reference,
                    tick.source,
                    tick.detail,
                    tick.variables,
                ),
                setting,
                outcome,
            )
        )
    return out


def ctdcast_correction_rows(ds: xr.Dataset) -> list[tuple[Correction, ConformanceTick]]:
    """Return ctdcast's stage-3 corrections as the cast page's ``(record, tick)`` rows.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-3 cast file.

    Returns
    -------
    list of tuple
        ``(Correction, ConformanceTick)`` per step, in the order stage 3 applied them; the
        record's parameters are the setting and the outcome joined.
    """
    return [(rec, tick) for rec, tick, _setting, _outcome in _stage3_rows(ds)]


def _history_line(ds: xr.Dataset, stage: str) -> list[str]:
    """Return the cast's ``history`` lines written by *stage* (``stage1``, ``stage2``)."""
    return [
        line
        for line in str(ds.attrs.get("history", "")).splitlines()
        if f" {stage}: " in line
    ]


def _stage1_rows(ds: xr.Dataset) -> list[ProcessingRow]:
    """Return how stage 1 read the raw file: the reader and its settings, not the file name."""
    rows = []
    for line in _history_line(ds, "stage1"):
        version = re.search(r"ctdcast (\S+) stage1:", line)
        text = line.split("stage1: ", 1)[1]
        read = re.match(r"read \S+(?: \+ \S+)? (with .*)", text)
        if not read:
            continue
        rows.append(
            ProcessingRow(
                stage="stage 1",
                step="read",
                producer="ctdcast stage 1",
                version=f"ctdcast {version.group(1)}" if version else "",
                setting=read.group(1),
                outcome=text.split(" with ")[0].removeprefix("read "),
            )
        )
    return rows


def _stage2_rows(ds: xr.Dataset) -> list[ProcessingRow]:
    """Return stage 2's soak/deck rule: its settings, and how many scans it flagged."""
    rows = []
    for line in _history_line(ds, "stage2"):
        version = re.search(r"ctdcast (\S+) stage2:", line)
        text = line.split("stage2: ", 1)[1]
        if not text.startswith("soak/deck"):
            continue
        counts, _, setting = text.rpartition("; ")
        found = re.findall(r"\((\d+) flagged\)", counts)
        outcome = (
            f"{found[0]} soak and {found[1]} deck scans flagged (QARTOD 4, kept)"
            if len(found) == 2
            else ""
        )
        rows.append(
            ProcessingRow(
                stage="stage 2",
                step="trim (soak/deck)",
                producer="ctdcast stage 2",
                version=f"ctdcast {version.group(1)}" if version else "",
                setting=setting,
                outcome=outcome,
                variables="every variable with a _qc",
            )
        )
    return rows


def _sea_bird_rows(ds: xr.Dataset) -> list[ProcessingRow]:
    """Return the Sea-Bird steps recorded in the raw header, one row per conformance tick."""
    header = header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
    if not header:
        return []
    records = correction_records(header)
    by_key: dict[str, list[ConformanceTick]] = {}
    for tick in conformance_ticks(header, source_to_canonical(ds, lower_keys=True)):
        by_key.setdefault(tick.key, []).append(tick)
    rows = []
    for rec in records:
        ticks = by_key.get(rec.key) or [None]
        split = len(ticks) > 1
        for tick in ticks:
            rows.append(
                ProcessingRow(
                    stage="Sea-Bird",
                    step=tick.label if tick else rec.label,
                    producer=rec.producer,
                    version=rec.version,
                    setting=tick.detail
                    if (split and tick and tick.detail)
                    else rec.parameters,
                    variables=tick.variables if tick else "",
                    state=tick.state if tick else CONFORMANCE_NO_REFERENCE,
                    reference=tick.reference if tick else "",
                    source=tick.source if tick else "",
                )
            )
    return rows


def processing_rows(ds: xr.Dataset) -> list[ProcessingRow]:
    """Return every step applied to a cast, in the order they ran.

    Parameters
    ----------
    ds : xarray.Dataset
        A cast's stage file (any stage; a stage-1 file has only the stage-1 and Sea-Bird rows).

    Returns
    -------
    list of ProcessingRow
        Stage 1, the Sea-Bird header's steps, stage 2, stage 3 and products.
    """
    rows = _stage1_rows(ds) + _sea_bird_rows(ds) + _stage2_rows(ds)
    for rec, tick, setting, outcome in _stage3_rows(ds):
        step = rec.label if tick.label == rec.label else tick.label
        product = rec.label.startswith(("binavg (", "product ("))
        exception = _exception_of(step, outcome)
        # Bin Average's divergence from seabirdscientific is what it did on this cast (an
        # exception), not its setting, so across casts it is compared as unreferenced.
        state = (
            CONFORMANCE_NO_REFERENCE
            if exception == BINAVG_KEPT_PARTLY_FLAGGED
            else tick.state
        )
        rows.append(
            ProcessingRow(
                stage="product" if product else "stage 3",
                step=step,
                producer=rec.producer,
                version=rec.version,
                setting=setting,
                outcome=outcome,
                variables=tick.variables,
                state=state,
                reference="" if state != tick.state else tick.reference,
                source="" if state != tick.state else tick.source,
                exception=exception,
            )
        )
    return rows


def record_json(ds: xr.Dataset) -> str:
    """Return :func:`processing_rows` as one JSON string, for a per-profile variable.

    Parameters
    ----------
    ds : xarray.Dataset
        A cast's stage file.

    Returns
    -------
    str
        A JSON list of row objects (the :class:`ProcessingRow` fields).
    """
    return json.dumps([asdict(r) for r in processing_rows(ds)], ensure_ascii=False)


def rows_from_json(text: str) -> list[ProcessingRow]:
    """Return the rows of a :func:`record_json` string; an empty string gives no rows.

    Parameters
    ----------
    text : str
        The stored JSON.

    Returns
    -------
    list of ProcessingRow
        The cast's rows.
    """
    return [ProcessingRow(**r) for r in json.loads(text)] if text else []
