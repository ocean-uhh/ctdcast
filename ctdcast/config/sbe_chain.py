"""Translate a CNV header's SBE Data Processing chain into ctdcast ``data_processing`` steps.

A Sea-Bird CNV records every module that ran on it (``# wildedit_date``, ``# filter_low_pass_tc_A``,
…).  :func:`chain_steps` turns that record into the list of steps ctdcast's stage 3 understands, in
the order the modules ran, with the parameters each used and SBE channel names replaced by
ctdcast's variable names.  It is how a cruise's own processing is reproduced from the ``.hex``: read
the CNV the cruise made, write the equivalent ``data_processing:`` block, run it, compare.

Each step is a one-key mapping ``{module: parameters}``; a module that ran twice gives two steps.
Sea-Bird's Filter, which applies two time constants (A and B) in one run, becomes two ``filter``
steps.  Modules that are not steps in ctdcast are reported in ``skipped`` with the reason:
``datcnv`` (stage 1), ``Derive`` (ctdcast derives salinity, density and oxygen itself), ``strip``
(a product's variable list) and ``bottlesum`` (bottle files).  One CNV header shows only the branch
of processing that produced that file; a cruise's other products have their own headers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ctdcast.config.cnv_header import _canonical_var, parse_processing_chain

#: SBE modules with no ctdcast step, and why.
SKIPPED_MODULES: dict[str, str] = {
    "datcnv": "conversion to engineering units: stage 1",
    "derive": "ctdcast derives salinity, density and oxygen itself after every change",
    "strip": "a product's variable list, not a processing step",
    "bottlesum": "bottle files, not the profile",
    "rossum": "bottle files, not the profile",
    "seaplot": "plotting only",
    "asciiout": "file format only",
    "translate": "file format only",
}


def _yes(value: str) -> bool:
    return value.strip().lower().startswith("yes")


def _num(value: str) -> float | int:
    v = float(value.split()[0].rstrip(","))
    return int(v) if v.is_integer() and "." not in value.split()[0] else v


def _vars(value: str, rename_map: dict[str, str] | None) -> list[str]:
    return [_canonical_var(v, rename_map) for v in value.split()]


def _kv_tail(text: str) -> dict[str, str]:
    """Parse ``a = 1, b = 2`` (the tail SBE writes after a first ``=``) into a dict."""
    out = {}
    for part in text.split(","):
        k, sep, v = part.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def _wildedit(p: dict[str, str], rn: dict[str, str] | None) -> list[dict]:
    step: dict[str, Any] = {}
    for key, name in (("pass1_nstd", "pass1_nstd"), ("pass2_nstd", "pass2_nstd"),
                      ("pass2_mindelta", "mindelta"), ("npoint", "scans_per_block")):  # fmt: skip
        if key in p:
            step[name] = _num(p[key])
    if "excl_bad_scans" in p:
        step["exclude_flagged"] = _yes(p["excl_bad_scans"])
    if "vars" in p:
        step["variables"] = _vars(p["vars"], rn)
    return [{"wildedit": step}]


def _wfilter(p: dict[str, str], rn: dict[str, str] | None) -> list[dict]:
    """One ``window_filter`` step per distinct (type, width), in first-seen order."""
    groups: dict[tuple[str, str], list[str]] = {}
    for key, value in p.items():
        if not key.startswith("action "):
            continue
        kind, _, width = (s.strip() for s in value.partition(","))
        groups.setdefault((kind, width), []).append(
            _canonical_var(key[len("action ") :], rn)
        )
    out = []
    for (kind, width), variables in groups.items():
        step: dict[str, Any] = {"type": kind, "variables": variables}
        if width:
            step["width"] = _num(width)
        if "excl_bad_scans" in p:
            step["exclude_flagged"] = _yes(p["excl_bad_scans"])
        out.append({"window_filter": step})
    return out


def _filter(p: dict[str, str], rn: dict[str, str] | None) -> list[dict]:
    """Sea-Bird's Filter A and B as two ``filter`` steps (A first, as Sea-Bird runs them)."""
    out = []
    for ab in ("A", "B"):
        variables = p.get(f"low_pass_{ab}_vars", "").split()
        if variables and f"low_pass_tc_{ab}" in p:
            out.append(
                {
                    "filter": {
                        "time_constant": _num(p[f"low_pass_tc_{ab}"]),
                        "variables": [_canonical_var(v, rn) for v in variables],
                    }
                }
            )
    return out


def _alignctd(p: dict[str, str], rn: dict[str, str] | None) -> list[dict]:
    step = {}
    for pair in p.get("adv", "").split(","):
        bits = pair.split()
        if len(bits) >= 2:
            step[_canonical_var(bits[0], rn)] = _num(bits[1])
    return [{"alignctd": step}] if step else []


def _celltm(p: dict[str, str], _rn: dict[str, str] | None) -> list[dict]:
    """``alpha``/``tau`` are ``primary, secondary`` pairs; a single value applies to the primary."""
    alphas = [a.strip() for a in p.get("alpha", "").split(",") if a.strip()]
    taus = [t.strip() for t in p.get("tau", "").split(",") if t.strip()]
    step = {}
    for i, (a, t) in enumerate(zip(alphas, taus, strict=False)):
        step[f"conductivity_{i + 1}"] = {"alpha": _num(a), "tau": _num(t)}
    return [{"celltm": step}] if step else []


