"""Stage 1 — CNV-to-netCDF conversion.

Defines the CtdBackend Protocol, concrete backend implementations, and
``stage1()``, the public function that converts a directory of CNV files
to per-cast netCDF.  To add a new backend implement CtdBackend and add a
branch in ``get_ctd_backend()`` — nothing else changes.

The ``converters`` module re-exports these names for backward compatibility.
"""

from __future__ import annotations

import contextlib
import io
import logging
import sys
import warnings
from pathlib import Path
from typing import Protocol

import numpy as np
import xarray as xr

from ctdcast.config.cnv_header import (
    build_correction_ledger,
    conformance_advisories,
    header_from_raw_metadata,
    provenance_advisories,
    sbe_history_notes,
)
from ctdcast.config.global_attrs import identity_attrs
from ctdcast.config.parameters import (
    CAST_TAG_WIDTH,
    CNV_ALIASES,
    VARIABLES,
    resolve_sensor_var,
)
from ctdcast.config.sensors import (
    FREQUENCY_ROLES,
    ROLE_VARIABLE,
    SensorOverrides,
    SensorRegistry,
    catalog_var_name,
    resolve_sensor,
    role_base,
)
from ctdcast.processors._warnings import summarise_warnings
from ctdcast.processors.history import (
    PL_CONVERTED,
    add_processing_level,
    append_history,
)
from ctdcast.identity import cast_id_from_name, format_cast_id
from ctdcast.processors.stage_layout import stage_dir, stage_path
from ctdcast.readers.metadata import parse_sensor_channels
from ctdcast.writers.netcdf import write as write_nc


# Stage 1 is a faithful translation: it drops nothing.  Every CNV column reaches the stage-1
# file (SBE-derived quantities under an ``sbe_`` prefix so they cannot be confused with
# ctdcast's own; unrecognised channels under the reader's source name, warned once).  The
# deliberate, recorded drop step lives at stage 2 (config ``trim.drop_sbe:``).

# Coordinate variables that _normalise must not warn about as kept-unknowns.
_KEEP_COORDS: frozenset[str] = frozenset({"latitude", "longitude", "time"})


