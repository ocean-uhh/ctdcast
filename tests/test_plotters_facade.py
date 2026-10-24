"""The deprecated ``ctdcast.plotters.plots`` façade warns and re-exports the split modules."""

import importlib
import sys

import pytest

from ctdcast.plotters import ladcp, maps, profiles, sections, timeseries


def test_plots_facade_warns_and_reexports():
    sys.modules.pop("ctdcast.plotters.plots", None)
    with pytest.warns(DeprecationWarning, match="ctdcast.plotters.plots is split"):
        plots = importlib.import_module("ctdcast.plotters.plots")
    mods = (maps, profiles, sections, timeseries, ladcp)
    # Every figure builder is re-exported...
    for mod in mods:
        for name in dir(mod):
            if name.startswith("draw_"):
                assert getattr(plots, name) is getattr(mod, name), name
                assert name in plots.__all__, name
    # ...and every re-export is defined in one of the split modules.
    split_names = {m.__name__ for m in mods}
    for name in plots.__all__:
        assert getattr(plots, name).__module__ in split_names, name


def test_no_internal_caller_imports_the_facade():
    """Package code imports the subject modules, so the warning never fires in-tree."""
    from pathlib import Path

    pkg = Path(importlib.import_module("ctdcast").__file__).parent
    offenders = [
        str(p.relative_to(pkg))
        for p in pkg.rglob("*.py")
        if p.name != "plots.py"
        and "ctdcast.plotters.plots import" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
