"""Compare a ctdcast stage file with a Sea-Bird CNV made from the same ``.hex``.

The check behind every Sea-Bird step ctdcast applies: run the step on the ``.hex`` path, read the
CNV the cruise made with the same step, and see whether the two agree scan by scan.  Both come
from the same raw scans, so at the native rate scan *k* in one is scan *k* in the other; the CNV is
read through stage 1's own renaming, so a variable has the same name and units on both sides.

What Sea-Bird marks as bad is kept apart from the numbers.  Wild Edit replaces a value it rejects
with the file's ``bad_flag`` (``-9.990e-29``), and Loop Edit sets the ``flag`` column for a whole
scan; both count as flagged in the CNV.  On the ctdcast side a value is flagged when its
``{var}_qc`` is QARTOD 3 (suspect) or 4 (fail).  Differences are taken only where neither side
flags the scan, and the flagged scans are compared as flags.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import xarray as xr

#: QARTOD flags that count as flagged on the ctdcast side.
FLAGGED_QC = (3, 4)


@dataclass(frozen=True)
class VariableComparison:
    """One variable's agreement between a ctdcast stage file and a CNV.

    Attributes
    ----------
    name : str
        Variable name, the same on both sides.
    units : str
        Units of the differences (the ctdcast variable's ``units``).
    n_compared : int
        Scans where neither side flags the value and both are finite.
    median, rms, max_abs : float
        Of ctdcast minus CNV over the compared scans; NaN when none.
    flagged_ref : int
        Scans the CNV flags (bad-flag value or Loop Edit).
    flagged_ours : int
        Scans the ctdcast ``{name}_qc`` flags (3 or 4).
    flagged_both : int
        Scans flagged on both sides.
    """

    name: str
    units: str
    n_compared: int
    median: float
    rms: float
    max_abs: float
    flagged_ref: int
    flagged_ours: int
    flagged_both: int


def _is_bad_flag(values: np.ndarray) -> np.ndarray:
    """Return where *values* hold Sea-Bird's bad flag, after any unit scaling.

    The bad flag is ``-9.990e-29``; stage 1's unit conversion may scale it (S/m to mS/cm makes it
    ``-9.990e-28``), so any negative value smaller in magnitude than ``1e-20`` counts.
    """
    v = np.asarray(values, dtype=float)
    return (v < 0) & (np.abs(v) < 1e-20)


def read_reference(cnv_path: Path | str) -> xr.Dataset:
    """Read a Sea-Bird CNV as stage 1 would name it, with Sea-Bird's flags kept apart.

    Parameters
    ----------
    cnv_path : path-like
        The CNV.

    Returns
    -------
    xarray.Dataset
        The CNV's variables under ctdcast's names and units.  Values Sea-Bird flagged are NaN, and
        each variable that had any carries a boolean ``{var}_sbe_flagged``; a scan Loop Edit
        marked is flagged in every variable.  The two kinds are also kept apart:
        ``{var}_sbe_value_flagged`` for values set to the bad flag (Wild Edit) and
        ``sbe_scan_flagged`` for scans Loop Edit marked.
    """
    from ctdcast.readers.cnv import read

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = read(Path(cnv_path))
    n = ds.sizes["time"]
    scan_flag = np.zeros(n, dtype=bool)
    if "sbe_flag" in ds:
        f = ds["sbe_flag"].values.astype(float)
        scan_flag = np.isfinite(f) & (f != 0)
    out = ds.copy()
    for name, da in ds.data_vars.items():
        if da.dims != ("time",) or name == "sbe_flag" or da.dtype.kind not in "fi":
            continue
        value_bad = _is_bad_flag(da.values)
        bad = value_bad | scan_flag
        if bad.any():
            out[name] = da.where(~bad)
            out[f"{name}_sbe_flagged"] = ("time", bad)
        if value_bad.any():
            out[f"{name}_sbe_value_flagged"] = ("time", value_bad)
    if scan_flag.any():
        out["sbe_scan_flagged"] = ("time", scan_flag)
    return out


@dataclass(frozen=True)
class FlagAgreement:
    """Where ctdcast and a CNV mark the same variable's values.

    Attributes
    ----------
    name : str
        Variable name.
    ref : int
        Values the CNV marks.
    ours : int
        Values ctdcast marks.
    both : int
        Values both mark.
    """

    name: str
    ref: int
    ours: int
    both: int


def flag_agreement(ours: dict[str, np.ndarray], ref: xr.Dataset) -> list[FlagAgreement]:
    """Compare ctdcast's marks for one step with the values the CNV set to its bad flag.

    Sea-Bird's Wild Edit replaces each value it rejects with the file's bad flag, so a CNV's
    per-value bad flags are Wild Edit's marks; Loop Edit's whole-scan marks are kept apart, in
    ``sbe_scan_flagged``, and do not count here.

    Parameters
    ----------
    ours : dict of str to numpy.ndarray
        ``{variable: mask}`` from one ctdcast step (e.g. :func:`ctdcast.processors.editing.apply_wild_edit`).
    ref : xarray.Dataset
        The CNV from :func:`read_reference`.

    Returns
    -------
    list of FlagAgreement
        One per variable in *ours* that the CNV also carries.
    """
    rows = []
    for name, mask in ours.items():
        if name not in ref:
            continue
        r = (
            ref[f"{name}_sbe_value_flagged"].values
            if f"{name}_sbe_value_flagged" in ref
            else np.zeros(ref.sizes["time"], dtype=bool)
        )
        m = np.asarray(mask, dtype=bool)
        if m.size != r.size:
            raise ValueError(
                f"{name}: scan counts differ (ctdcast {m.size}, CNV {r.size})"
            )
        rows.append(FlagAgreement(name, int(r.sum()), int(m.sum()), int((r & m).sum())))
    return rows


def _ours_flagged(ds: xr.Dataset, name: str, n: int) -> np.ndarray:
    qc = f"{name}_qc"
    if qc not in ds:
        return np.zeros(n, dtype=bool)
    return np.isin(ds[qc].values[:n], FLAGGED_QC)


def compare(
    ours: xr.Dataset, ref: xr.Dataset, variables: list[str] | None = None
) -> list[VariableComparison]:
    """Compare each variable present in both datasets, scan by scan.

    Parameters
    ----------
    ours : xarray.Dataset
        A ctdcast stage file read from the ``.hex``.
    ref : xarray.Dataset
        The CNV from :func:`read_reference`.
    variables : list of str, optional
        Which variables; default every one-dimensional numeric variable both carry, other than
        flags and Sea-Bird's own derived quantities (``sbe_*``).

    Returns
    -------
    list of VariableComparison
        In the order of *variables*, or of *ours* by default.

    Raises
    ------
    ValueError
        When the two have different scan counts: the comparison is scan by scan, and a difference
        in length means one of them dropped or averaged scans.
    """
    n = ours.sizes["time"]
    if ref.sizes["time"] != n:
        raise ValueError(
            f"scan counts differ (ctdcast {n}, CNV {ref.sizes['time']}): "
            "compare files at the same rate, before any bin average"
        )
    if variables is None:
        variables = [
            v
            for v, da in ours.data_vars.items()
            if v in ref
            and da.dims == ("time",)
            and da.dtype.kind == "f"
            and not v.endswith("_qc")
            and not v.startswith("sbe_")
            and not v.endswith("_flagged")
        ]
    rows = []
    for name in variables:
        a = ours[name].values.astype(float)
        b = ref[name].values.astype(float)
        f_ref = (
            ref[f"{name}_sbe_flagged"].values
            if f"{name}_sbe_flagged" in ref
            else np.zeros(n, dtype=bool)
        )
        f_ours = _ours_flagged(ours, name, n)
        ok = ~f_ref & ~f_ours & np.isfinite(a) & np.isfinite(b)
        d = a[ok] - b[ok]
        if d.size:
            med, rms, mx = (
                float(np.median(d)),
                float(np.sqrt(np.mean(d**2))),
                float(np.max(np.abs(d))),
            )
        else:
            med = rms = mx = float("nan")
        rows.append(
            VariableComparison(
                name=name,
                units=str(ours[name].attrs.get("units", "")),
                n_compared=int(ok.sum()),
                median=med,
                rms=rms,
                max_abs=mx,
                flagged_ref=int(f_ref.sum()),
                flagged_ours=int(f_ours.sum()),
                flagged_both=int((f_ref & f_ours).sum()),
            )
        )
    return rows


def comparison_table(rows: list[VariableComparison]) -> str:
    """Return *rows* as a plain-text table, one variable per line.

    Parameters
    ----------
    rows : list of VariableComparison
        From :func:`compare`.

    Returns
    -------
    str
        Columns: variable, units, scans compared, median, rms, max |d|, flagged (CNV / ctdcast /
        both).
    """
    head = f"{'variable':22s} {'units':15s} {'n':>7s} {'median':>10s} {'rms':>10s} {'max|d|':>10s}  flagged CNV/ours/both"
    lines = [head]
    for r in rows:
        lines.append(
            f"{r.name:22s} {r.units:15s} {r.n_compared:7d} {r.median:+10.5f} {r.rms:10.5f} "
            f"{r.max_abs:10.4f}  {r.flagged_ref}/{r.flagged_ours}/{r.flagged_both}"
        )
    return "\n".join(lines)