def _normalise(ds: xr.Dataset, cruise_info: dict | None = None) -> xr.Dataset:
    """Rename variables to ctdcast canonical names — dropping nothing.

    Applied between the reader (seasenselib or future hex reader) and the
    ctdcast netCDF writer.  Both readers must produce a Dataset that this
    function can normalise into the same output shape.  Stage 1 is a **faithful
    translation**: every CNV column is kept.  The deliberate, recorded drop of the
    SeaBird-derived ``sbe_*`` channels happens at stage 2 (config ``trim.drop_sbe:``).

    Steps, in order:

    1. Rename variables using :data:`~ctdcast.config.parameters.CNV_ALIASES`
       (keys are lower-cased before lookup; two columns aliasing to one name keep
       the first, the duplicate stays under its own name), handle the oxygen unit
       variants, and convert conductivity from S/m to mS/cm (the CCHDO convention).
       SeaBird-computed quantities (density, depth, sound velocity, timeJ/S, flag,
       oxygen saturation) are renamed to an ``sbe_`` prefix so they cannot be
       mistaken for ctdcast's own; nothing is dropped.
    2. Record any ``None`` variable attribute the reader left as ``"UNK"``, and warn
       about kept channels with no ``VARIABLES`` entry or no ``units`` (not optional).
    3. Apply the single-sensor naming rule: when only one sensor of a measured
       type is present, strip the ``_1`` suffix so the variable is plain
       (e.g. ``ctd_temperature_1`` → ``ctd_temperature`` when there is no
       ``ctd_temperature_2``).
    4. Append a ``history`` line recording the ctdcast version and stage.
    5. Stamp the cruise identity (``cruise`` + ``platform_*`` + ``expocode``)
       when *cruise_info* supplies it, so a per-cast stage file is
       self-describing when copied out of its directory.
    6. Stamp the SBE upstream-provenance ledger (``sbe_acquisition``,
       ``sbe_processing``, ``sbe_processing_order``, ``correction_*``,
       ``time_*``) from the verbatim header in ``raw_metadata``, recording
       what the deck unit and SBE Data Processing did before ctdcast. A no-op
       when there is no SBE header (e.g. a LADCP file).

    Parameters
    ----------
    ds:
        Dataset as returned by the reader (seasenselib or hex reader).
    cruise_info:
        The config ``cruise_info:`` mapping.  ``None`` or empty writes no
        identity attributes, so a call path supplying no config is unchanged.

    Returns
    -------
    xr.Dataset
        Normalised Dataset ready for :func:`ctdcast.writers.netcdf.write`.
    """
    ds = ds.copy()

    # Step 1: rename via CNV_ALIASES (lowercase key lookup).  The reader
    # (seasenselib) records the raw column name per variable as
    # ``cnv_original_name``, so the source→canonical provenance survives these
    # renames without any extra bookkeeping here.
    rename_map: dict[str, str] = {}
    _claimed_by: dict[str, str] = {}
    for var in list(ds.data_vars):
        target = CNV_ALIASES.get(var.lower())
        if not target or target == var:
            continue
        # Two source columns can alias to one canonical name (e.g. a file carrying both
        # ``density`` and ``density00``).  First claim wins; a later duplicate keeps its own
        # name and surfaces as a kept-unknown rather than crashing the rename.  Which one wins
        # is reader column order and it can change numbers — anything computed from the target
        # (the µmol/L → µmol/kg oxygen conversion divides by ``sbe_density``) uses the winner —
        # so name both columns and the winner.
        if target in _claimed_by or target in ds.data_vars:
            _winner = _claimed_by.get(target, target)
            warnings.warn(
                f"two columns map to {target!r}: {_winner!r} won, {var!r} kept under its own "
                f"name (cnv_original_name records the source). Anything derived from {target!r} "
                "uses the winner.",
                stacklevel=3,
            )
            continue
        rename_map[var] = target
        _claimed_by[target] = var
    if rename_map:
        ds = ds.rename(rename_map)

    # Step 1b: handle seasenselib's oxygen_N vars, which may be % saturation, µmol/L, or
    # µmol/kg depending on the CNV column the sensor was on.  µmol/kg → ctd_oxygen_N (the basic
    # measured value); µmol/L → convert to µmol/kg using SBE density (now sbe_density, kept, not
    # dropped); % saturation → sbe_oxygen_saturation_N (SBE-derived, kept under the sbe_ prefix).
    # Step 3 strips the _1 suffix when single-sensor.  Also handles the hex-reader names
    # ('oxygen', 'oxygen2').  Volts arrive under a separate raw name (oxygen_raw_N), not here.
    for _v in ("oxygen_1", "oxygen_2", "oxygen", "oxygen2"):
        if _v not in ds.data_vars:
            continue
        _suffix = "1" if _v in ("oxygen_1", "oxygen") else "2"
        _units = ds[_v].attrs.get("units", "").lower().strip()
        if "umol/kg" in _units or "µmol/kg" in _units:
            ds = ds.rename({_v: f"ctd_oxygen_{_suffix}"})
        elif "umol/l" in _units or "µmol/l" in _units:
            if "sbe_density" in ds:
                # sbe_density is kg/m³; divide by 1000 to get kg/L, then µmol/L / (kg/L) = µmol/kg.
                rho = ds["sbe_density"] / 1000.0
                converted = ds[_v] / rho
                new_attrs = dict(ds[_v].attrs)
                new_attrs["units"] = "umol/kg"
                new_attrs["comment"] = (
                    "converted from umol/l to umol/kg using SBE density"
                )
                converted.attrs = new_attrs
                ds = ds.drop_vars([_v]).assign({f"ctd_oxygen_{_suffix}": converted})
            else:
                # No density to convert with — keep it under its source name (stage 1 drops
                # nothing) and warn; it surfaces as a kept-unknown below.
                warnings.warn(
                    f"Oxygen variable {_v!r} is in µmol/L but no SBE density is available to "
                    "convert it; kept under its source name.",
                    stacklevel=3,
                )
        else:
            ds = ds.rename({_v: f"sbe_oxygen_saturation_{_suffix}"})

    # Step 1c: convert conductivity from S/m to mS/cm — the CCHDO/oceanographic
    # convention and what gsw.SP_from_C expects.  1 S/m = 10 mS/cm.  Guarded on
    # the source units so a file already in mS/cm is not double-converted.  The
    # seasenselib reader now emits mS/cm directly, so on those files this guard
    # is a no-op; the conversion body remains for any reader that hands us S/m
    # (a future hex reader, or a differently-configured CNV) and is marked
    # no-cover because no real fixture can exercise it while seasenselib is the
    # only reader.
    for _c in ("conductivity_1", "conductivity_2"):
        if _c not in ds.data_vars:
            continue
        _u = ds[_c].attrs.get("units", "").lower().replace(" ", "").replace("^", "")
        if _u in (
            "s/m",
            "sm-1",
            "sm⁻1",
            "siemens/m",
            "siemenspermetre",
        ):  # pragma: no cover
            converted = ds[_c] * 10.0
            _attrs = dict(ds[_c].attrs)
            _attrs["units"] = "mS cm-1"
            _attrs["comment"] = "converted from S m-1 to mS cm-1 (factor 10)"
            converted.attrs = _attrs
            ds = ds.assign({_c: converted})

    # The reader stamps None for a per-variable attribute it could not fill (e.g.
    # cnv_original_unit on a column with no unit).  netCDF cannot serialize None; record it as
    # "UNK" — never a silent drop or default — so the file keeps that the source had no value.
    # Scoped to the reader boundary and to variable attrs: a None on the provenance backbone
    # (a global tracking_id / cruise) must still reach the writer and crash, not be rewritten.
    for _var in ds.variables:
        _attrs = ds[_var].attrs
        for _key, _val in list(_attrs.items()):
            if _val is None:
                _attrs[_key] = "UNK"

    # Stage 1 drops nothing — a faithful translation.  Two warn-only checks: kept-unknown
    # channels (no VARIABLES entry) are kept under their source name; and units are not
    # optional, so warn naming any kept-unknown the reader left without units (variables in
    # VARIABLES receive their units from the writer).
    _unknown = sorted(
        str(v) for v in ds.data_vars if v not in VARIABLES and v not in _KEEP_COORDS
    )
    if _unknown:
        warnings.warn(
            f"stage 1 kept {len(_unknown)} channel(s) with no VARIABLES entry "
            f"({', '.join(_unknown)}); add a VARIABLES entry to give them units and a long_name.",
            stacklevel=3,
        )
        _no_units = [
            v for v in _unknown if not str(ds[v].attrs.get("units", "")).strip()
        ]
        if _no_units:
            warnings.warn(
                f"stage 1 kept {len(_no_units)} variable(s) with no units "
                f"({', '.join(_no_units)}); units are not optional.",
                stacklevel=3,
            )

    # Step 3: single-sensor naming — strip _1 when no _2 sibling exists.
    # Only applies to scientific end-product variables (T/S/O); conductivity
    # is an intermediate quantity and keeps its _1 suffix regardless.
    _SUFFIXED_PAIRS = [
        ("ctd_temperature_1", "ctd_temperature_2", "ctd_temperature"),
        ("ctd_salinity_1", "ctd_salinity_2", "ctd_salinity"),
        ("ctd_oxygen_1", "ctd_oxygen_2", "ctd_oxygen"),
        (
            "sbe_oxygen_saturation_1",
            "sbe_oxygen_saturation_2",
            "sbe_oxygen_saturation",
        ),
    ]
    for v1, v2, plain in _SUFFIXED_PAIRS:
        if v1 in ds.data_vars and v2 not in ds.data_vars:
            ds = ds.rename({v1: plain})

    # Step 4: append history.  The SBE upstream steps predate the reader's own line, so
    # they are prepended (in reverse file order, so the earliest module ends up first) to
    # keep the record oldest-first; ctdcast's stage-1 line is then appended at the end.
    # The header comes from raw_metadata, computed once here and reused for the ledger.
    header = header_from_raw_metadata(ds.attrs.get("raw_metadata"))
    if header:
        for n in reversed(sbe_history_notes(header)):
            append_history(
                ds.attrs,
                n.note,
                stage=n.stage,
                version=n.version,
                producer="SBE Data Processing",
                timestamp=n.timestamp,
                prepend=True,
            )
    append_history(ds.attrs, "normalise (CNV → canonical names)", stage="stage1")

    # Step 5: stamp the immutable cruise identity.  identity_attrs returns {} when
    # cruise_info is None/empty, so this is a no-op for callers that pass no config
    # (e.g. the stage-1 tests).  Config remains the source of truth: the compiler
    # re-applies it and warns on disagreement, so this is a portability snapshot,
    # not a second authority.
    ds.attrs.update(identity_attrs(cruise_info))

    # Step 6: stamp the SBE upstream-provenance ledger, read from the same verbatim
    # header.  Records what the deck unit and SBE Data Processing did before ctdcast, so
    # a later stage cannot re-apply a correction already made.  No-op with no SBE header.
    # Structural advisories (pressure-gridded, asymmetric advance, system clock) are also
    # raised as warnings; the batch collapses identical ones via summarise_warnings.
    # Conformance advisories (parameters that deviate from a documented reference) are a
    # separate loop so summarise_warnings collapses each class on its own; a no-op for an
    # empty header or an instrument outside the SBE 9 family.
    if header:
        ds.attrs.update(build_correction_ledger(header))
        for advisory in provenance_advisories(header):
            warnings.warn(advisory, stacklevel=2)
        for advisory in conformance_advisories(header):
            warnings.warn(advisory, stacklevel=2)

    return ds


