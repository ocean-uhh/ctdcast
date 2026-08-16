"""Tests for the section-manifest model and resolver (``reports/_manifest.py``).

These exercise the resolution algorithm in isolation with synthetic panels and
sections — no rendered page needed.  They pin the invariants from the design
note: compact numbering over the rendered subset, appendix lettering, ``Expand``
splicing, ``applies_to`` dropping to the not-applicable list, and ``None`` renders
becoming stubs while the section keeps its heading and number.
"""

import pytest

from ctdcast.reports._manifest import (
    Expand,
    Panel,
    PanelGroup,
    Profile,
    Section,
    _letter,
    resolve,
)


def _panel(pid: str, html: str | None = "<figure/>", **kw) -> Panel:
    """Build a synthetic panel returning a fixed HTML string (or None)."""
    return Panel(id=pid, render=lambda _ctx: html, **kw)


def _registry(*panels: Panel) -> dict[str, Panel]:
    """Return a panel registry keyed by id."""
    return {p.id: p for p in panels}


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------


def test_flat_numbering_is_one_to_n():
    """Content sections number 1..N in profile order."""
    panels = _registry(_panel("a"), _panel("b"), _panel("c"))
    profile = Profile(
        numbering="flat",
        entries=(
            Section("s1", "One", ("a",)),
            Section("s2", "Two", ("b",)),
            Section("s3", "Three", ("c",)),
        ),
    )
    report = resolve(profile, ctx=None, panels=panels)
    assert [s.number for s in report.sections] == ["1", "2", "3"]
    assert [s.title for s in report.sections] == ["One", "Two", "Three"]


def test_appendix_sections_get_letters_and_do_not_pad_content():
    """Appendix sections number A.. independently of the content 1..N run."""
    panels = _registry(_panel("a"), _panel("b"), _panel("z"))
    profile = Profile(
        numbering="flat",
        entries=(
            Section("s1", "One", ("a",)),
            Section("appx", "NetCDF variables", ("z",), role="appendix"),
            Section("s2", "Two", ("b",)),
        ),
    )
    report = resolve(profile, ctx=None, panels=panels)
    nums = {s.id: s.number for s in report.sections}
    assert nums == {"s1": "1", "appx": "A", "s2": "2"}


def test_numbering_none_leaves_numbers_blank():
    """numbering='none' renders every section with an empty number."""
    panels = _registry(_panel("a"), _panel("b"))
    profile = Profile(
        numbering="none",
        entries=(Section("s1", "One", ("a",)), Section("s2", "Two", ("b",))),
    )
    report = resolve(profile, ctx=None, panels=panels)
    assert all(s.number == "" for s in report.sections)


def test_grouped_numbering_not_implemented():
    """numbering='grouped' is reserved and raises until a later branch builds it."""
    profile = Profile(numbering="grouped", entries=())
    with pytest.raises(NotImplementedError):
        resolve(profile, ctx=None, panels={})


@pytest.mark.parametrize(
    "n,expected", [(0, "A"), (1, "B"), (25, "Z"), (26, "AA"), (27, "AB")]
)
def test_letter_sequence(n, expected):
    """Appendix lettering rolls over A..Z, AA, AB like spreadsheet columns."""
    assert _letter(n) == expected


# ---------------------------------------------------------------------------
# Inclusion / not-applicable
# ---------------------------------------------------------------------------


def test_section_dropped_by_explicit_predicate_lands_in_not_applicable():
    """A section whose applies_to is false is omitted and named in the footer list."""
    panels = _registry(_panel("a"), _panel("v"))
    profile = Profile(
        entries=(
            Section("hydro", "Hydrography", ("a",)),
            Section("vel", "Velocity", ("v",), applies_to=lambda _c: False),
        ),
    )
    report = resolve(profile, ctx=None, panels=panels)
    assert [s.id for s in report.sections] == ["hydro"]
    assert report.not_applicable == ("Velocity",)
    # The kept section renumbers compactly — no gap where Velocity was.
    assert report.sections[0].number == "1"


def test_default_section_applies_iff_any_panel_applies():
    """With applies_to=None, a section is dropped when none of its panels apply."""
    panels = _registry(
        _panel("present"),
        _panel("absent", applies_to=lambda _c: False),
    )
    profile = Profile(
        entries=(
            Section("kept", "Kept", ("present",)),
            Section("gone", "Gone", ("absent",)),
        ),
    )
    report = resolve(profile, ctx=None, panels=panels)
    assert [s.id for s in report.sections] == ["kept"]
    assert report.not_applicable == ("Gone",)


# ---------------------------------------------------------------------------
# Panel rendering / stubs
# ---------------------------------------------------------------------------


def test_none_render_becomes_stub_but_keeps_content():
    """A panel that renders None becomes a stub alongside rendered panels."""
    panels = _registry(_panel("ok", "<figure/>"), _panel("empty", None))
    profile = Profile(entries=(Section("s", "S", ("ok", "empty")),))
    report = resolve(profile, ctx=None, panels=panels)
    rpanels = report.sections[0].panels
    assert rpanels[0].is_stub is False and rpanels[0].payload == "<figure/>"
    assert rpanels[1].is_stub is True and rpanels[1].stub_reason


def test_kept_section_with_all_panels_none_keeps_heading_and_number():
    """A section applicable but with every panel None keeps its heading + one stub."""
    panels = _registry(_panel("empty", None))
    profile = Profile(
        entries=(Section("before", "Before", ("empty",), applies_to=lambda _c: True),),
    )
    report = resolve(profile, ctx=None, panels=panels)
    sec = report.sections[0]
    assert sec.number == "1"
    assert len(sec.panels) == 1 and sec.panels[0].is_stub


