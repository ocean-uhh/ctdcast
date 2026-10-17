"""Declare and resolve the preferred sensor per cast — one mechanism, two groups.

A dual-sensor cast carries a primary and a secondary measurement for each role; which
is *better* is a human judgement made on noise, not derivable from calibration.  The
cruise config declares the choice as a cruise-wide ``default`` plus per-cast-range
exceptions, in channel terms (``primary`` / ``secondary``); ctdcast resolves it per cast
and (elsewhere) stamps it.

The same resolve → derive-segments → validate logic serves two independent groups —
the T/C pair (which governs temperature, salinity and conductivity together, because
salinity needs a matched pair) and oxygen — so every function here takes a
:class:`SensorGroup` descriptor and never branches on which group.  ``PREFERRED_PAIR``
and ``PREFERRED_OXYGEN`` are the only group-specific data.

Primary vs secondary is the sensor **role index** (``temperature_1`` / ``temperature_2``),
which matches the variable suffix (``ctd_temperature_1`` / ``_2``) — *not* the
``sensor_channel`` field, which is the CNV wiring position (primary conductivity sits on
channel 2).  The declaration is by that index; the physical sensor is an independent,
verification-only record stamped at write time (the catalog variable name per role), so a
later mismatch is detectable.  Serials never enter the config a human types.
"""

from __future__ import annotations

from dataclasses import dataclass

from ctdcast.identity import expand_cast_numbers

#: The closed set of declaration values; the 0/1 CNV-vs-ctdcast ambiguity is why a digit
#: is refused rather than mapped — the declaration is words ("primary"/"secondary"), not numbers.
USE_VALUES: frozenset[str] = frozenset({"primary", "secondary"})

#: ``primary`` / ``secondary`` map to the role (and variable) index suffix.
_INDEX_OF_USE: dict[str, int] = {"primary": 1, "secondary": 2}


@dataclass(frozen=True)
class SensorGroup:
    """A set of channels governed by one preferred-choice declaration.

    Parameters
    ----------
    config_key : str
        The ``processing:`` sub-key carrying the declaration — ``"preferred_pair"`` or
        ``"preferred_oxygen"``.  Also the attribute name stamped on the output.
    members : tuple of str
        The composite (plain, unsuffixed) variables this one choice governs, built from
        the preferred channel per cast — e.g. ``("ctd_temperature", "ctd_salinity",
        "conductivity")`` for the pair, ``("ctd_oxygen",)`` for oxygen.
    preferred_roles : tuple of str
        The **base** roles whose physical sensor the choice selects (for the
        ``sensor_<role>_preferred`` stamp and the single-sensor presence test) —
        ``("temperature", "conductivity")`` for the pair, ``("oxygen",)`` for oxygen.
        The chosen indexed role is ``f"{base}_{index}"`` with ``index`` from the use word.
    segment_roles : tuple of str
        The **indexed** catalog roles whose serial defines a hardware segment; a change in
        *any* of them starts a new segment.  The T/C pair uses all four
        (``temperature_1/2``, ``conductivity_1/2``); oxygen adds its line's T/C, because the
        O₂ saturation/AOU derivation uses that line's temperature and salinity.
    """

    config_key: str
    members: tuple[str, ...]
    preferred_roles: tuple[str, ...]
    segment_roles: tuple[str, ...]


#: The T/C pair: one choice governs temperature, salinity and conductivity (matched for
#: the salinity computation); segments break on any of the four T/C serials.
PREFERRED_PAIR = SensorGroup(
    config_key="preferred_pair",
    members=("ctd_temperature", "ctd_salinity", "conductivity"),
    preferred_roles=("temperature", "conductivity"),
    segment_roles=(
        "temperature_1",
        "conductivity_1",
        "temperature_2",
        "conductivity_2",
    ),
)

#: Oxygen: independent hardware, its own choice.  Its derivation uses its line's T/S, so
#: a T/C swap on that line is a segment boundary for oxygen too.
PREFERRED_OXYGEN = SensorGroup(
    config_key="preferred_oxygen",
    members=("ctd_oxygen",),
    preferred_roles=("oxygen",),
    segment_roles=(
        "oxygen_1",
        "oxygen_2",
        "temperature_1",
        "conductivity_1",
        "temperature_2",
        "conductivity_2",
    ),
)

#: Every group ctdcast resolves.
GROUPS: tuple[SensorGroup, ...] = (PREFERRED_PAIR, PREFERRED_OXYGEN)