def _sensor_variable(role: str, ds: xr.Dataset) -> str | None:
    """The data variable a sensor *role* maps to in *ds*, or None if it stores none.

    Joins the header's role vocabulary to ctdcast's variable names via
    :data:`~ctdcast.config.sensors.ROLE_VARIABLE`, then resolves the single-vs-dual spelling
    the dataset actually holds (``_normalise`` step 4 strips ``_1`` on a single-sensor cast).
    A role absent from ``ROLE_VARIABLE`` (transmissometer, pH, SPAR/PAR) stores no variable
    and returns None.
    """
    base = role_base(role)
    var_base = ROLE_VARIABLE.get(base)
    if var_base is None:
        return None
    suffix = role[len(base) :] if role != base else ""  # "_1"/"_2" for an indexed role
    return resolve_sensor_var(ds, f"{var_base}{suffix}")


def _build_cast_sensor_catalog(
    ds: xr.Dataset, overrides: SensorOverrides
) -> xr.Dataset:
    """Add this cast's ``SENSOR_<TYPE>_<SERIAL>`` catalog and link each data variable to it.

    One link out, everything else on the entry: a data variable that maps to a sensor carries
    exactly ``sensor`` (the catalog variable name) and nothing else, while the ``SENSOR_*``
    entry carries the identity (resolved from the SensorID registry + cruise overrides),
    ``sensor_role``, ``sensor_channel``, and — for a frequency sensor — its drift Slope/Offset.
    Role and channel live on the entry, not the variable, so a sensor with no stored variable
    (transmissometer, pH) still records both; that is what lets :func:`build_profiles` aggregate
    the catalog from the per-cast files without re-parsing the header. Must run after
    :func:`_normalise` so ``sensor=`` lands on the final variable names. A no-op for a cast with
    no ``<Sensors>`` block.
    """
    records = parse_sensor_channels(ds)
    if not records:
        return ds
    ds = ds.copy()
    registry = SensorRegistry.load()
    catalog: dict[str, dict[str, str]] = {}
    serial_to_names: dict[str, set[str]] = {}
    for rec in records:
        role, serial = rec["role"], rec["serial"]
        if not role or not serial:  # a Free/unused or serial-less slot
            continue
        canon = overrides.canonical_serial(serial)
        name = catalog_var_name(role, canon)
        is_freq = role_base(role) in FREQUENCY_ROLES
        if name not in catalog:
            attrs = resolve_sensor(
                sensor_id=rec["sensor_id"],
                serial=serial,
                role=role,
                calibration_date=rec["calibration_date"],
                element=rec["element"],
                registry=registry,
                overrides=overrides,
            )
            attrs["sensor_role"] = role
            attrs["sensor_channel"] = int(rec["channel"])
            if is_freq:
                attrs["sensor_calibration_slope"] = rec["slope"]
                attrs["sensor_calibration_offset"] = rec["offset"]
            # The whole <sensor> config block, verbatim, for every sensor (voltage sensors
            # carry coefficients too, so this is ungated by is_freq unlike the drift knobs):
            # the raw→physical calibration is then reconstructable from the compiled file
            # alone, not only from the stage-1 raw_metadata.
            if rec.get("raw_block"):
                attrs["sensor_config_xml"] = rec["raw_block"]
            catalog[name] = attrs
            serial_to_names.setdefault(canon, set()).add(name)
        var = _sensor_variable(role, ds)
        if var is not None and var in ds:
            ds[var].attrs["sensor"] = name
            # This variable maps to a sensor in the <Sensors> block, which is the evidence
            # that its values were converted from instrument units (datcnv did it upstream;
            # table 3 describes the procedure, not who ran it).  Co-located with the link so
            # the claim and its evidence cannot drift, and no channel needs a hardcoded name.
            add_processing_level(ds[var].attrs, PL_CONVERTED)
        elif var is not None:
            # A role ctdcast knows how to store, whose variable is absent: the reader dropped
            # a channel it could have kept.  (A role with no stored variable at all — e.g. a
            # transmissometer — returns None above and is silent by design.)
            warnings.warn(
                f"sensor role {role!r} maps to variable {var!r}, which is not in the cast "
                "— the reader dropped a channel it can store.",
                stacklevel=2,
            )
    # Cross-link entries that resolve to one physical serial (e.g. an FLNTU as fluorometer +
    # turbidity).  Fires only when both channels report the same canonical serial: a device
    # recorded under two spellings needs a config ``sensors.aliases`` entry to be seen as one.
    for names in serial_to_names.values():
        if len(names) > 1:
            for name in names:
                catalog[name]["sensor_shared_with"] = " ".join(sorted(names - {name}))
    for name, attrs in catalog.items():
        ds[name] = xr.DataArray(
            np.int32(0), attrs={k: v for k, v in attrs.items() if v != ""}
        )
    return ds


