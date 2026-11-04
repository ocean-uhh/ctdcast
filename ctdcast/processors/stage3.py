"""Stage 3 — QC, calibration, and derived-variable orchestrator.

Stage3 is iterative: re-run it as calibration improves.  Each run applies the
per-sensor conductivity slope and offset and the processing steps configured for the
cruise (``data_processing:``), re-derives salinity, derives SBE 43 oxygen from the
voltage where a cast carries it, and then runs gross-range and spike QC on the
corrected values.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import xarray as xr

from ctdcast.analysis.derive import derive_salinity
from ctdcast.config.preferred_sensors import (
    GROUPS,
    SensorGroup,
    has_choice,
    has_use,
    index_of,
    preferred_sensor_names,
    resolve_preferred,
)
from ctdcast.identity import format_cast_id
from ctdcast.processors import qc
from ctdcast.processors.corrections import (
    derive_oxygen,
    flag_missing,
    resolve_slope_offset,
)
from ctdcast.processors.history import (
    PL_CALIBRATED,
    add_processing_level,
    append_history,
)
from ctdcast.processors.products import make_product
from ctdcast.processors.sensor_catalog import read_cast_sensor_catalog
from ctdcast.processors.stage_layout import (
    group_by_cast,
    is_up_to_date,
    matches_tags,
    parse_stage,
    stage_path,
)
from ctdcast.processors.steps import (
    STEPS,
    StepContext,
    iter_steps,
    validate_data_processing,
)
from ctdcast.writers.netcdf import write as _write_nc


def stage3(
    ds: xr.Dataset,
    cruise_cfg: dict | None = None,
    *,
    cast_number: int | None = None,
    cast_label: str = "?",
    context: StepContext | None = None,
) -> xr.Dataset:
    """Apply the configured processing steps, derived variables and QC to a per-cast Dataset.

    Applies, in order:

    1. The per-sensor conductivity slope and offset (``data_processing.slope_offset``), as
       Sea-Bird applies them when it converts the raw counts.
    2. ``data_processing.steps``, in the order listed: ``wildedit``
       and ``loopedit`` (:mod:`ctdcast.processors.editing`), ``filter`` and ``window_filter``
       (:mod:`ctdcast.processors.filtering`), ``alignctd`` and ``celltm``
       (:func:`ctdcast.processors.corrections.apply_corrections`), from
       :data:`ctdcast.processors.steps.STEPS`.  A step ctdcast does not apply yet is skipped
       (``run`` refuses it unless ``data_processing.allow_unapplied``), with a warning and a
       ``history`` note.  The order they ran in is written to the ``data_processing_steps``
       attribute.
    3. Re-derives practical salinity whenever a step changed conductivity, temperature or
       pressure.
    4. Derives ``ctd_oxygen`` from the SBE 43 voltage on a cast that carries ``oxygen_raw_<N>``
       and no converted oxygen (:func:`ctdcast.processors.corrections.derive_oxygen`), with the
       window in ``data_processing.oxygen``.
    5. Two-tier gross-range QC and the QARTOD spike test, on the corrected values, using the
       package defaults merged with ``qc.gross_range`` / ``qc.spike``.

    Parameters
    ----------
    ds : xarray.Dataset
        Per-cast Dataset (dim=time), already through stage1 and stage2.
    cruise_cfg : dict or None
        The settings from :func:`ctdcast.config.layout.processing_view`: ``data_processing``
        and ``qc`` are read here.
    cast_number : int or None
        The cast's number, for per-cast-range values.
    cast_label : str
        How the cast is named in warnings (e.g. ``"011"``).
    context : StepContext, optional
        Filled in as the steps run (Wild Edit's marks, Loop Edit's scans), for the products
        made from this cast in the same run.

    Returns
    -------
    xarray.Dataset
        New Dataset; input is not mutated.
    """
    cfg = cruise_cfg or {}
    dp = cfg.get("data_processing") or {}

    # Step 1: per-sensor slope and offset, before anything else (Sea-Bird applies them at datcnv).
    ds, calibrated = _apply_slope_offset(ds, dp.get("slope_offset"), cast_number)

    # Step 2: the listed steps, in order (validated by run(), before any cast).
    ctx = context if context is not None else StepContext()
    ctx.cast_number, ctx.cast_label = cast_number, cast_label
    ctx.changed.update(calibrated)
    if calibrated:
        ctx.applied.append("slope_offset")
    for name, params in iter_steps(dp):
        step = STEPS[name]
        if step.apply is None:
            # Recorded where it falls in the order, so history reads as the steps ran.
            ctx.applied.append(f"{name} (not applied)")
            append_history(
                ds.attrs, f"{name}: not yet applied by ctdcast, skipped", stage="stage3"
            )
            continue
        ds = step.apply(ds, params, ctx)
        ctx.applied.append(name)
    skipped = [a.split(" ")[0] for a in ctx.applied if a.endswith("(not applied)")]
    if skipped:
        warnings.warn(
            "data_processing step(s) not yet applied by ctdcast, skipped: "
            + ", ".join(dict.fromkeys(skipped)),
            stacklevel=2,
        )
    changed, edge_masks = ctx.changed, ctx.edge_masks

    # Step 3: re-derive salinity whenever conductivity, temperature or pressure changed.
    if any(
        v.startswith(("conductivity", "ctd_temperature")) or v == "pressure"
        for v in changed
    ):
        ds = derive_salinity(ds)
        for var, mask in edge_masks.items():
            if var.startswith("conductivity"):
                line = var[-1]
                for sal in (f"ctd_salinity_{line}", "ctd_salinity"):
                    if sal in ds:
                        flag_missing(ds, sal, mask)
                        break
        if calibrated:
            # Salinity now embodies the calibration, but keeps no conversion value: it was
            # computed, never instrument data.
            for _sal in ("ctd_salinity", "ctd_salinity_1", "ctd_salinity_2"):
                if _sal in ds:
                    add_processing_level(ds[_sal].attrs, PL_CALIBRATED)
        append_history(
            ds.attrs,
            "salinity re-derived from "
            + ("calibrated and corrected" if calibrated else "corrected")
            + " conductivity",
            stage="stage3",
        )

    # Step 4: oxygen from the SBE 43 voltage (hex casts; a CNV's own oxygen is left alone).
    ds, _oxygen = derive_oxygen(ds, dp, cast_label=cast_label, marked=ctx.marked)
    if ctx.applied:
        # The order the steps ran in, for the file and for the cast page's corrections table.
        ds.attrs["data_processing_steps"] = "; ".join(ctx.applied)

    # Step 5: gross-range + spike QC, judging the corrected values.
    ds = qc.apply_gross_range(ds, (cfg.get("qc") or {}).get("gross_range") or None)
    return qc.apply_spike_test(ds, (cfg.get("qc") or {}).get("spike") or None)


def product_path(root: Path, stem: str, name: str) -> Path:
    """Return where a cast's product is written: ``<root>/products/<name>/<stem>_<name>.nc``.

    Parameters
    ----------
    root : pathlib.Path
        The CTD stage root (``ctd_root``).
    stem : str
        The cast's file stem (``MIXSED2_050``).
    name : str
        The product's name.

    Returns
    -------
    pathlib.Path
        The product file's path.
    """
    return root / "products" / name / f"{stem}_{name}.nc"


def _make_products(
    ds: xr.Dataset,
    products: list[dict],
    cast_id: tuple,
    marked: dict | None = None,
) -> list[tuple[dict, xr.Dataset | None]]:
    """Make each configured product of one cast in memory; a failure names the product only."""
    label = format_cast_id(*cast_id)
    made: list[tuple[dict, xr.Dataset | None]] = []
    for product in products:
        try:
            out = make_product(
                ds, product, cast_number=cast_id[0], cast_label=label, marked=marked
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED product {product['name']} of cast {label}  "
                f"({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
            out = None
        made.append((product, out))
    return made


def _stamp_product_divergence(
    ds: xr.Dataset, made: list[tuple[dict, xr.Dataset | None]]
) -> None:
    """Record on the stage-3 file each product's Bin Average that kept part of a flagged scan.

    The cast page reads it (the products themselves are separate files), so the divergence from
    seabirdscientific is shown where the cast's processing is.
    """
    lines = [
        f"{product['name']}: {out.attrs['bin_average_partly_flagged']}"
        for product, out in made
        if out is not None and int(out.attrs.get("bin_average_partly_flagged_scans", 0))
    ]
    if lines:
        ds.attrs["products_bin_average_partly_flagged"] = " | ".join(lines)


def _write_products(
    made: list[tuple[dict, xr.Dataset | None]], root: Path, stem: str
) -> int:
    """Write the products made by :func:`_make_products`; return how many failed (made or written)."""
    failed = 0
    for product, out in made:
        if out is None:
            failed += 1
            continue
        path = product_path(root, stem, product["name"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_nc(out, path)
            print(f"  ok: {path.parent.name}/{path.name}")
        except Exception as exc:  # noqa: BLE001
            # One product failing to write names that product only; the stage-3 file and the
            # other products stand.  A file from an earlier run may still be there.
            print(
                f"  FAILED writing product {product['name']}: {path.name}  "
                f"({type(exc).__name__}: {exc}); any older {path.name} is stale",
                file=sys.stderr,
            )
            failed += 1
    return failed


def _apply_slope_offset(
    ds: xr.Dataset, block: dict | None, cast_number: int | None
) -> tuple[xr.Dataset, list[str]]:
    """Apply ``C' = slope * C + offset`` to each conductivity sensor configured for this cast.

    Returns the new dataset (the input is not mutated) and the variables changed.  Each changed
    variable records its slope, offset and the config entry they came from.
    """
    import numpy as np

    done: list[str] = []
    for var in ("conductivity_1", "conductivity_2"):
        if var not in ds:
            continue
        hit = resolve_slope_offset(block, var, cast_number)
        if hit is None:
            continue
        slope, offset, source = hit
        if not done:
            ds = ds.copy()
        values = ds[var].values.astype(np.float64) * slope + offset
        attrs = dict(ds[var].attrs)
        attrs["calibration_slope"] = slope
        attrs["calibration_offset"] = offset
        attrs["calibration_config"] = source
        attrs["calibration_note"] = (
            f"conductivity = {slope:.8g} * conductivity + {offset:g}"
        )
        add_processing_level(attrs, PL_CALIBRATED)
        ds[var] = (ds[var].dims, values.astype(ds[var].dtype, copy=False), attrs)
        append_history(
            ds.attrs,
            f"slope_offset: {var} slope={slope:.8g} offset={offset:g} ({source})",
            stage="stage3",
        )
        done.append(var)
    return ds, done


def _preferred_use(
    group: SensorGroup, records: list[dict], cruise_cfg: dict, cast_number: int
) -> str | None:
    """Return the use (``primary`` / ``secondary``) that applies to this cast, or None.

    The shared gate for both the attribute stamp and the composite build, so the two cannot
    diverge.  Returns None when the group is undeclared for this cast, or when the cast has
    no genuine primary-vs-secondary choice (single-sensor for this group — its one sensor is
    already the plain composite).  Raises only when an **explicit range** names the channel a
    single-sensor cast lacks.

    Raises
    ------
    ValueError
        On a malformed declaration / out-of-set value / conflicting overlap (via
        :func:`resolve_preferred`), or an explicit range naming a channel the cast lacks.
    """
    use, source = resolve_preferred(group, cruise_cfg, cast_number)
    if use is None:
        return None
    if not has_choice(group, records):
        if source == "range" and not has_use(group, records, use):
            raise ValueError(
                f"{group.config_key}: cast {cast_number} is declared {use!r} by an "
                f"explicit range, but it has no {use} sensor for "
                f"{', '.join(group.preferred_roles)} (a single-sensor cast)."
            )
        return None
    return use


def _stamp_preferred_sensors(
    ds: xr.Dataset, cruise_cfg: dict | None, cast_number: int
) -> None:
    """Stamp the per-cast preferred-sensor choice onto *ds* in place (stage 3 only).

    For each sensor group with a genuine choice on this cast, record both the choice word
    (``preferred_pair`` / ``preferred_oxygen``) and the resolved physical sensors as
    ``sensor_<role>_preferred`` — the ``SENSOR_*`` catalog variable names.  Holding the
    catalog names (rather than bare serials) lets a consumer verify, at read time, that the
    named channel still carries the expected serial.  Groups with no choice (single-sensor)
    or no declaration leave no attribute — never the string ``"undeclared"``.

    Parameters
    ----------
    ds:
        The stage-3 dataset, carrying the ``SENSOR_*`` catalog stage 1 built; mutated in
        place.
    cruise_cfg:
        The settings from :func:`ctdcast.config.layout.processing_view` (``cruise_cfg[group.config_key]`` is the nested
        declaration, or absent).
    cast_number:
        The cast's integer number; a lettered cast resolves by its number.

    Raises
    ------
    ValueError
        On a declaration that is not a mapping, a range missing its ``casts`` key, a config
        value outside the closed set, conflicting overlapping ranges, or an explicit range
        naming a channel the cast lacks.
    """
    cfg = cruise_cfg or {}
    records = read_cast_sensor_catalog(ds)
    for group in GROUPS:
        use = _preferred_use(group, records, cfg, cast_number)
        if use is None:
            continue
        # Names come from this cast's own catalog records, so each is a SENSOR_* variable
        # present in ds by construction — no re-check needed here; the read-time check is
        # the consumer's (a stamped name whose channel serial later disagrees = corruption).
        ds.attrs[group.config_key] = use
        for role, catalog_name in preferred_sensor_names(group, records, use).items():
            ds.attrs[f"sensor_{role}_preferred"] = catalog_name


def _build_preferred_composites(
    ds: xr.Dataset, cruise_cfg: dict | None, cast_number: int
) -> None:
    """Build the plain composite variables from each group's preferred channel, in place.

    For a cast with a genuine choice, copies the preferred indexed channel to the plain
    (unsuffixed) name for every group member — ``ctd_temperature_<idx>`` → ``ctd_temperature``,
    and likewise ``ctd_salinity``, ``conductivity``, ``ctd_oxygen`` — carrying the channel's
    ``{var}_qc`` companion so QC propagates.  The composite is a **per-cast selection, never a
    blend**; an undeclared dual cast gets no composite (so downstream it is absent, never a
    silent ``_1`` fallback).  A single-sensor cast has no choice and is left untouched: its
    T/S/O already carry the plain name (stage-1 promotion), while conductivity keeps
    ``conductivity_1`` (stage 1 does not promote it), so such a cast has no plain
    ``conductivity``.

    Parameters
    ----------
    ds:
        The stage-3 dataset; mutated in place.
    cruise_cfg:
        The settings from :func:`ctdcast.config.layout.processing_view`.
    cast_number:
        The cast's integer number.
    """
    cfg = cruise_cfg or {}
    records = read_cast_sensor_catalog(ds)
    for group in GROUPS:
        use = _preferred_use(group, records, cfg, cast_number)
        if use is None:
            continue
        idx = index_of(use)
        for member in group.members:
            src = f"{member}_{idx}"
            if src not in ds:
                continue
            da = ds[src]
            # Carry the source channel's attrs (units, standard_name, calibration provenance,
            # processing_level) so the composite is self-describing before the writer runs.
            # But a composite is a per-cast *selection* of one channel, not a renamed source
            # column, so drop the source-name attrs: `original_name` (and the pre-0.4.0
            # `cnv_original_name` / `source_variable`) are the rename-table keys
            # (readers.metadata.source_to_canonical) and would collide with the indexed
            # channel's own entry, mislabeling which CNV column became which variable. Drop
            # long_name too, so the writer sets the composite's own ("… (preferred pair)"),
            # and add the selection provenance.
            _drop = {
                "long_name",
                "original_name",
                "cnv_original_name",
                "source_variable",
            }
            attrs = {k: v for k, v in da.attrs.items() if k not in _drop}
            attrs["comment"] = (
                f"preferred {use} channel; copied from {src} per {group.config_key}"
            )
            ds[member] = xr.DataArray(da.values, dims=da.dims, attrs=attrs)
            qc_src = f"{src}_qc"
            if qc_src in ds:
                # Drop the source's long_name ("Quality flag for conductivity_1") so the
                # writer sets the composite's ("Quality flag for conductivity").
                qc_attrs = {
                    k: v for k, v in ds[qc_src].attrs.items() if k != "long_name"
                }
                ds[f"{member}_qc"] = xr.DataArray(
                    ds[qc_src].values, dims=ds[qc_src].dims, attrs=qc_attrs
                )


def run(
    root: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    cast_tags: set[str] | None = None,
    cruise_info: dict | None = None,
    **kw: object,
) -> int:
    """Apply stage 3 (QC + calibration) across the casts under *root*.

    Reads each cast's **stage-2** file, applies :func:`stage3`, and writes a new
    ``stage3/<stem>_stage3.nc`` — never in place.  Reads are strict: a cast with
    no stage-2 file is skipped with a warning (its soak/deck flags were never
    applied, so QC'ing it would manufacture a product whose filename lies).
    Called by :func:`ctdcast.processors.process` with ``stage=3``.

    Parameters
    ----------
    root:
        The CTD stage root (``ctd_root``).  Stage files live under
        ``root/stage2/`` … ``root/stage3/``.
    force:
        Rewrite the stage-3 file even when it already exists.  Without ``force``,
        a cast whose ``stage3/<stem>_stage3.nc`` exists is skipped.
    dry_run:
        Print what would be processed without writing any output.
    cast_tags:
        If given, process only casts selected by these zero-padded tags
        (e.g. ``{"042"}``), matched on the parsed cast identity.
    cruise_info:
        The config ``cruise_info:`` block.  When it declares ``data_mode: D``,
        each stage-3 file is stamped ``data_mode = "D"``; if no calibration was
        actually applied the delayed-mode claim is unsupported, so the cast is
        named in a warning and the gap recorded in ``history``.
    **kw:
        Passed to :func:`stage3` (e.g. ``cruise_cfg``).

    Returns
    -------
    int
        Number of stage-3 files written (0 for dry_run).

    Raises
    ------
    FileNotFoundError
        If *root* does not exist or is not a directory.
    """
    if not root.is_dir():
        raise FileNotFoundError(
            f"stage root not found: {root}. Stage 1 creates it from the raw input, so run "
            "--stage 1 first and check that the config's data: block sets cnv_dir or hex_dir."
        )

    cruise_cfg: dict | None = kw.get("cruise_cfg")  # type: ignore[assignment]
    # A declared ``D`` is a human claim about a finished cruise (OceanSITES table 4), not
    # something stage 3 can infer from having applied a slope; stamp it per cast, and warn
    # (naming the cast) when nothing in the config backs the claim.
    declare_delayed = str((cruise_info or {}).get("data_mode", "")).upper() == "D"

    # A malformed correction block fails once, here, not as one error per cast.
    validate_data_processing((cruise_cfg or {}).get("data_processing"))
    products = ((cruise_cfg or {}).get("data_processing") or {}).get("products") or []
    groups = group_by_cast(root)
    n = n_skipped = n_failed = n_products_failed = 0
    for cast_id in sorted(groups):
        if cast_tags is not None and not matches_tags(cast_id, cast_tags):
            continue
        input_path = groups[cast_id].get(2)  # strict: stage 3 reads stage 2
        if input_path is None:
            num, suffix = cast_id
            print(
                f"  skip (no stage 2): cast {format_cast_id(num, suffix)}",
                file=sys.stderr,
            )
            n_skipped += 1
            continue
        parsed = parse_stage(input_path)
        stem = parsed[0] if parsed else input_path.stem
        target = stage_path(root, stem, 3)
        if not force and is_up_to_date(target, [input_path]):
            print(f"  skip (up to date): {target.name}")
            n_skipped += 1
            continue
        if dry_run:
            print(
                f"  [dry-run] stage 3 would process: {input_path.name} -> {target.name}"
            )
            continue
        ds = None
        try:
            ds = xr.open_dataset(input_path, engine="netcdf4").load()
            steps_ctx = StepContext()
            ds_out = stage3(
                ds,
                cruise_cfg=cruise_cfg,
                cast_number=cast_id[0],
                cast_label=format_cast_id(*cast_id),
                context=steps_ctx,
            )
            # Lineage: record the stage-2 file's id before the writer stamps ds_out's own
            # fresh tracking_id (empty on a legacy stage-2 file that predates the id).
            _src_id = ds.attrs.get("tracking_id", "")
            if _src_id:
                ds_out.attrs["source_tracking_id"] = _src_id
            ds_out.attrs["processing_stage"] = 3
            _stamp_preferred_sensors(ds_out, cruise_cfg, cast_id[0])
            _build_preferred_composites(ds_out, cruise_cfg, cast_id[0])
            if declare_delayed:
                ds_out.attrs["data_mode"] = "D"
                # The claim is backed only if a calibration was actually applied — detected by
                # the PL_CALIBRATED processing_level stage3 stamps when it calibrates, not by
                # the presence of a config key that may carry no usable slope.
                calibrated = any(
                    PL_CALIBRATED in str(ds_out[v].attrs.get("processing_level", ""))
                    for v in ds_out.data_vars
                )
                if not calibrated:
                    num, suffix = cast_id
                    name = format_cast_id(num, suffix)
                    warnings.warn(
                        f"cast {name}: data_mode 'D' declared but no calibration was "
                        "applied; the delayed-mode claim is unsupported by anything in "
                        "the file.",
                        stacklevel=2,
                    )
                    append_history(
                        ds_out.attrs,
                        "data_mode=D declared but no calibration applied; "
                        "delayed-mode claim unsupported",
                        stage="stage3",
                    )
            ds.close()
            ds = None  # prevent double-close in finally; file released before write
            made = _make_products(ds_out, products, cast_id, steps_ctx.marked)
            _stamp_product_divergence(ds_out, made)
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_nc(ds_out, target)
            print(f"  ok: {target.name}")
            n += 1
            n_products_failed += _write_products(made, root, stem)
        except Exception as exc:  # noqa: BLE001
            print(
                f"  FAILED: {input_path.name}  ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
            n_failed += 1
        finally:
            if ds is not None:
                ds.close()
    if not dry_run:
        parts = [f"{n} written", f"{n_skipped} skipped"]
        if n_failed:
            parts.append(f"{n_failed} FAILED")
        if n_products_failed:
            parts.append(f"{n_products_failed} product file(s) FAILED")
        print(f"stage 3: {', '.join(parts)}.")
    return n
