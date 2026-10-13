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


def test_vendored_off_ctdcast_on():
    """The shared default is off; ctdcast's owned design flips it on."""
    from ctdcast.reports import design
    from ctdcast.reports._vendored import design_tokens

    assert design_tokens.SHOW_FIGURE_SOURCE is False
    assert design.FIGURE_SOURCE is True
