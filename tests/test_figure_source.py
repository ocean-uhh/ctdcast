"""Per-figure source caption: derivation + registry (reports/_vendored/figure_png).

The caption names the draw function behind each panel. The vendored mechanism is
default-off (``design_tokens.SHOW_FIGURE_SOURCE``); ctdcast turns it on in its owned
``reports/design.py`` (``FIGURE_SOURCE``).
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ctdcast.reports._vendored import figure_png


def _draw_demo():
    """A trivial draw function returning a Figure, for the registry round-trip."""
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    return fig


def test_source_for_names_module_and_function():
    """source_for returns ``<module-path>.py:<function>``."""
    src = figure_png.source_for(_draw_demo)
    assert ".py:" in src
    assert src.endswith(":_draw_demo")


def test_source_for_collapses_a_closure():
    """A closure's ``.<locals>.`` prefix is dropped (no dotted qualname leaks out)."""

    def outer():
        def _inner():
            return None

        return _inner

    src = figure_png.source_for(outer())
    assert ".<locals>." not in src
    assert ":" in src and "." not in src.split(":", 1)[1]


def test_render_b64_registers_the_source():
    """render_b64 records the b64 -> source mapping, readable via source_of."""
    figure_png.clear_sources()
    b64 = figure_png.render_b64(_draw_demo)
    assert b64
    assert figure_png.source_of(b64) == figure_png.source_for(_draw_demo)


def test_source_of_is_none_for_unknown():
    """source_of returns None for a missing/empty key, never raises."""
    assert figure_png.source_of(None) is None
    assert figure_png.source_of("not-a-recorded-b64") is None


def test_custom_wrapper_map_registers_its_source():
    """The sections map (custom encode wrapper, not render_b64) still records a source."""
    from ctdcast.reports._plots import _make_all_sections_map_b64

    sections_data = [
        {
            "name": "A",
            "color": "#1f77b4",
            "lats": [60.0, 60.1, 60.2],
            "lons": [-5.0, -5.1, -5.2],
        }
    ]
    figure_png.clear_sources()
    b64 = _make_all_sections_map_b64(
        sections_data, [60.0, 60.1, 60.2], [-5.0, -5.1, -5.2]
    )
    assert b64
    assert (
        figure_png.source_of(b64)
        == "ctdcast/plotters/maps.py:draw_all_sections_map_fig"
    )


def test_vendored_off_ctdcast_on():
    """The shared default is off; ctdcast's owned design flips it on."""
    from ctdcast.reports import design
    from ctdcast.reports._vendored import design_tokens

    assert design_tokens.SHOW_FIGURE_SOURCE is False
    assert design.FIGURE_SOURCE is True


def test_caption_gated_by_show_source():
    """The ``.fig-source`` element appears only when ``show_source`` is on.

    The off contract: the stylesheet carries an unused ``.fig-source`` rule, but no
    page emits an element for it — the panel macro gates emission on ``show_source``.
    """
    import types

    from ctdcast.reports import _env as env_mod

    figure_png.clear_sources()
    b64 = figure_png.render_b64(_draw_demo)
    panel = types.SimpleNamespace(
        is_stub=False, kind="figure", slot="half", payload=b64, caption=None, id="demo"
    )
    # `with context` so the macro reads show_source from the render call, not the env
    # global (imported macros bind globals at import time, which the report sets once).
    tmpl = env_mod._env.from_string(
        "{% import '_macros.html' as m with context %}{{ m.panel(p) }}"
    )

    assert 'class="fig-source"' not in tmpl.render(p=panel, show_source=False)
    assert 'class="fig-source"' in tmpl.render(p=panel, show_source=True)
