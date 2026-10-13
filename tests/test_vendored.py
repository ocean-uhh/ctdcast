"""Guard the vendored report-design files against a local edit that skipped re-vendor.

The vendored directory checks itself: ``check.main([])`` hashes every file under
``reports/_vendored/`` against ``MANIFEST.txt`` and returns non-zero on any drift
— a file edited since ``--update``, a file on disk not recorded, or a recorded
file missing. Cross-repo equality — are the siblings in sync? — is ``check``'s
``../sibling`` mode, run in review, not a test here.
"""

from pathlib import Path

from ctdcast.reports._vendored import check

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_vendored_copy_matches_its_manifest(capsys):
    """Every vendored file matches MANIFEST.txt; names the drifted file on failure."""
    rc = check.main([])
    out = capsys.readouterr().out
    assert rc == 0, f"vendored files drift from MANIFEST.txt:\n{out}"


def test_no_owned_template_shadows_a_vendored_one():
    """No template filename exists in both the owned and vendored template dirs.

    The report environment loads owned templates first, so an owned partial with
    a vendored one's name would silently fork the shared copy. This is a ctdcast
    report-env concern, not vendoring integrity, so it stays a separate test.
    """
    owned = _REPO_ROOT / "ctdcast" / "reports" / "templates"
    vendored = _REPO_ROOT / "ctdcast" / "reports" / "_vendored" / "templates"
    owned_names = {p.name for p in owned.glob("*") if p.is_file()}
    vendored_names = {p.name for p in vendored.glob("*") if p.is_file()}
    assert not (owned_names & vendored_names), (
        f"owned templates shadow vendored ones: {sorted(owned_names & vendored_names)}"
    )
