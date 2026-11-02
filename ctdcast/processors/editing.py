"""Stage-3 editing at the native scan rate: Sea-Bird's Wild Edit.

Wild Edit marks values that sit far from the rest of their block of scans, as SBE Data
Processing's module of the same name does: in each block of ``scans_per_block`` scans, the
values beyond ``pass1_nstd`` standard deviations of the block mean are set aside, the mean and
standard deviation are recomputed from what is left, and a value is marked when it lies beyond
``pass2_nstd`` of those *and* farther than ``mindelta`` from the mean.  The last, partial block
is judged against the last full ``scans_per_block`` scans of the cast.

Sea-Bird replaces a marked value with its bad flag; ctdcast keeps the value and sets
``{var}_qc`` to QARTOD 4 (fail), so nothing is lost and the edit is visible in the file.  The
parameters and the number of values marked are recorded on each variable and in ``history``.

The marking is :func:`seabirdscientific.processing.wild_edit`'s; ctdcast turns its bad-flag values
into ``_qc`` flags and keeps the data.

**Where it appears to differ from SBE Data Processing** (Sea-Bird's Windows program).  On a block
where a channel sits at one or two A/D levels (an SBE 43 voltage, altimeter or fluorescence near
the surface), the standard deviation left after the first pass is about zero.  With
``mindelta`` 0 the Windows program then marks every value in the block; seabirdscientific marks
only the values off the block's main level.  On OdB cast 050 every value ctdcast marked was also
marked in the cruise's CNV, which marked 5–10 times more on those channels, in whole blocks.  The
cause is inferred from the output, not from the Windows program's source.  A ``mindelta`` of a few
A/D steps on such channels avoids both.

Configuration, a step in ``data_processing.steps``::

    - wildedit:
        pass1_nstd: 2.0
        pass2_nstd: 20.0
        mindelta: 0.0
        scans_per_block: 100
        exclude_flagged: true    # leave scans an earlier Loop Edit marked out of the statistics
        variables: [pressure, ctd_temperature_1, conductivity_1]
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import xarray as xr
from seabirdscientific import processing as sbs_processing

from ctdcast.config.cnv_header import applied_sbe_corrections, header_from_raw_metadata
from ctdcast.processors.corrections import _version
from ctdcast.processors.history import append_history
from ctdcast.processors.qc import QARTOD_FAIL, _ensure_qc, _raise_flag

#: SBE Data Processing's example values (its Wild Edit dialog), used for a key the config leaves out.
WILD_EDIT_DEFAULTS: dict[str, float | int | bool] = {
    "pass1_nstd": 2.0,
    "pass2_nstd": 20.0,
    "mindelta": 0.0,
    "scans_per_block": 100,
    "exclude_flagged": True,
}

#: Variables edited when the config names none.
DEFAULT_WILD_EDIT_VARIABLES = (
    "pressure",
    "ctd_temperature_1",
    "ctd_temperature_2",
    "conductivity_1",
    "conductivity_2",
    "oxygen_raw_1",
    "oxygen_raw_2",
)


@dataclass(frozen=True)
class WildEdit:
    """Resolved Wild Edit parameters.

    Attributes
    ----------
    pass1_nstd, pass2_nstd : float
        Standard deviations for the first and second passes.
    mindelta : float
        A value closer to the block mean than this is never marked, in the variable's units.
    scans_per_block : int
        Scans per block.
    exclude_flagged : bool
        Leave scans an earlier Loop Edit marked out of the block statistics.
    variables : tuple of str
        Variables to edit.
    """

    pass1_nstd: float
    pass2_nstd: float
    mindelta: float
    scans_per_block: int
    exclude_flagged: bool
    variables: tuple[str, ...]

    def describe(self) -> str:
        """Return the parameters as one line, for attributes and ``history``."""
        return (
            f"pass1_nstd={self.pass1_nstd:g} pass2_nstd={self.pass2_nstd:g} "
            f"mindelta={self.mindelta:g} scans_per_block={self.scans_per_block} "
            f"exclude_flagged={'yes' if self.exclude_flagged else 'no'}"
        )


def resolve_wild_edit(cfg: dict | None) -> WildEdit | None:
    """Return the Wild Edit parameters from ``{"wildedit": parameters}``, or None when absent.

    Parameters
    ----------
    cfg : dict or None
        ``{"wildedit": ...}``: the step's parameters from ``data_processing.steps``.

    Returns
    -------
    WildEdit or None
        None when ``wildedit`` is absent or empty.

    Raises
    ------
    ValueError
        On an unknown key or a value of the wrong kind.
    """
    cfg = cfg or {}
    if "wildedit" not in cfg:
        return None
    block = cfg["wildedit"] or {}
    if not isinstance(block, dict):
        raise ValueError(f"wildedit: expected a mapping, got {block!r}")
    unknown = set(block) - set(WILD_EDIT_DEFAULTS) - {"variables"}
    if unknown:
        raise ValueError(f"wildedit: unknown key(s) {sorted(unknown)}")
    merged = {**WILD_EDIT_DEFAULTS, **block}
    try:
        p1, p2, md = (
            float(merged[k]) for k in ("pass1_nstd", "pass2_nstd", "mindelta")
        )
        spb = int(merged["scans_per_block"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"wildedit: {exc}") from exc
    if spb < 2 or p1 <= 0 or p2 <= 0 or md < 0:
        raise ValueError(
            "wildedit: scans_per_block must be at least 2, pass1_nstd and pass2_nstd positive, "
            "mindelta not negative"
        )
    variables = block.get("variables") or DEFAULT_WILD_EDIT_VARIABLES
    if isinstance(variables, str) or not all(isinstance(v, str) for v in variables):
        raise ValueError(
            f"wildedit.variables: expected a list of names, got {variables!r}"
        )
    return WildEdit(p1, p2, md, spb, bool(merged["exclude_flagged"]), tuple(variables))


def wild_edit_mask(
    values: np.ndarray,
    params: WildEdit,
    excluded: np.ndarray | None = None,
) -> np.ndarray:
    """Return where Wild Edit marks *values*, using :func:`seabirdscientific.processing.wild_edit`.

    Parameters
    ----------
    values : numpy.ndarray
        One variable at the native scan rate; NaN is never marked and never counted.
    params : WildEdit
        The resolved parameters.
    excluded : numpy.ndarray, optional
        Boolean, true at scans to leave out of the block statistics (an earlier Loop Edit's
        marks); used only when ``params.exclude_flagged``.

    Returns
    -------
    numpy.ndarray
        Boolean, true at the values marked.
    """
    x = np.asarray(values, dtype=float)
    flags = np.zeros_like(x)
    if excluded is not None and params.exclude_flagged:
        flags[np.asarray(excluded, dtype=bool)] = sbs_processing.FLAG_VALUE
    # seabirdscientific's last-block rule indexes from len - scans_per_block, so a cast shorter
    # than one block is judged as one block.
    k = min(params.scans_per_block, x.size)
    if k < 2:
        return np.zeros(x.size, dtype=bool)
    out = sbs_processing.wild_edit(
        x,
        flags,
        params.pass1_nstd,
        params.pass2_nstd,
        k,
        params.mindelta,
        params.exclude_flagged,
    )
    return (out == sbs_processing.FLAG_VALUE) & (x != sbs_processing.FLAG_VALUE)


def apply_wild_edit(
    ds: xr.Dataset,
    cfg: dict | None,
    *,
    excluded: np.ndarray | None = None,
    cast_label: str = "?",
) -> tuple[xr.Dataset, dict[str, np.ndarray]]:
    """Apply Wild Edit to one cast: mark outliers QARTOD 4 in each named variable's ``_qc``.

    Parameters
    ----------
    ds : xarray.Dataset
        A stage-2 dataset at its native scan rate.
    cfg : dict or None
        ``{"wildedit": ...}``: the step's parameters from ``data_processing.steps``.
    excluded : numpy.ndarray, optional
        Scans an earlier Loop Edit marked, left out of the statistics when ``exclude_flagged``.
    cast_label : str, optional
        How the cast is named in warnings.

    Returns
    -------
    tuple of (xarray.Dataset, dict)
        A new dataset (the input is not mutated) and ``{variable: mask}`` of the values marked.
        Without a ``wildedit`` entry the dataset is returned unchanged.  A cast Sea-Bird already
        wild-edited is skipped, with a warning and a ``history`` note.
    """
    params = resolve_wild_edit(cfg)
    if params is None:
        return ds, {}
    ds = ds.copy()
    header = header_from_raw_metadata(ds.attrs.get("raw_metadata")) or ""
    if "wildedit" in applied_sbe_corrections(header)["modules"]:
        message = "wildedit skipped: Sea-Bird wildedit already ran"
        warnings.warn(f"cast {cast_label}: {message}", stacklevel=2)
        append_history(ds.attrs, message, stage="stage3")
        return ds, {}
    marks: dict[str, np.ndarray] = {}
    absent = []
    for var in params.variables:
        if var not in ds.data_vars or ds[var].dims != ("time",):
            absent.append(var)
            continue
        mask = wild_edit_mask(ds[var].values, params, excluded)
        qc_name = _ensure_qc(ds, var)
        qc = ds[qc_name].values.copy()
        _raise_flag(qc, mask, QARTOD_FAIL)
        ds[qc_name] = (ds[qc_name].dims, qc, ds[qc_name].attrs)
        attrs = dict(ds[var].attrs)
        attrs["wild_edit"] = params.describe()
        attrs["wild_edit_method"] = (
            f"seabirdscientific {_version()} processing.wild_edit"
        )
        attrs["wild_edit_marked"] = int(mask.sum())
        ds[var].attrs = attrs
        marks[var] = mask
    note = f"wildedit: {params.describe()}; marked " + (
        ", ".join(f"{v} {int(m.sum())}" for v, m in marks.items()) or "nothing"
    )
    if absent:
        note += f"; not in this cast: {', '.join(absent)}"
    append_history(ds.attrs, note, stage="stage3")
    return ds, marks