def test_panel_kind_is_carried_to_resolved_panel():
    """A panel's kind survives resolution so the macro can branch on escaping."""
    panels = _registry(
        _panel("fig"),
        _panel("tbl", "<table/>", kind="table"),
        _panel("prose", "<ul/>", kind="html"),
    )
    profile = Profile(entries=(Section("s", "S", ("fig", "tbl", "prose")),))
    report = resolve(profile, ctx=None, panels=panels)
    kinds = {p.id: p.kind for p in report.sections[0].panels}
    assert kinds == {"fig": "figure", "tbl": "table", "prose": "html"}


def test_callable_slot_is_resolved_against_ctx():
    """A panel whose slot is a callable has it computed from ctx at resolution."""
    panels = _registry(_panel("f", slot=lambda ctx: ctx["width"]))
    profile = Profile(entries=(Section("s", "S", ("f",)),))
    report = resolve(profile, ctx={"width": "half"}, panels=panels)
    assert report.sections[0].panels[0].slot == "half"


def test_panel_not_applying_is_omitted_silently():
    """A panel whose applies_to is false is dropped without a stub."""
    panels = _registry(
        _panel("shown"),
        _panel("hidden", applies_to=lambda _c: False),
    )
    profile = Profile(entries=(Section("s", "S", ("shown", "hidden")),))
    report = resolve(profile, ctx=None, panels=panels)
    ids = [p.id for p in report.sections[0].panels]
    assert ids == ["shown"]


# ---------------------------------------------------------------------------
# Expand
# ---------------------------------------------------------------------------


def test_expand_splices_one_section_per_item():
    """An Expand entry becomes N sections, numbered in the spliced order."""
    panels = _registry(_panel("head"), _panel("var"))
    expand = Expand(
        over=lambda _c: ["Temperature", "Salinity"],
        section=lambda name: Section(f"var_{name.lower()}", name, ("var",)),
    )
    profile = Profile(
        entries=(Section("intro", "Processing history", ("head",)), expand),
    )
    report = resolve(profile, ctx=None, panels=panels)
    assert [s.title for s in report.sections] == [
        "Processing history",
        "Temperature",
        "Salinity",
    ]
    assert [s.number for s in report.sections] == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# PanelGroup — panel-level expansion within one section
# ---------------------------------------------------------------------------


def test_panelgroup_expands_to_panels_under_one_heading():
    """A PanelGroup places N panels in one section without changing the section count."""
    group = PanelGroup(
        over=lambda _c: ["27.7", "27.8"],
        panel=lambda v: Panel(id=f"iso_{v}", render=lambda _c, _v=v: f"<fig {_v}/>"),
    )
    profile = Profile(
        entries=(
            Section("overflow", "Overflow", (group,)),
            Section("after", "After", ("tail",)),
        ),
    )
    panels = _registry(_panel("tail"))
    report = resolve(profile, ctx=None, panels=panels)
    # Two sections, numbered 1 and 2 — the group did not create sections.
    assert [(s.id, s.number) for s in report.sections] == [
        ("overflow", "1"),
        ("after", "2"),
    ]
    # Overflow holds both expanded panels, in order.
    assert [p.id for p in report.sections[0].panels] == ["iso_27.7", "iso_27.8"]


def test_panelgroup_mixes_with_static_panel_ids_in_order():
    """Static panel ids and a PanelGroup interleave in declared order."""
    group = PanelGroup(
        over=lambda _c: ["a", "b"],
        panel=lambda v: Panel(id=f"g_{v}", render=lambda _c: "<fig/>"),
    )
    panels = _registry(_panel("head"), _panel("tail"))
    profile = Profile(entries=(Section("s", "S", ("head", group, "tail")),))
    report = resolve(profile, ctx=None, panels=panels)
    assert [p.id for p in report.sections[0].panels] == ["head", "g_a", "g_b", "tail"]


def test_section_with_only_empty_panelgroup_is_dropped_by_default():
    """A default-applies section whose only PanelGroup yields nothing is dropped."""
    group = PanelGroup(over=lambda _c: [], panel=lambda v: _panel(v))
    profile = Profile(entries=(Section("s", "S", (group,)),))
    report = resolve(profile, ctx=None, panels={})
    assert report.sections == ()
    assert report.not_applicable == ("S",)


def test_empty_panelgroup_with_explicit_applies_keeps_heading_with_stub():
    """An empty PanelGroup under an explicitly-applicable section keeps a stub heading."""
    group = PanelGroup(over=lambda _c: [], panel=lambda v: _panel(v))
    profile = Profile(
        entries=(Section("s", "S", (group,), applies_to=lambda _c: True),),
    )
    report = resolve(profile, ctx=None, panels={})
    assert report.sections[0].number == "1"
    assert report.sections[0].panels[0].is_stub


def test_anchor_returns_number_or_none():
    """ResolvedReport.anchor maps a section id to its number, or None if dropped."""
    panels = _registry(_panel("a"), _panel("v"))
    profile = Profile(
        entries=(
            Section("hydro", "Hydrography", ("a",)),
            Section("vel", "Velocity", ("v",), applies_to=lambda _c: False),
        ),
    )
    report = resolve(profile, ctx=None, panels=panels)
    assert report.anchor("hydro") == "1"
    assert report.anchor("vel") is None