# The per-profile stamp names variables `sensor_<role>_preferred`, so two groups sharing a
# preferred role would collide on one variable (the later group silently overwriting the
# earlier). Enforce disjoint preferred roles here, so adding a colliding group fails loudly
# at import rather than dropping a sensor record from profiles.nc.
_all_preferred_roles = [role for g in GROUPS for role in g.preferred_roles]
if len(_all_preferred_roles) != len(set(_all_preferred_roles)):
    raise ValueError(
        f"GROUPS share a preferred role, which would collide on sensor_<role>_preferred: "
        f"{sorted(_all_preferred_roles)}"
    )


def index_of(use: str) -> int:
    """Return the role/variable index suffix for a use word.

    Parameters
    ----------
    use : str
        ``"primary"`` or ``"secondary"``.

    Returns
    -------
    int
        ``1`` for ``"primary"``, ``2`` for ``"secondary"`` — the suffix on the indexed role
        (``temperature_1``) and variable (``ctd_temperature_1``).
    """
    return _INDEX_OF_USE[use]


def _validate_use(value: object, where: str) -> str:
    """Return *value* if it is a valid use word, else raise ValueError naming *where*."""
    if value not in USE_VALUES:
        raise ValueError(
            f"{where}: preferred-sensor value {value!r} is not one of "
            f"{sorted(USE_VALUES)} (a digit is refused — the 0/1 CNV-vs-ctdcast ambiguity)"
        )
    return str(value)


def _as_declaration(decl: object, config_key: str) -> dict:
    """Return *decl* as a mapping, raising a clear ValueError if it is not one.

    Guards the shorthand mistake ``preferred_pair: primary`` (a bare scalar) in place of
    the nested ``preferred_pair: {default: primary}``; without this the scalar would reach
    ``.get(...)`` and raise an opaque ``AttributeError`` mid-run.
    """
    if not isinstance(decl, dict):
        raise ValueError(
            f"{config_key}: declaration must be a mapping with 'default' and/or 'ranges' "
            f"(got {type(decl).__name__} {decl!r}); write "
            f"'{config_key}: {{default: {decl!r}}}', not '{config_key}: {decl!r}'."
        )
    return decl


def _range_casts(rng: object, config_key: str, i: int) -> object:
    """Return a range entry's ``casts`` spec, raising a clear ValueError if absent."""
    if not isinstance(rng, dict) or "casts" not in rng:
        raise ValueError(
            f"{config_key} range {i}: each range needs a 'casts' key "
            f"(e.g. casts: [[31, 60]]); got {rng!r}."
        )
    return rng["casts"]


def _has_casts(rng: object) -> bool:
    """Return True if *rng* is a mapping carrying a non-empty ``casts`` spec."""
    return isinstance(rng, dict) and bool(rng.get("casts"))


def resolve_preferred(
    group: SensorGroup, cruise_cfg: dict, cast_number: int
) -> tuple[str | None, str | None]:
    """Resolve the declared choice for one cast, from config alone.

    Parameters
    ----------
    group : SensorGroup
        The group whose declaration to read (``group.config_key`` in *cruise_cfg*).
    cruise_cfg : dict
        The ``processing:`` config block (``cruise_cfg[group.config_key]`` is the nested
        ``{default, ranges}`` declaration, or absent).
    cast_number : int
        The cast's integer number (a lettered cast resolves by its number).

    Returns
    -------
    tuple of (str or None, str or None)
        ``(use, source)`` where *use* is ``"primary"`` / ``"secondary"`` / ``None``
        (undeclared for this cast) and *source* is ``"range"`` / ``"default"`` / ``None``.
        The caller (the stamp step) needs *source* to tell an explicit declaration
        (refuse when impossible) from a cruise-wide default (skip silently).

    Raises
    ------
    ValueError
        On a declaration that is not a mapping, a range missing its ``casts`` key, a value
        outside :data:`USE_VALUES`, or two ranges covering this cast with different ``use``
        (a conflicting overlap).
    """
    raw = cruise_cfg.get(group.config_key) if cruise_cfg else None
    # Distinguish an ABSENT declaration (key missing → None) from a present-but-falsey one
    # (``preferred_pair: 0`` / ``false``): the latter is malformed and must be refused by
    # _as_declaration, not silently treated as undeclared. An empty mapping ``{}`` is a
    # dict, passes _as_declaration, and resolves to undeclared below.
    if raw is None:
        return None, None
    decl = _as_declaration(raw, group.config_key)

    matches: list[str] = []
    for i, rng in enumerate(decl.get("ranges") or []):
        casts = _range_casts(rng, group.config_key, i)
        if cast_number in expand_cast_numbers(casts):
            matches.append(
                _validate_use(rng.get("use"), f"{group.config_key} range {i}")
            )
    if matches:
        if len(set(matches)) > 1:
            raise ValueError(
                f"{group.config_key}: cast {cast_number} is covered by ranges declaring "
                f"different pairs {sorted(set(matches))}"
            )
        return matches[0], "range"

    default = decl.get("default")
    if default is not None:
        return _validate_use(default, f"{group.config_key} default"), "default"
    return None, None


