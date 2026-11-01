"""Owned report templates follow the vendored table conventions."""

import re
from pathlib import Path

_TEMPLATES = Path(__file__).parents[1] / "ctdcast" / "reports" / "templates"

#: Owned templates still writing their own ``<th>``, with the reason each is exempt.
_TH_EXEMPT = {
    # Column classes (``num``) and a ``title`` tooltip that the vendored ``thead`` macro
    # cannot express yet.
    "casts.html",
}


def test_owned_templates_use_the_vendored_thead():
    offenders = sorted(
        p.name
        for p in _TEMPLATES.glob("*.html")
        if p.name not in _TH_EXEMPT and re.search(r"<th[\s>]", p.read_text(encoding="utf-8"))
    )
    assert offenders == []
