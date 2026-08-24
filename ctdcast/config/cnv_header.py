"""Parse the acquisition (``*``) and start-time (``#``) header of an SBE CNV/HEX file.

These are pure functions over header text — no file I/O, no xarray. They recover
what a Sea-Bird deck unit and Seasave did to a cast *before* ctdcast ever read it:
the deck-unit conductivity advance (applied in hardware at acquisition and recorded
nowhere ctdcast previously looked), the system/NMEA clock pair, and which clock the
``start_time`` coordinate is anchored to.

The two verbatim blocks are ground truth; every typed field is a best-effort read on
top of them. A line the classifier does not recognise is kept in ``verbatim`` and
skipped — never dropped, never fatal. Absence of a deck-unit line means a different
instrument class, not "unaligned": it yields an empty :class:`DeckUnit`, not an error.

Header lines are matched with :meth:`str.splitlines`, which handles the CRLF endings
these Windows-written files carry, and whitespace inside a value is collapsed before
a timestamp is parsed (some writers emit ``NMEA UTC`` with a double space).

The header text is not read from a CNV file: it is already carried on every stage-1
file in the ``raw_metadata`` global attribute. :func:`header_from_raw_metadata`
extracts it from that JSON envelope, so nothing here opens a file.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

_SBE_TIME_FMT = "%b %d %Y %H:%M:%S"

# One compiled pattern per recognised '*'-line shape. The '*' block is NOT
# ``key = value`` -- advance lines have no '=' at all -- so match by shape, never
# split on '='.
_RE_DECK_UNIT = re.compile(r"^\*\s*(SBE 11plus)\s+(V\s+[\d.]+[a-z]?)\b")
_RE_ADVANCE = re.compile(r"^\*\s*advance\s+(.+?)\s+([\d.]+)\s+seconds\s*$")
_RE_SCANS_AVG = re.compile(
    r"^\*\s*Number of Scans Averaged by the Deck Unit\s*=\s*(\d+)"
)
_RE_SYSTEM_UPLOAD = re.compile(r"^\*\s*System UpLoad Time\s*=\s*(.+?)\s*$")
_RE_SYSTEM_UTC = re.compile(r"^\*\s*System UTC\s*=\s*(.+?)\s*$")
_RE_NMEA_UTC = re.compile(r"^\*\s*NMEA UTC \(Time\)\s*=\s*(.+?)\s*$")
_RE_SEASAVE = re.compile(r"^\*\s*Software Version Seasave\s+(.+?)\s*$")
_RE_START_TIME = re.compile(r"^#\s*start_time\s*=\s*(.+?)\s*$")
# The provenance bracket is optional -- a start_time without one still yields its value.
_RE_START_BRACKET = re.compile(r"\[(.+?)\]")
# A '#' processing-module line (``# datcnv_date = ...``), used only to detect a chain
# that the bad_flag gate failed to capture. group(1) is the module token.
_RE_HASH_MODULE = re.compile(r"^#\s*(\w+)_\w[^=]*=")

# start_time bracket -> (clock, anchor). The bracket is "<clock>, <anchor>" and SBE is
# inconsistent with its own trailing period (the System form has one, the NMEA form does
# not), so it is split on the first comma and each half normalised (strip, drop a trailing
# period, casefold) before lookup -- never matched as a whole string. Absent or
# unrecognised halves resolve to "unknown".
_START_TIME_CLOCKS = {
    "system utc": "system",
    "nmea time": "nmea",
    "instrument's time stamp": "instrument",
}
_START_TIME_ANCHORS = {
    "first data scan": "first_scan",
    "header": "header",
}

# The salient parameters to surface per module in its ``correction_<module>`` summary;
# modules absent here fall back to all of their parameters bar the housekeeping ones.
# Every module in the chain gets a summary -- deciding which modules "count" as
# corrections would require predicting them, and the corpus already holds three nobody
# would (airpress, hex2py, binning). A later stage reads the order and these summaries.
_MODULE_SALIENT = {
    "celltm": ("alpha", "tau"),
    "binavg": ("bintype", "binsize"),
    "filter": ("low_pass_tc_A", "low_pass_tc_B"),
    "wildedit": ("pass1_nstd", "pass2_nstd", "npoint"),
}
_LEDGER_HOUSEKEEPING = frozenset({"date", "in"})

# SBE 11plus factory-default conductivity advance: +1.75 scans at 24 Hz = 0.073 s (manual
# p.85), the value that cancels the typical TC-duct / 3000-rpm lag. A conductivity channel
# advanced by anything else is flagged by provenance_advisories.
_DEFAULT_CONDUCTIVITY_ADVANCE = 0.073


@dataclass(frozen=True)
class DeckUnit:
    """The SBE 11plus deck unit's acquisition-time configuration.

    ``advance`` maps a channel name exactly as the header spells it (``"primary
    conductivity"``, ``"voltage 0"``) to its advance in seconds. It is a per-channel
    map, not a boolean or single value: a V 5.0 unit advances the two conductivity
    channels by different amounts, and that asymmetry is the whole reason this parse
    exists. An empty map with ``model`` ``None`` means no deck-unit line was found.
    """

    model: str | None = None
    firmware: str | None = None
    advance: dict[str, float] = field(default_factory=dict)
    scans_averaged: int | None = None


@dataclass(frozen=True)
class Clocks:
    """The two acquisition clocks and their offset.

    ``offset_seconds`` is ``nmea_utc - system_utc`` (positive when the system clock is
    slow relative to GPS), or ``None`` if either timestamp is absent or unparseable.
    ``system_dt`` / ``nmea_dt`` are the same two clocks already parsed to ``datetime`` while
    computing the offset, exposed so callers need not re-parse the verbatim strings.
    """

    system_upload: str | None = None
    system_utc: str | None = None
    nmea_utc: str | None = None
    offset_seconds: float | None = None
    system_dt: datetime | None = None
    nmea_dt: datetime | None = None


@dataclass(frozen=True)
class StartTime:
    """The ``# start_time`` value and the provenance named in its bracket.

    ``source`` is the verbatim bracket text (``"System UTC, first data scan."``);
    ``clock`` and ``anchor`` are its resolved halves. ``source`` is ``""`` when the line
    carries no bracket.
    """

    value: str | None
    clock: str
    anchor: str
    source: str = ""


@dataclass(frozen=True)
class Acquisition:
    """Everything recovered from the ``*`` acquisition block of a CNV/HEX header."""

    deck_unit: DeckUnit
    clocks: Clocks
    seasave_version: str | None
    verbatim: str


@dataclass(frozen=True)
class ProcessingStep:
    """One SBE Data Processing module in the ``#`` chain.

    ``module`` is the name exactly as the header spells it (``datcnv``, ``wildedit``,
    ``Derive``). ``params`` maps each field to its verbatim value in file order — keys
    keep the SBE channel names the header uses (``low_pass_A_vars``, ``action t090C``);
    values are never split, so a comma-collection such as ``no, min = 0.000, ...`` and
    a date's trailing ``[datcnv_vars = 15]`` stay intact.
    """

    module: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessingChain:
    """The SBE Data Processing module chain, in file order.

    ``steps`` is one entry per contiguous run of a module's lines, so a module that
    runs twice (SBE sanctions running Wild Edit more than once) yields two steps and
    is never deduplicated. ``verbatim`` is the ``#`` processing region exactly as read,
    so an unrecognised line is preserved there even when it contributes no step.
    """

    steps: list[ProcessingStep] = field(default_factory=list)
    verbatim: str = ""


@dataclass(frozen=True)
class Correction:
    """One correction in the ledger, split into producer, version and parameters.

    The deck-unit alignment and each Sea-Bird Data Processing module become a record.
    ``label`` is the display name (``"align (deck)"``, ``"celltm"``, ``"celltm (2)"`` for
    a repeat); ``key`` is the attribute suffix (``"align"``, ``"celltm"``, ``"celltm_2"``).
    ``parameters`` is the salient parameter string, possibly empty.
    """

    label: str
    key: str
    producer: str
    version: str
    parameters: str


@dataclass(frozen=True)
class SbeHistoryNote:
    """One SBE Data Processing module rendered as a ``history`` line's components.

    ``timestamp`` is the module's verbatim SBE stamp (no ``Z``); ``stage`` is the module
    name as spelled; ``note`` is its salient-parameter body. The deck-unit align has no
    timestamp and is not a history note (it is ``correction_align``).
    """

    timestamp: str
    version: str
    stage: str
    note: str


@dataclass(frozen=True)
class SensorCalibration:
    """A frequency sensor's drift Slope/Offset, read from the CNV ``<Sensors>`` config.

    Answers "was a calibration correction already applied before ctdcast read the cast?"
    Sea-Bird applies ``corrected = slope * computed + offset`` at ``datcnv`` to the
    *derived physical value* (not the raw frequency), so a non-identity slope/offset means
    a drift or span correction is already baked into the data. ``kind`` is
    ``"temperature"``/``"conductivity"``/``"pressure"``; ``label`` disambiguates dual
    sensors (``"temperature_1"``, ``"temperature_2"``), or is the bare kind when a sensor
    is single. ``slope`` and ``offset`` are kept verbatim as the config spells them, so no
    precision is lost. ``slope_nondefault`` / ``offset_nondefault`` flag each value that
    departs from its identity (slope 1.0, offset 0.0) independently, so the display can
    mark exactly which one carries a correction; ``drift_applied`` is True when either
    does. Only the frequency sensors are read: a voltage sensor's Slope/Offset (pH,
    transmissometer) is a native calibration, not a drift knob.
    """

    kind: str
    label: str
    serial: str
    slope: str
    offset: str
    slope_nondefault: bool
    offset_nondefault: bool

    @property
    def drift_applied(self) -> bool:
        """True when a drift or span correction is baked into either value."""
        return self.slope_nondefault or self.offset_nondefault


def _collapse(value: str) -> str:
    """Collapse internal whitespace runs to single spaces and strip the ends."""
    return re.sub(r"\s+", " ", value.strip())


def _parse_sbe_time(value: str | None) -> datetime | None:
    """Parse an SBE timestamp (``Apr 01 2026 18:02:29``), tolerating extra spaces."""
    if value is None:
        return None
    try:
        return datetime.strptime(_collapse(value), _SBE_TIME_FMT)
    except ValueError:
        return None


def _star_verbatim(lines: list[str]) -> str:
    """Return the ``*`` acquisition lines, minus ``*END*`` and the ``**`` user header.

    The ``<Sensors>`` calibration XML lives in the ``#`` namespace (``# <Sensors ...>``),
    so the ``*`` block carries no sensor XML to exclude — it is kept verbatim elsewhere
    as ``raw_metadata``. ``**`` lines are a separate user-header namespace.
    """
    kept: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("**") or stripped.startswith("*END*"):
            continue
        if stripped.startswith("*"):
            kept.append(raw.rstrip())
    return "\n".join(kept)


def parse_star_block(header_text: str) -> Acquisition:
    """Parse the ``*`` acquisition block of an SBE CNV/HEX header.

    Recognised lines populate the typed fields; every ``*`` line (bar the sensor XML)
    is preserved in :attr:`Acquisition.verbatim`. Unrecognised lines are not fatal.
    Absence of the deck-unit line yields an empty :class:`DeckUnit`.
    """
    lines = header_text.splitlines()

    model: str | None = None
    firmware: str | None = None
    advance: dict[str, float] = {}
    scans_averaged: int | None = None
    system_upload: str | None = None
    system_utc: str | None = None
    nmea_utc: str | None = None
    seasave_version: str | None = None

    for line in lines:
        if (m := _RE_DECK_UNIT.match(line)) is not None:
            model, firmware = m.group(1), _collapse(m.group(2))
        elif (m := _RE_ADVANCE.match(line)) is not None:
            advance[_collapse(m.group(1))] = float(m.group(2))
        elif (m := _RE_SCANS_AVG.match(line)) is not None:
            scans_averaged = int(m.group(1))
        elif (m := _RE_SYSTEM_UPLOAD.match(line)) is not None:
            system_upload = m.group(1)
        elif (m := _RE_SYSTEM_UTC.match(line)) is not None:
            system_utc = m.group(1)
        elif (m := _RE_NMEA_UTC.match(line)) is not None:
            nmea_utc = m.group(1)
        elif (m := _RE_SEASAVE.match(line)) is not None:
            seasave_version = m.group(1)

    sys_dt = _parse_sbe_time(system_utc)
    nmea_dt = _parse_sbe_time(nmea_utc)
    offset_seconds = (
        (nmea_dt - sys_dt).total_seconds()
        if sys_dt is not None and nmea_dt is not None
        else None
    )

    deck_unit = DeckUnit(
        model=model, firmware=firmware, advance=advance, scans_averaged=scans_averaged
    )
    clocks = Clocks(
        system_upload=system_upload,
        system_utc=system_utc,
        nmea_utc=nmea_utc,
        offset_seconds=offset_seconds,
        system_dt=sys_dt,
        nmea_dt=nmea_dt,
    )
    return Acquisition(
        deck_unit=deck_unit,
        clocks=clocks,
        seasave_version=seasave_version,
        verbatim=_star_verbatim(lines),
    )


def header_from_raw_metadata(raw_metadata: str | None) -> str | None:
    """Extract the verbatim SBE header text from a stage-1 file's ``raw_metadata`` attr.

    ``raw_metadata`` is the JSON envelope seasenselib writes and stage 1 carries
    through: ``{"schema": ..., "raw_format": "sbe-cnv", "blocks": {"header": "<* and #
    lines>", ...}}``. Returns the ``blocks.header`` string, or ``None`` if the
    attribute is absent, is not JSON, or does not carry a header string. The schema
    string is not required to match, so a schema bump degrades gracefully rather than
    raising — only a change to the envelope *shape* yields ``None``.
    """
    if not raw_metadata:
        return None
    try:
        envelope = json.loads(raw_metadata)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(envelope, dict):
        return None
    blocks = envelope.get("blocks")
    if not isinstance(blocks, dict):
        return None
    header = blocks.get("header")
    return header if isinstance(header, str) and header else None


def parse_start_time(header_text: str) -> StartTime:
    """Parse ``# start_time`` and resolve its bracket to a ``(clock, anchor)`` pair.

    The provenance bracket is optional: a ``start_time`` line without one still yields
    its timestamp value, with ``clock``/``anchor`` ``"unknown"``. A file with no
    ``start_time`` line at all (e.g. a raw HEX, which carries no ``#`` block) returns
    ``value=None``.
    """
    for line in header_text.splitlines():
        if (m := _RE_START_TIME.match(line)) is not None:
            rhs = m.group(1)
            bracket = _RE_START_BRACKET.search(rhs)
            if bracket is None:
                return StartTime(
                    value=_collapse(rhs), clock="unknown", anchor="unknown"
                )
            clock, anchor = _resolve_start_time_bracket(bracket.group(1))
            return StartTime(
                value=_collapse(rhs[: bracket.start()]),
                clock=clock,
                anchor=anchor,
                source=_collapse(bracket.group(1)),
            )
    return StartTime(value=None, clock="unknown", anchor="unknown")


def start_time_clock(bracket: str) -> str:
    """Classify a ``time_coordinate_source`` bracket to its clock: ``system``/``nmea``/``unknown``.

    The public single point of truth for "which clock is the time coordinate anchored to", used by
    the stage-2 clock applier's gate so it does not re-parse the bracket with a fragile substring.
    An empty or unrecognised bracket resolves to ``"unknown"``.
    """
    return _resolve_start_time_bracket(bracket)[0]


def _resolve_start_time_bracket(bracket: str) -> tuple[str, str]:
    """Resolve a ``start_time`` bracket ``<clock>, <anchor>`` to ``(clock, anchor)``.

    Split on the first comma and normalise each half independently, so every
    clock/anchor combination resolves and SBE's inconsistent trailing period does not
    matter. A missing or unrecognised half is ``"unknown"``.
    """
    clock_part, _, anchor_part = bracket.partition(",")
    clock = _START_TIME_CLOCKS.get(_norm_bracket_part(clock_part), "unknown")
    anchor = _START_TIME_ANCHORS.get(_norm_bracket_part(anchor_part), "unknown")
    return clock, anchor


def _norm_bracket_part(part: str) -> str:
    """Normalise one half of a bracket: strip, drop a trailing period, casefold."""
    return part.strip().rstrip(".").strip().casefold()


def _processing_region(lines: list[str]) -> list[str]:
    """Return the ``#`` module-chain lines: from the first module line to ``file_type``.

    The chain is found by its first module-shaped line (``# <module>_<field> = ...``),
    not by the ``# bad_flag`` delimiter, so the verbatim block survives a header that
    omits bad_flag rather than vanishing. The ``# <Sensors>`` XML is skipped, and the
    data-table preamble (``# name 0 = ...``, ``# start_time = ...``) is excluded because
    it is not module-shaped — ``start`` and ``bad`` are the only underscore-keyed
    preamble tokens. Once the chain is entered, every ``#`` line is kept (so a module's
    continuation lines survive) until ``# file_type`` or ``*END*``.
    """
    region: list[str] = []
    in_chain = False
    in_sensors = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("*END*"):
            break
        if stripped.startswith("# <Sensors") or stripped.startswith("# <sensors"):
            in_sensors = True
            continue
        if in_sensors:
            if stripped.startswith("# </Sensors") or stripped.startswith("# </sensors"):
                in_sensors = False
            continue
        if not stripped.startswith("#"):
            continue
        if stripped[1:].strip().startswith("file_type"):
            break
        if not in_chain:
            m = _RE_HASH_MODULE.match(stripped)
            if m is None or m.group(1) in ("start", "bad"):
                continue
            in_chain = True
        region.append(raw.rstrip())
    return region


def parse_processing_chain(header_text: str) -> ProcessingChain:
    """Parse the ``#`` SBE Data Processing module chain into ordered steps.

    Module identity is the token before the first ``_`` (``datcnv_date`` -> ``datcnv``),
    which is correct for every SBE ``#``-block module — they are all single tokens.

    A new step starts when the module changes **or** when a field reappears within the
    current run. The second rule catches a module run twice as *adjacent* blocks — the
    case SBE's manual explicitly sanctions for Wild Edit — where the module name never
    changes: the repeat of ``wildedit_date`` (or any field already seen) opens a fresh
    step, so the first run's parameters are never overwritten. This works even for a
    dialect that emits no ``_date`` line at all, unlike splitting on ``_date``. Repeats
    are therefore kept, never deduplicated.

    Values are split on the first ``=`` only, leaving comma-collections and bracketed
    second fields verbatim. A line that is not ``key = value`` is preserved in
    :attr:`ProcessingChain.verbatim` but adds no step, so an unrecognised dialect
    degrades to verbatim rather than to an empty chain.
    """
    region = _processing_region(header_text.splitlines())
    groups: list[tuple[str, dict[str, str]]] = []
    for line in region:
        body = line.strip()[1:].strip()
        rawkey, sep, value = body.partition("=")
        rawkey = rawkey.strip()
        if not sep or "_" not in rawkey:
            continue
        module, field_name = rawkey.split("_", 1)
        if not groups or groups[-1][0] != module or field_name in groups[-1][1]:
            groups.append((module, {}))
        groups[-1][1][field_name] = value.strip()
    steps = [ProcessingStep(module=name, params=params) for name, params in groups]
    return ProcessingChain(steps=steps, verbatim="\n".join(region))


def _module_date_parts(params: dict[str, str]) -> tuple[str, str]:
    """Split a module's ``date`` value into ``(timestamp, version)``.

    The date is ``<timestamp>, <version> [<module>_vars = N]``; the bracket is stripped
    *before* the comma split so a comma inside it cannot corrupt either half. A date with
    no comma (no version recorded) is all timestamp; an absent date gives ``("", "")``.
    :func:`_module_version` and :func:`_module_timestamp` share this so they cannot drift.
    """
    date = re.sub(r"\[.*\]", "", params.get("date", ""))
    if "," not in date:
        return date.strip(), ""
    timestamp, version = date.rsplit(",", 1)
    return timestamp.strip(), version.strip()


def _module_version(params: dict[str, str]) -> str:
    """The SBE Data Processing version from a module's ``date`` value, or ``""``."""
    return _module_date_parts(params)[1]


def _count_phrase(n: int, noun: str) -> str:
    """Format ``"13 variables"`` / ``"1 variable"`` — a readable count, not the full list."""
    return f"{n} {noun}{'s' if n != 1 else ''}"


def _wfilter_body(step: ProcessingStep) -> str:
    """Summarise wfilter: collapse the per-variable ``action <var> = ...`` fields.

    Every variable typically gets the same action (e.g. ``median, 10``), so the eight
    identical lines collapse to ``median, 10 (8 variables)`` rather than one per channel.
    """
    counts: dict[str, int] = {}
    other: list[str] = []
    for k, v in step.params.items():
        if k.startswith("action "):
            counts[v] = counts.get(v, 0) + 1
        elif k not in _LEDGER_HOUSEKEEPING:
            other.append(f"{k}={v}")
    collapsed = [f"{val} ({_count_phrase(n, 'variable')})" for val, n in counts.items()]
    return " ".join(other + collapsed)


def _correction_body(step: ProcessingStep) -> str:
    """The salient parameter string for a module.

    Salient-listed modules show only those fields (wildedit also gets its variable list
    summarised as a count); wfilter collapses its per-variable actions; anything else
    falls back to all non-housekeeping parameters.  The verbatim ``sbe_processing`` block
    keeps every field regardless, so a trimmed summary loses nothing.
    """
    if step.module == "wfilter":
        return _wfilter_body(step)
    fields = _MODULE_SALIENT.get(step.module)
    if fields is None:
        parts = [
            f"{k}={v}" for k, v in step.params.items() if k not in _LEDGER_HOUSEKEEPING
        ]
        return " ".join(parts)
    parts = [f"{k}={step.params[k]}" for k in fields if k in step.params]
    if step.module == "wildedit" and "vars" in step.params:
        parts.append(_count_phrase(len(step.params["vars"].split()), "variable"))
    return " ".join(parts)


def _deck_advances(deck: DeckUnit) -> str:
    """The deck-unit advance string, keeping SBE channel names (``primary conductivity``)."""
    return ", ".join(f"{chan} +{sec:.3f} s" for chan, sec in deck.advance.items())


def _correction_records(acq: Acquisition, chain: ProcessingChain) -> list[Correction]:
    """Build the structured corrections from a parsed acquisition and chain, in file order."""
    records: list[Correction] = []
    if acq.deck_unit.advance:
        records.append(
            Correction(
                label="align (deck)",
                key="align",
                producer=f"{acq.deck_unit.model or 'SBE'} deck unit",
                version=acq.deck_unit.firmware or "",
                parameters=_deck_advances(acq.deck_unit),
            )
        )
    run_count: dict[str, int] = {}
    for step in chain.steps:
        run_count[step.module] = run_count.get(step.module, 0) + 1
        n = run_count[step.module]
        records.append(
            Correction(
                label=step.module if n == 1 else f"{step.module} ({n})",
                key=step.module if n == 1 else f"{step.module}_{n}",
                producer="SBE Data Processing",
                version=_module_version(step.params),
                parameters=_correction_body(step),
            )
        )
    return records


def correction_records(header_text: str) -> list[Correction]:
    """Return the structured corrections (deck-unit align + each module) in file order.

    The display counterpart of the flat ``correction_<key>`` ledger attributes: same
    records, split into producer / version / parameters instead of one string.
    """
    if not header_text:
        return []
    return _correction_records(
        parse_star_block(header_text), parse_processing_chain(header_text)
    )


def sbe_history_notes(header_text: str) -> list[SbeHistoryNote]:
    """Return one history note per **timestamped** SBE Data Processing module, file order.

    Attributed to Sea-Bird so a stage-1 file's ``history`` shows what SBE did before
    ctdcast, oldest-first. A module with no ``_date`` line — the third-party dialect that
    emits none — is skipped, because a history line needs a stamp and it has none: such a
    module still appears in ``correction_<module>`` and ``sbe_processing_order`` but not in
    ``history``. The deck-unit align has no timestamp either and is recorded only as
    ``correction_align``. The note body is the same summary the ledger uses.
    """
    if not header_text:
        return []
    notes: list[SbeHistoryNote] = []
    for step in parse_processing_chain(header_text).steps:
        timestamp, version = _module_date_parts(step.params)
        if not timestamp:  # no date -> no stamp -> no history line
            continue
        notes.append(
            SbeHistoryNote(
                timestamp=timestamp,
                version=version,
                stage=step.module,
                note=_correction_body(step),
            )
        )
    return notes


def _is_pressure_bin(bintype: str) -> bool:
    """True when a ``binavg`` bin type is a pressure axis.

    Only ``decibars`` is confirmed in the corpus. SBE's Bin Average also offers depth and
    scan-number bins; do not match a guessed ``meters`` string — verify what SBE writes for
    a depth bin before adding it here.
    """
    return bintype.strip().casefold() == "decibars"


def provenance_advisories(header_text: str) -> list[str]:
    """Structural implications of the SBE ledger — what the file *is* and what was done.

    Each is a fact about the cast and its consequence, not a comparison to any
    recommendation. The single source for both a stage-1 warning and the note under the
    cast-page provenance table, so the two never drift. (The SBE-conformance check — where a
    cast deviates from Sea-Bird's *published* recommendation — is a separate, later concern
    and deliberately not here.)
    """
    if not header_text:
        return []
    acq = parse_star_block(header_text)
    start = parse_start_time(header_text)
    chain = parse_processing_chain(header_text)
    advisories: list[str] = []

    if any(
        step.module == "binavg" and _is_pressure_bin(step.params.get("bintype", ""))
        for step in chain.steps
    ):
        advisories.append(
            "Already binned to a pressure grid before ctdcast read it — a terminal product "
            "entering mid-sequence. No time-domain correction (conductivity alignment, cell "
            "thermal mass, loop edit) can be applied to it, because pressure-binning discarded "
            "the scan-level time series they need."
        )

    # A conductivity advance other than the factory default is worth flagging: the SBE manual
    # allows channels to need different lags (plumbing differs), so a non-default value is not
    # necessarily a residual — but it is a deviation the reader should judge.
    # Compare rounded to the 3 decimals the message shows, so a value that displays as the
    # default is never flagged as differing from it.
    nondefault = {
        ch: sec
        for ch, sec in acq.deck_unit.advance.items()
        if "conductivity" in ch
        and round(sec, 3) != round(_DEFAULT_CONDUCTIVITY_ADVANCE, 3)
    }
    if nondefault:
        parts = ", ".join(f"{ch} +{sec:.3f} s" for ch, sec in nondefault.items())
        advisories.append(
            f"Deck-unit conductivity advance is non-default ({parts}; SBE's factory value is "
            f"+{_DEFAULT_CONDUCTIVITY_ADVANCE:.3f} s). The correct advance depends on the "
            "channel's plumbing, so this may be deliberate or may leave a residual that spikes "
            "salinity at sharp temperature steps — confirm from the data."
        )

    # Only claim an offset when both clocks parsed; offset_seconds is None otherwise.
    if start.clock == "system" and acq.clocks.offset_seconds is not None:
        advisories.append(
            "The time coordinate is on the ship's system clock, not GPS — the two differed by "
            f"{acq.clocks.offset_seconds} s at acquisition."
        )

    return advisories


#: Config ``<Sensors>`` element tag -> frequency-sensor kind. Voltage sensors (pH,
#: oxygen, altimeter, transmissometer…) are absent by design: their Slope/Offset is a
#: native calibration, not the datcnv drift knob this reads.
_FREQUENCY_SENSOR_TAGS = {
    "TemperatureSensor": "temperature",
    "ConductivitySensor": "conductivity",
    "PressureSensor": "pressure",
}
#: Slope/offset within this tolerance of the identity (slope 1, offset 0) read as "no
#: drift correction applied" -- sub-ppm departures are calibration noise, not a correction.
_CAL_IDENTITY_TOL = 5e-7


def _sensors_region(header_text: str) -> str | None:
    """Return the ``<Sensors>…</Sensors>`` config block, ``#`` prefixes stripped, or None.

    The block is embedded in the CNV header as ``#``-commented XML. Stripping the leading
    ``#`` yields a well-formed element that :mod:`xml.etree` can parse. Returns None when
    no block is present (a header that carries no embedded configuration).
    """
    region: list[str] = []
    in_block = False
    for raw in header_text.splitlines():
        stripped = raw.strip()
        body = stripped[1:].strip() if stripped.startswith("#") else stripped
        if body.startswith("<Sensors"):
            in_block = True
        if in_block:
            region.append(body)
        if body.startswith("</Sensors"):
            break
    return "\n".join(region) if in_block else None


def _cal_value_nondefault(value: str, default: float) -> bool:
    """True when *value* departs from *default* beyond the identity tolerance.

    An unparseable value reads as default: a drift that cannot be read is not claimed.
    """
    try:
        return abs(float(value) - default) > _CAL_IDENTITY_TOL
    except ValueError:
        return False


def sensor_calibrations(header_text: str) -> list[SensorCalibration]:
    """Read each frequency sensor's drift Slope/Offset from the CNV ``<Sensors>`` config.

    Surfaces whether a drift or span correction is already baked into the data before
    ctdcast read it (see :class:`SensorCalibration`). Only temperature, conductivity and
    pressure sensors are returned, in config order; voltage sensors are skipped because
    their Slope/Offset is a native calibration rather than a datcnv drift knob. Dual
    sensors are labelled ``<kind>_1``/``<kind>_2`` and a lone sensor keeps the bare kind.
    Returns an empty list for an empty header, a header with no ``<Sensors>`` block, or an
    unparseable block (the block is a convenience read over the verbatim header).
    """
    if not header_text:
        return []
    region = _sensors_region(header_text)
    if region is None:
        return []
    try:
        root = ET.fromstring(region)
    except ET.ParseError:
        return []

    found: list[tuple[str, str, str, str]] = []
    for elem in root.iter():
        kind = _FREQUENCY_SENSOR_TAGS.get(elem.tag)
        if kind is None:
            continue
        serial = (elem.findtext("SerialNumber") or "").strip()
        slope = (elem.findtext("Slope") or "1.0").strip()
        offset = (elem.findtext("Offset") or "0.0").strip()
        found.append((kind, serial, slope, offset))

    totals: dict[str, int] = {}
    for kind, *_ in found:
        totals[kind] = totals.get(kind, 0) + 1
    seen: dict[str, int] = {}
    calibrations: list[SensorCalibration] = []
    for kind, serial, slope, offset in found:
        seen[kind] = seen.get(kind, 0) + 1
        label = kind if totals[kind] == 1 else f"{kind}_{seen[kind]}"
        calibrations.append(
            SensorCalibration(
                kind=kind,
                label=label,
                serial=serial,
                slope=slope,
                offset=offset,
                slope_nondefault=_cal_value_nondefault(slope, 1.0),
                offset_nondefault=_cal_value_nondefault(offset, 0.0),
            )
        )
    return calibrations


def _correction_flat(rec: Correction) -> str:
    """Flatten a :class:`Correction` to its one-line ``correction_<key>`` attribute value."""
    head = f"{rec.producer} {rec.version}".strip()
    return f"{head}: {rec.parameters}" if rec.parameters else head


def build_correction_ledger(header_text: str) -> dict[str, str | float]:
    """Build the stage-1 correction ledger from an SBE header.

    Records what was done to the cast before ctdcast read it, so a later stage does not
    re-apply a correction already made. Two verbatim blocks (``sbe_acquisition``,
    ``sbe_processing``) are the ground truth; the structured attributes are convenience
    summaries over them: the module order, the deck-unit alignment, one
    ``correction_<module>`` per step in the chain (a repeat suffixed ``_2``, ``_3``…),
    and the time coordinate's source and offset. Every module gets a summary — deciding
    which "count" as corrections would require predicting them. An attribute is written
    only when the header supports it; an absent ``correction_<name>`` means "not
    recorded", never "not done". Returns an empty mapping for an empty or missing header
    (e.g. a LADCP file), so the caller can update attributes unconditionally.
    """
    if not header_text:
        return {}
    acq = parse_star_block(header_text)
    start = parse_start_time(header_text)
    chain = parse_processing_chain(header_text)

    ledger: dict[str, str | float] = {}
    if acq.verbatim:
        ledger["sbe_acquisition"] = acq.verbatim
    if chain.verbatim:
        ledger["sbe_processing"] = chain.verbatim

    order: list[str] = []
    # Record the deck unit unconditionally -- "present and set to zero" differs from
    # "no deck unit" -- but add the align(deck) order token only when it actually
    # advanced something, so a zero-set unit does not read as an alignment.
    if acq.deck_unit.advance and any(
        sec != 0.0 for sec in acq.deck_unit.advance.values()
    ):
        order.append("align(deck)")
    order.extend(step.module for step in chain.steps)
    if order:
        ledger["sbe_processing_order"] = " ".join(order)

    # One correction_<key> per record; a module that runs more than once is suffixed
    # (correction_celltm, correction_celltm_2) so a repeat's parameters are never lost.
    for rec in _correction_records(acq, chain):
        ledger[f"correction_{rec.key}"] = _correction_flat(rec)

    if start.source:
        # SBE's own phrasing ("System UTC, first data scan."), which round-trips against
        # the verbatim header; the resolved clock/anchor drive the guards, not this text.
        ledger["time_coordinate_source"] = start.source
    if acq.clocks.offset_seconds is not None:
        ledger["time_clock_offset_seconds"] = acq.clocks.offset_seconds

    return ledger