class CtdBackend(Protocol):
    """Protocol for per-cast CNV-to-netCDF converters."""

    def convert_cast(
        self,
        cnv_path: Path,
        nc_path: Path,
        *,
        force: bool = False,
        cruise_info: dict | None = None,
        sensor_overrides: SensorOverrides | None = None,
    ) -> bool:
        """Convert one CNV file to netCDF.

        Parameters
        ----------
        cnv_path:
            Path to the raw SBE CNV input file.
        nc_path:
            Desired output netCDF path.
        force:
            If True, overwrite an existing nc_path.
        cruise_info:
            The config ``cruise_info:`` mapping, stamped as cruise identity on
            the output; ``None`` writes none.
        sensor_overrides:
            The config ``sensors:`` overrides, used to resolve the per-cast sensor
            catalog; ``None`` uses an empty :class:`SensorOverrides`.

        Returns
        -------
        bool
            True if the file was written; False if skipped.
        """
        ...


class _SeasenselibBackend:
    """CTD backend that delegates to the seasenselib package."""

    def __init__(self) -> None:
        """Initialise; raises ImportError if seasenselib is not installed."""
        try:
            import seasenselib as _sl
        except ImportError as exc:
            raise ImportError(
                "seasenselib backend requested but the package is not installed. "
                "Install it with: pip install seasenselib"
            ) from exc
        self._sl = _sl
        # Suppress verbose output from pycnv/seasenselib at the logger level.
        logging.getLogger("pycnv").setLevel(logging.ERROR)
        logging.getLogger("seasenselib").setLevel(logging.ERROR)

    def convert_cast(
        self,
        cnv_path: Path,
        nc_path: Path,
        *,
        force: bool = False,
        cruise_info: dict | None = None,
        sensor_overrides: SensorOverrides | None = None,
    ) -> bool:
        """Convert one CNV file using seasenselib.

        Parameters
        ----------
        cnv_path:
            Path to the raw SBE CNV input file.
        nc_path:
            Desired output netCDF path.
        force:
            If True, overwrite an existing nc_path.
        cruise_info:
            The config ``cruise_info:`` mapping, stamped as cruise identity on
            the output; ``None`` writes none.
        sensor_overrides:
            The config ``sensors:`` overrides, used to resolve the per-cast sensor
            catalog; ``None`` uses an empty :class:`SensorOverrides`.

        Returns
        -------
        bool
            True if the file was written; False if skipped (already exists).
        """
        if nc_path.exists() and not force:
            return False
        with contextlib.redirect_stdout(io.StringIO()):
            ds = self._sl.read(str(cnv_path))
        ds = _normalise(ds, cruise_info=cruise_info)
        ds = _build_cast_sensor_catalog(ds, sensor_overrides or SensorOverrides())
        # Lineage root: stage 1 has no upstream netCDF, so it names the raw CNV it read
        # (a distinct attr, not source_tracking_id, which holds a tracking_id downstream).
        ds.attrs["source_cnv"] = cnv_path.name
        # The stage and the cast identity both live in the filename, but a file copied out of
        # its directory (as caldip takes it) loses the path; record both in the file so it is
        # identifiable on its own.  cast_id is the canonical zero-padded form (e.g. "011",
        # "011b"); it carries forward unchanged because stage 2/3 copy the attributes.
        ds.attrs["processing_stage"] = 1
        _cid = cast_id_from_name(cnv_path.stem)
        if _cid is not None:
            ds.attrs["cast_id"] = format_cast_id(*_cid)
        write_nc(ds, nc_path)
        return True


