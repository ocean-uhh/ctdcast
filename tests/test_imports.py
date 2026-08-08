# tests/test_imports.py
"""Every module in the package imports cleanly.

Cheap protection for code the suite never executes: a rename that breaks an
import in a 0%-covered module fails here instead of at a user's first call.
"""

import importlib
import pkgutil

import pytest

import ctdcast  # or oceanarray


def _module_names():
    return sorted(
        m.name
        for m in pkgutil.walk_packages(ctdcast.__path__, prefix="ctdcast.")
        if "legacy" not in m.name
    )


@pytest.mark.parametrize("name", _module_names())
def test_module_imports(name):
    importlib.import_module(name)
