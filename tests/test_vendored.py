"""Guard the vendored report-design files against a local edit that skipped re-vendor.

The vendored directory checks itself: ``check.main([])`` hashes every file under
``reports/_vendored/`` against ``MANIFEST.txt`` and returns non-zero on any drift
— a file edited since ``--update``, a file on disk not recorded, or a recorded
file missing. Cross-repo equality — are the siblings in sync? — is ``check``'s
``../sibling`` mode, run in review, not a test here.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ctdcast.reports._vendored import check

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENDORED = _REPO_ROOT / "ctdcast" / "reports" / "_vendored"


def test_vendored_copy_matches_its_manifest(capsys):
    """Every vendored file matches MANIFEST.txt; names the drifted file on failure."""
    rc = check.main([])
    out = capsys.readouterr().out
    assert rc == 0, f"vendored files drift from MANIFEST.txt:\n{out}"


def test_vendored_python_is_ruff_format_stable():
    """``ruff format`` leaves the vendored Python unchanged.

    A consumer that runs a whole-repo ``ruff format`` must not rewrite a byte-identical copy
    (which would then fail its own ``check.py``); so the source-of-truth files are kept already
    formatted here.  Guards the family's re-vendor contract.

    Skipped when ruff is not importable (the CI lint job enforces this, so the test job need not
    carry the lint tooling as a dependency).
    """
    pytest.importorskip(
        "ruff", reason="ruff not installed; the lint job enforces format stability"
    )
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", str(_VENDORED)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"vendored files are not ruff-format-stable:\n{result.stdout}{result.stderr}"
    )


def test_compare_sibling_flags_a_sibling_only_file(tmp_path, capsys):
    """A file present only in the sibling is drift (the union, not just the local set)."""
    sibling_vendored = tmp_path / "sibling" / "pkg" / "reports" / "_vendored"
    shutil.copytree(_VENDORED, sibling_vendored)
    (sibling_vendored / "rogue.py").write_text(
        "# only in the sibling\n", encoding="utf-8"
    )
    rc = check.compare_sibling(tmp_path / "sibling")
    out = capsys.readouterr().out
    assert rc >= 1, "a sibling-only file must count as drift"
    assert "EXTRA" in out and "rogue.py" in out


def test_compare_manifests_by_basename(tmp_path):
    """``--compare`` diffs two manifests by basename: identical passes, a flipped hash drifts."""
    local = check.MANIFEST.read_text(encoding="utf-8")
    other = tmp_path / "MANIFEST.txt"
    other.write_text(local, encoding="utf-8")
    assert check.compare_manifests(other) == 0

    flipped, out_lines = False, []
    for line in local.splitlines():
        if line and not line.startswith("#") and not flipped:
            digest, rel = line.split(maxsplit=1)
            digest = ("1" if digest[0] == "0" else "0") + digest[1:]
            line = f"{digest}  {rel}"
            flipped = True
        out_lines.append(line)
    other.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    assert check.compare_manifests(other) >= 1


def test_parse_manifest_rejects_missing_malformed_and_duplicate(tmp_path):
    """A missing, malformed, or duplicate-keyed manifest exits 1 with a message, not a traceback."""
    with pytest.raises(SystemExit):
        check.parse_manifest(tmp_path / "nope.txt")

    malformed = tmp_path / "malformed.txt"
    malformed.write_text("this-line-has-no-hash-and-path-split\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        check.parse_manifest(malformed)

    duplicate = tmp_path / "duplicate.txt"
    duplicate.write_text("aaa  x.py\nbbb  x.py\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        check.parse_manifest(duplicate)


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