_BACKENDS: dict[str, type] = {
    "seasenselib": _SeasenselibBackend,
}


def get_ctd_backend(name: str) -> CtdBackend:
    """Return a CtdBackend instance for the given backend name.

    Parameters
    ----------
    name:
        Currently only ``"seasenselib"``.

    Raises
    ------
    ValueError
        If name is not a recognised backend.
    ImportError
        If the requested backend's package is not installed.
    """
    if name not in _BACKENDS:
        known = ", ".join(f"'{k}'" for k in _BACKENDS)
        raise ValueError(f"Unknown CTD backend: {name!r}. Known backends: {known}.")
    return _BACKENDS[name]()


def stage1(
    cnv_dir: Path,
    nc_dir: Path,
    *,
    backend: str = "seasenselib",
    force: bool = False,
    cast_filter: int | list[int] | None = None,
    pattern: str = "*.cnv",
    cruise_info: dict | None = None,
    sensor_overrides: SensorOverrides | None = None,
) -> int:
    """Convert per-cast CNV files to netCDF using the specified backend.

    Parameters
    ----------
    cnv_dir:
        Directory containing raw SBE CNV files.
    nc_dir:
        The CTD stage root; stage 1 writes ``stage1/<stem>_stage1.nc`` under it
        (the stage1 directory is created if absent).
    backend:
        Backend name (currently only ``"seasenselib"``).
    force:
        Overwrite existing netCDF files.
    cast_filter:
        If given, convert only files whose stem contains the zero-padded cast number.
        Accepts a single int or a list of ints for multi-cast filtering.
    pattern:
        Filename glob pattern applied within ``cnv_dir`` (default: ``"*.cnv"``).
    cruise_info:
        The config ``cruise_info:`` mapping, stamped as cruise identity on each
        per-cast file; ``None`` writes none (the default, so bare conversions are
        unchanged).
    sensor_overrides:
        The config ``sensors:`` overrides, used to resolve the per-cast sensor
        catalog; ``None`` uses an empty :class:`SensorOverrides`.

    Returns
    -------
    int
        Number of files written (skipped files not counted).

    Raises
    ------
    ImportError
        If the chosen backend's package is not installed.
    """
    stage_dir(nc_dir, 1, create=True)  # nc_dir is the stage root; write to stage1/
    b = get_ctd_backend(backend)

    cnv_files = sorted(cnv_dir.glob(pattern))
    if cast_filter is not None:
        tags = (
            {f"{cast_filter:0{CAST_TAG_WIDTH}d}"}
            if isinstance(cast_filter, int)
            else {f"{c:0{CAST_TAG_WIDTH}d}" for c in cast_filter}
        )
        cnv_files = [p for p in cnv_files if any(t in p.stem for t in tags)]

    n = 0
    # Capture per-cast backend warnings (e.g. seasenselib's 'db' vs 'dbar' unit
    # notice) across the whole batch and print one counted summary line each,
    # instead of the same warning once per cast.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # GSW Nsquared() warns on dp=0 (stationary CTD between 1-second samples).
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
        for cnv_path in cnv_files:
            nc_path = stage_path(nc_dir, cnv_path.stem, 1)
            try:
                written = b.convert_cast(
                    cnv_path,
                    nc_path,
                    force=force,
                    cruise_info=cruise_info,
                    sensor_overrides=sensor_overrides,
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  FAILED: {cnv_path.name}  ({type(exc).__name__}: {exc})",
                    file=sys.stderr,
                )
                continue
            if written:
                print(f"  ok: {cnv_path.name} → {nc_path.name}")
                n += 1
            else:
                print(f"  skip: {nc_path.name}")
    summarise_warnings(caught)
    return n