def _loopedit(p: dict[str, str], _rn: dict[str, str] | None) -> list[dict]:
    step: dict[str, Any] = {}
    for key, value in p.items():
        k = key.lower()
        if k == "minvelocity":
            step["min_velocity"] = _num(value)
        elif k.startswith("percent"):
            step["min_velocity_percent"] = value.strip()
        elif k.startswith("surfacesoak"):
            # "surfaceSoak: minDepth" = "5.0, maxDepth = 20, useDeckPress = 1"
            first, _, rest = value.partition(",")
            tail = _kv_tail(rest)
            soak: dict[str, Any] = {"min_depth": _num(first)}
            if "maxDepth" in tail:
                soak["max_depth"] = _num(tail["maxDepth"])
            if "useDeckPress" in tail:
                soak["deck_pressure"] = tail["useDeckPress"].strip() == "1"
            step["surface_soak"] = soak
        elif k == "excl_bad_scans":
            step["exclude_flagged"] = _yes(value)
    return [{"loopedit": step}]


def _binavg(p: dict[str, str], _rn: dict[str, str] | None) -> list[dict]:
    step: dict[str, Any] = {}
    if "bintype" in p:
        step["bin"] = p["bintype"].strip()
    if "binsize" in p:
        step["size"] = _num(p["binsize"])
    if "excl_bad_scans" in p:
        step["exclude_flagged"] = _yes(p["excl_bad_scans"])
    for key, name in (("min_scans_bin", "min_scans"), ("max_scans_bin", "max_scans"),
                      ("skipover", "skip_over"), ("omit", "omit")):  # fmt: skip
        if key in p:
            step[name] = _num(p[key])
    if "surface_bin" in p:
        flag, _, rest = p["surface_bin"].partition(",")
        if _yes(flag):
            tail = _kv_tail(rest)
            step["surface_bin"] = {k: _num(v) for k, v in tail.items()}
        else:
            step["surface_bin"] = None
    return [{"binavg": step}]


def _split(p: dict[str, str], _rn: dict[str, str] | None) -> list[dict]:
    step: dict[str, Any] = {}
    if "excl_bad_scans" in p:
        step["exclude_flagged"] = _yes(p["excl_bad_scans"])
    return [{"split": step}]


_TRANSLATORS = {
    "wildedit": _wildedit,
    "wfilter": _wfilter,
    "filter": _filter,
    "alignctd": _alignctd,
    "celltm": _celltm,
    "loopedit": _loopedit,
    "binavg": _binavg,
    "split": _split,
}


def chain_steps(
    header_text: str, rename_map: dict[str, str] | None = None
) -> dict[str, list]:
    """Return the ctdcast processing steps equivalent to a CNV header's SBE chain.

    Parameters
    ----------
    header_text : str
        The CNV header (everything up to ``*END*``).
    rename_map : dict of str to str, optional
        ``{sbe_column_name: variable_name}`` for this file, when known; otherwise the static
        aliases are used and an unmapped channel keeps its SBE name.

    Returns
    -------
    dict
        ``{"steps": [{module: parameters}, ...], "skipped": [{"module": ..., "reason": ...}, ...]}``
        in run order.  An SBE module ctdcast has no translation for is listed in ``skipped`` with
        the reason ``"not translated"``.
    """
    steps: list[dict] = []
    skipped: list[dict[str, str]] = []
    for step in parse_processing_chain(header_text).steps:
        name = step.module.lower()
        if name in _TRANSLATORS:
            steps += _TRANSLATORS[name](step.params, rename_map)
        else:
            skipped.append(
                {
                    "module": step.module,
                    "reason": SKIPPED_MODULES.get(name, "not translated"),
                }
            )
    return {"steps": steps, "skipped": skipped}


def chain_yaml(header_text: str, rename_map: dict[str, str] | None = None) -> str:
    """Return :func:`chain_steps` as a paste-ready ``data_processing:`` YAML block.

    Parameters
    ----------
    header_text : str
        The CNV header.
    rename_map : dict of str to str, optional
        As for :func:`chain_steps`.

    Returns
    -------
    str
        YAML with the steps under ``data_processing.steps``, the skipped modules as comments.
    """
    import yaml

    class _Dumper(yaml.SafeDumper):
        pass

    def _list(dumper: yaml.SafeDumper, data: list) -> yaml.Node:
        # A list of names on one line; the list of steps stays one step per line.
        flat = not any(isinstance(v, dict | list) for v in data)
        return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flat)

    def _dict(dumper: yaml.SafeDumper, data: dict) -> yaml.Node:
        # A small mapping of plain values ({alpha: 0.03, tau: 7.0}) reads best on one line.
        small = len(data) <= 3 and not any(
            isinstance(v, dict | list) for v in data.values()
        )
        return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=small)

    _Dumper.add_representer(list, _list)
    _Dumper.add_representer(dict, _dict)

    result = chain_steps(header_text, rename_map)
    body = yaml.dump(
        {"data_processing": {"steps": result["steps"]}},
        Dumper=_Dumper,
        sort_keys=False,
        width=100,
    )
    notes = [f"# not a step: {s['module']} ({s['reason']})" for s in result["skipped"]]
    return "\n".join([*notes, body.rstrip()]) + "\n"


def header_text_of(path: str | Path) -> str:
    """Return a CNV file's header, everything before ``*END*``.

    Parameters
    ----------
    path : str or os.PathLike
        The CNV file.

    Returns
    -------
    str
        The header lines, joined.
    """
    lines = []
    with Path(path).open(encoding="latin-1") as fh:
        for line in fh:
            if line.startswith("*END*"):
                break
            lines.append(line.rstrip("\n"))
    return "\n".join(lines)
