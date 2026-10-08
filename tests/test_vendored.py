"""Guard the vendored report-design files against a local edit that skipped re-vendor.

``VENDORED.txt`` records the sha256 of each file shared byte-identical with the
sibling packages (oceanarray, glidertest).  These tests fail if a recorded file's
bytes drift from its hash, or if the recorded set no longer matches the list in
``scripts/check_vendored.py`` — either means an edit landed without running
``scripts/check_vendored.py --update``.  Cross-repo equality (are the siblings in
sync?) is the script's job, run in review, not a test here.
"""

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_vendored.py"

_spec = importlib.util.spec_from_file_location("check_vendored", _SCRIPT)
check_vendored = importlib.util.module_from_spec(_spec)
sys.modules["check_vendored"] = check_vendored
_spec.loader.exec_module(check_vendored)


def test_manifest_lists_exactly_the_vendored_set():
    """VENDORED.txt records every vendored file and no others."""
    recorded = set(check_vendored.load_expected())
    assert recorded == set(check_vendored.VENDORED)


def test_vendored_files_match_recorded_hashes():
    """Each vendored file's bytes still match its recorded sha256."""
    expected = check_vendored.load_expected()
    drifted = [
        rel
        for rel in check_vendored.VENDORED
        if check_vendored.sha256(_REPO_ROOT / rel) != expected[rel]
    ]
    assert not drifted, (
        f"vendored files edited without --update: {drifted}; "
        "run `python scripts/check_vendored.py --update`"
    )