def _names_by_role(records: list[dict]) -> dict[str, str]:
    """Return ``{indexed role: catalog variable name}`` for a cast's catalog records."""
    return {rec["role"]: rec["name"] for rec in records if rec.get("role")}


def preferred_sensor_names(
    group: SensorGroup, records: list[dict], use: str
) -> dict[str, str]:
    """Return ``{base role: catalog variable name}`` for the chosen sensors on this cast.

    For each of ``group.preferred_roles``, resolves the indexed role ``f"{role}_{index}"``
    (index from *use*) to its ``SENSOR_*`` catalog name.  A role with no such entry is
    omitted — the caller decides whether that absence is a refusal (explicit choice) or a
    silent skip (cruise-wide default).

    Parameters
    ----------
    group : SensorGroup
        The group whose ``preferred_roles`` to resolve.
    records : list of dict
        The cast's ``SENSOR_*`` catalog records (``name`` / ``role`` / ``channel`` / ``attrs``).
    use : str
        ``"primary"`` or ``"secondary"`` — which indexed sensor to select.

    Returns
    -------
    dict of {str: str}
        ``{base role: catalog variable name}`` for the roles present on this cast; roles the
        cast lacks are omitted.
    """
    names = _names_by_role(records)
    idx = index_of(use)
    out: dict[str, str] = {}
    for role in group.preferred_roles:
        name = names.get(f"{role}_{idx}")
        if name is not None:
            out[role] = name
    return out


def has_use(group: SensorGroup, records: list[dict], use: str) -> bool:
    """Return True if every preferred role of *group* has a sensor for *use* on this cast.

    Parameters
    ----------
    group : SensorGroup
        The group whose ``preferred_roles`` must all be present.
    records : list of dict
        The cast's ``SENSOR_*`` catalog records.
    use : str
        ``"primary"`` or ``"secondary"``.

    Returns
    -------
    bool
        False on a single-sensor cast asked for its missing channel (e.g. ``secondary``
        where only ``temperature_1`` / ``conductivity_1`` exist).
    """
    names = _names_by_role(records)
    idx = index_of(use)
    return all(f"{role}_{idx}" in names for role in group.preferred_roles)


def has_choice(group: SensorGroup, records: list[dict]) -> bool:
    """Return True if this cast has a genuine primary-vs-secondary choice for *group*.

    A choice exists only when **both** channels are present (e.g. ``oxygen_1`` *and*
    ``oxygen_2``).  A single-sensor cast has no choice: its one sensor is already the plain
    composite (stage-1 promotes a lone sensor to the unsuffixed name), so no preferred
    declaration applies and nothing is stamped.

    Parameters
    ----------
    group : SensorGroup
        The group to test.
    records : list of dict
        The cast's ``SENSOR_*`` catalog records.

    Returns
    -------
    bool
        True only when both ``primary`` and ``secondary`` sensors are present for every
        preferred role of *group*.
    """
    return has_use(group, records, "primary") and has_use(group, records, "secondary")


def _segment_key(group: SensorGroup, records: list[dict]) -> tuple[str | None, ...]:
    """Return the catalog-name tuple identifying a cast's hardware for *group*.

    One entry per ``group.segment_roles`` member, in order: the ``SENSOR_*`` catalog
    variable name for that indexed role, or ``None`` when the cast has no such sensor.
    Two casts with equal keys share a hardware configuration.
    """
    names = _names_by_role(records)
    return tuple(names.get(role) for role in group.segment_roles)