def run(
    cnv_dir: Path,
    nc_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    **kw: object,
) -> int:
    """Run stage1 (CNV → netCDF) for explicit input and output directories.

    Called by :func:`ctdcast.processors.process` with ``stage=1`` or
    ``stage="stage1"``.

    Parameters
    ----------
    cnv_dir:
        Directory containing raw SBE CNV files.
    nc_dir:
        The CTD stage root; stage 1 writes ``stage1/<stem>_stage1.nc`` under it
        (the stage1 directory is created if absent).
    force:
        Overwrite existing NC files.
    dry_run:
        Print what would be converted without writing any files.
    cast_tags:
        If given, process only files whose stem contains one of the zero-padded
        3-digit cast numbers (e.g. ``{"042", "043"}``).
    **kw:
        Passed to :func:`stage1` (e.g. ``backend``, ``pattern``).

    Returns
    -------
    int
        Number of files written (0 for dry_run).
    """
    pattern: str = kw.get("pattern", "*.cnv")  # type: ignore[assignment]
    cnv_files = sorted(cnv_dir.glob(pattern))
    if cast_tags is not None:
        cnv_files = [p for p in cnv_files if any(t in p.stem for t in cast_tags)]

    if dry_run:
        print(f"[dry-run] stage 1: {cnv_dir} → {nc_dir}  ({len(cnv_files)} file(s))")
        for p in cnv_files:
            print(f"  [dry-run] would convert: {p.name}")
        return 0

    cast_filter: list[int] | None = (
        [int(t) for t in sorted(cast_tags)] if cast_tags is not None else None
    )
    n = stage1(cnv_dir, nc_dir, force=force, cast_filter=cast_filter, **kw)
    print(f"stage 1: {n} file(s) written.")
    return n
