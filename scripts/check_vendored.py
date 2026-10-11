"""Check the report-design files that are vendored byte-identical across packages.

ctdcast ``main`` is the source of truth for the shared report-design files under
``ctdcast/reports/_vendored/`` (design tokens, the figure encoder, the CSS
generator, the page model, the mplstyle, and the masthead-nav template).
oceanarray and glidertest carry byte-identical copies under their own
``<pkg>/reports/_vendored/`` and re-vendor from here; they never edit their
copies in place.

The vendored set is the *contents of the directory*, not a hand-kept list: every
file under ``ctdcast/reports/_vendored/`` (minus ``__pycache__``) is checked.

Usage
-----
Verify the local copies match the recorded hashes (what the test does)::

    venv/bin/python scripts/check_vendored.py

Compare the local copies against one or more sibling checkouts::

    venv/bin/python scripts/check_vendored.py ../oceanarray ../glidertest

Regenerate ``VENDORED.txt`` after an intentional edit to a vendored file::

    venv/bin/python scripts/check_vendored.py --update

Exit code is 1 if any file drifts (local hash mismatch, a recorded file missing
on disk, or a sibling file that is absent or differs), 0 otherwise.  A sibling
*repository* that is absent is reported and skipped; a sibling *file* that is
missing counts as drift.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

#: Repo-relative directory holding every vendored file.  The directory is the
#: source of the set — add a file to it and it is checked, no list to update.
VENDORED_DIR = "ctdcast/reports/_vendored"

REPO_ROOT = Path(__file__).resolve().parent.parent
# Lives beside this script, not at the repo root: the manifest is per-repo check
# infrastructure (it records this package's paths), not a vendored file itself,
# so it must not sit inside the rsync'd directory or clutter the root.
MANIFEST = Path(__file__).resolve().parent / "VENDORED.txt"


def vendored_files() -> list[str]:
    """Return the repo-relative path of every vendored file, sorted.

    Walks :data:`VENDORED_DIR` and skips ``__pycache__`` and compiled files, so
    the returned list is exactly what should be byte-identical across packages.
    """
    root = REPO_ROOT / VENDORED_DIR
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.is_dir() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        out.append(p.relative_to(REPO_ROOT).as_posix())
    return out


def sha256(path: Path) -> str:
    """Return the hex sha256 of a file's *content*, normalized to LF line endings.

    The vendored files are text, and "byte-identical across packages" means identical
    text — not identical line endings.  CRLF (a Windows checkout, or a sibling with a
    different ``core.autocrlf``) is normalized to LF before hashing so the hash is the same
    on every platform; otherwise the guard would fail on Windows CI for every file.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_expected() -> dict[str, str]:
    """Parse ``VENDORED.txt`` into a ``{relative-path: sha256}`` mapping.

    Exits 1 with a clear message on a missing manifest, a malformed line, or a
    duplicate path — a silent last-wins would hide a contradictory entry.
    """
    if not MANIFEST.exists():
        raise SystemExit(
            f"{MANIFEST.name} not found — run: python scripts/check_vendored.py --update"
        )
    expected: dict[str, str] = {}
    for n, raw in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise SystemExit(
                f"{MANIFEST.name}:{n}: malformed line "
                f"(expected '<sha256>  <path>'): {raw!r}"
            )
        digest, rel = parts
        if rel in expected:
            raise SystemExit(f"{MANIFEST.name}:{n}: duplicate path {rel}")
        expected[rel] = digest
    return expected


def package_name(repo: Path) -> str:
    """Return the sibling's import package from its ``pyproject.toml`` ``[project].name``.

    Deriving the package from the project name — not the checkout directory name
    — means a sibling checked out as ``../oceanarray-review`` or a git worktree
    still maps its vendored paths correctly.
    """
    text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)["project"]["name"]
    except ModuleNotFoundError:  # Python < 3.11
        in_project = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_project = stripped == "[project]"
                continue
            if in_project:
                m = re.match(r'name\s*=\s*"([^"]+)"', stripped)
                if m:
                    return m.group(1)
        raise SystemExit(
            f"could not read [project].name from {repo}/pyproject.toml"
        ) from None


def write_manifest() -> None:
    """Rewrite ``VENDORED.txt`` from the current local files."""
    lines = [
        "# sha256 of the report-design files vendored byte-identical across",
        "# ctdcast, oceanarray and glidertest.  Source of truth: ctdcast main.",
        "# The set is the contents of ctdcast/reports/_vendored/.",
        "# Regenerate after an intentional edit: "
        "python scripts/check_vendored.py --update",
    ]
    lines += [f"{sha256(REPO_ROOT / rel)}  {rel}" for rel in vendored_files()]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_local() -> int:
    """Check each local file against its recorded hash.  Return a failure count.

    Flags both directions: a file on disk not in ``VENDORED.txt`` (ran without
    ``--update``) and a recorded file missing from disk.
    """
    expected = load_expected()
    present = vendored_files()
    failures = 0
    for rel in present:
        want = expected.get(rel)
        if want is None:
            print(f"NOT RECORDED  {rel} (run --update)")
            failures += 1
        elif want != sha256(REPO_ROOT / rel):
            print(f"DRIFTED       {rel} (edited since --update)")
            failures += 1
    for rel in expected:
        if rel not in present:
            print(f"MISSING       {rel} (recorded but not on disk)")
            failures += 1
    if not failures:
        print(f"OK            {len(present)} vendored files match VENDORED.txt")
    return failures


def compare_sibling(sibling: Path) -> int:
    """Byte-compare every vendored file against *sibling*.  Return a mismatch count.

    The vendored files live under each repo's own package directory, so the
    leading package segment of each path is mapped to the sibling's package name
    (from its ``pyproject.toml``).  A vendored file missing in the sibling counts
    as drift.
    """
    print(f"\n== {sibling} ==")
    if not sibling.exists():
        print("  absent — skipped")
        return 0
    pkg = package_name(sibling)
    mismatches = 0
    for rel in vendored_files():
        here = REPO_ROOT / rel
        there = sibling / rel.replace("ctdcast/", f"{pkg}/", 1)
        if not there.exists():
            print(f"  MISSING   {there.relative_to(sibling)}")
            mismatches += 1
        elif sha256(here) != sha256(there):
            print(f"  DIFFERS   {there.relative_to(sibling)}")
            mismatches += 1
        else:
            print(f"  ok        {there.relative_to(sibling)}")
    return mismatches


def main(argv: list[str]) -> int:
    """Run the check; see the module docstring for the argument forms."""
    if "--update" in argv:
        write_manifest()
        print(
            f"wrote {MANIFEST.relative_to(REPO_ROOT)} ({len(vendored_files())} files)"
        )
        return 0
    siblings = [a for a in argv if not a.startswith("-")]
    if not siblings:
        return 1 if verify_local() else 0
    total = sum(compare_sibling(Path(s)) for s in siblings)
    print(f"\n{total} mismatch(es) across {len(siblings)} sibling(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