def derive_segments(
    group: SensorGroup, catalog_by_cast: dict[int, list[dict]]
) -> list[tuple[int, int, tuple[str | None, ...], frozenset[int]]]:
    """Derive runs of consecutive casts sharing one hardware configuration.

    A boundary is any cast where the :func:`_segment_key` (the catalog names of the
    group's :attr:`~SensorGroup.segment_roles`) changes — never a hardcoded cast count.

    Parameters
    ----------
    group : SensorGroup
        The group whose serials define the segments.
    catalog_by_cast : dict of {int: list of dict}
        Per-cast ``SENSOR_*`` catalog records (from
        ``processors.sensor_catalog.read_cast_sensor_catalog``), keyed by cast number.

    Returns
    -------
    list of tuple(int, int, tuple, frozenset of int)
        ``(first_cast, last_cast, segment_key, casts)`` for each run, in cast order.
        ``casts`` is the set of cast numbers actually in the run — not every integer in
        ``[first, last]``, so reconciliation stays correct when cast numbering has gaps.
    """
    runs: list[tuple[tuple[str | None, ...], list[int]]] = []
    for cast in sorted(catalog_by_cast):
        key = _segment_key(group, catalog_by_cast[cast])
        if runs and runs[-1][0] == key:
            runs[-1][1].append(cast)
        else:
            runs.append((key, [cast]))
    return [(casts[0], casts[-1], key, frozenset(casts)) for key, casts in runs]


def validate_preferred(
    group: SensorGroup, cruise_cfg: dict, catalog_by_cast: dict[int, list[dict]]
) -> list[str]:
    """Return advisory warnings reconciling the declaration against derived segments.

    Warnings only, and **never raises** — a partially declared cruise is a normal
    mid-processing state, and reconciliation runs at compile time where it must not block.
    A group with **no** declaration at all is silent (declaring one group, both, or neither
    is valid).  A malformed declaration (a scalar shorthand, a range missing ``casts``),
    out-of-set values, and conflicting overlaps are all :func:`resolve_preferred`'s job to
    refuse loudly at stamp time — here they are skipped, not re-raised.  For a well-formed
    declared group, two conditions warn: a declared range that **crosses** a hardware
    segment boundary (the human's cast range does not match where sensors actually
    changed), and a derived segment the declaration does not cover at all.

    Parameters
    ----------
    group : SensorGroup
        The group to check.
    cruise_cfg : dict
        The ``processing:`` config block.
    catalog_by_cast : dict of {int: list of dict}
        Per-cast catalog records, keyed by cast number.

    Returns
    -------
    list of str
        Human-readable warning strings naming the casts; empty when coherent.
    """
    raw = (cruise_cfg.get(group.config_key) if cruise_cfg else None) or {}
    if not isinstance(raw, dict) or not raw:
        # An entirely undeclared group is a valid, silent state; a malformed declaration
        # (a scalar shorthand) is the stamp's job to refuse loudly (resolve_preferred raises)
        # — reconciliation stays advisory and never raises, so it cannot block a compile.
        return []
    decl = raw
    segments = derive_segments(group, catalog_by_cast)
    warnings: list[str] = []

    # Each range's actual covered cast numbers, expanded once and reused by both checks.
    # A range whose `casts` is missing OR malformed is skipped (the empty set matches no
    # segment) — reconciliation is advisory and must never raise; the stamp
    # (resolve_preferred) is what refuses a malformed spec loudly.
    range_casts: list[set[int]] = []
    for rng in decl.get("ranges") or []:
        try:
            covered = (
                set(expand_cast_numbers(rng["casts"])) if _has_casts(rng) else set()
            )
        except (ValueError, TypeError, KeyError):
            covered = set()
        range_casts.append(covered)

    for i, rng in enumerate(decl.get("ranges") or []):
        covered = range_casts[i]
        # A range that touches more than one hardware segment crosses a swap boundary —
        # whether it straddles the boundary partially or encloses several segments whole.
        # Intersect with each segment's *actual* casts so a numbering gap cannot make a
        # range appear to reach a segment it has no casts in.
        spanned = [
            (first, last) for first, last, _key, casts in segments if covered & casts
        ]
        if len(spanned) >= 2:
            boundaries = ", ".join(f"{f}-{last}" for f, last in spanned)
            warnings.append(
                f"{group.config_key} range {i} ({rng['casts']}) crosses the hardware "
                f"segment boundary — it spans segments {boundaries}; the declared range does "
                f"not match where sensors changed"
            )

    if decl.get("default") is None:
        declared: set[int] = set().union(*range_casts) if range_casts else set()
        for first, last, _key, casts in segments:
            if not (casts & declared):
                warnings.append(
                    f"{group.config_key}: hardware segment casts {first}-{last} has no "
                    f"declaration (no default, no covering range)"
                )
    return warnings
