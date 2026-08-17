"""Legacy anchor aliases for report pages — a transition shim for the D3 fix.

Section ids became page anchors, so the old hand-authored ``#s-*`` anchors change
(``#s-profiles``/``#s-physics``/``#s-hydro`` all collapse onto ``#hydrography``).
The committed demo pages under ``docs/source/_static/demo/`` deep-link the old
ids, and external links (papers, issues, cruise reports) may too.  For one
release each page emits an empty ``<span id="old">`` for every old anchor whose
new section is rendered on it, so those links keep resolving.

Remove this module and the one template call that uses it once the old links are
gone.  The set was audited complete against the templates and the demo pages.
"""

from __future__ import annotations

#: Old ``#s-*`` anchor -> new section id (which is the new anchor).  Multiple old
#: anchors mapping to one new id is the D3 defect being retired: Hydrography was
#: ``s-profiles`` (cast), ``s-physics`` (section/timeseries) and ``s-hydro``
#: (index); Biogeochemistry was ``s-aux`` (cast) and ``s-biogeo`` (elsewhere).
LEGACY_ANCHORS: dict[str, str] = {
    "s-overview": "overview",
    "s-profiles": "hydrography",
    "s-physics": "hydrography",
    "s-hydro": "hydrography",
    "s-aux": "biogeochemistry",
    "s-biogeo": "biogeochemistry",
    "s-ts": "ts_diagram",
    "s-stability": "stability",
    "s-ladcp": "velocity",
    "s-map": "map",
    "s-diagnostics": "diagnostics",
    "s-sensors": "sensors",
}


def legacy_anchor_spans(rendered_ids: set[str]) -> str:
    """Return empty ``<span id="old">`` aliases for rendered sections' old anchors.

    Parameters
    ----------
    rendered_ids:
        The set of section ids actually rendered on the page.  A legacy anchor is
        aliased only when its new section is present, so no alias dangles at a
        section the page does not have.

    Returns
    -------
    str
        Concatenated empty spans, one per matching legacy anchor (possibly empty).
    """
    return "".join(
        f'<span id="{old}"></span>'
        for old, new in LEGACY_ANCHORS.items()
        if new in rendered_ids
    )
