"""Self-check for the report-design files vendored byte-identical across packages.

This module lives *inside* the vendored directory it guards, so a consumer
(oceanarray, glidertest) takes the whole directory and nothing else — the hash
manifest and the gate travel with the files. ctdcast ``main`` is the source of
truth; siblings re-vendor from it and never edit their copies in place.

The vendored set is the *contents of this directory*: every file here except
``MANIFEST.txt`` (which records the others' hashes) and ``__pycache__``. So
``check.py`` and ``README.md`` guard themselves too, and the whole directory is
byte-identical across the three repositories.

Paths in the manifest are relative to this directory, so the manifest is itself
identical across packages (no ``ctdcast/`` vs ``oceanarray/`` prefix).

Usage
-----
Verify the local copies match the recorded hashes (what the test does)::

    python -m <pkg>.reports._vendored.check

Compare the local copies against one or more sibling checkouts::

    python -m <pkg>.reports._vendored.check ../oceanarray ../glidertest

Regenerate ``MANIFEST.txt`` after an intentional edit to a vendored file::

    python -m <pkg>.reports._vendored.check --update

Exit code is 1 if any file drifts (local hash mismatch, a recorded file missing
on disk, or a sibling file that is absent or differs), 0 otherwise. A sibling
*repository* that is absent is reported and skipped; a sibling *file* that is
missing counts as drift.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

#: The directory this file lives in — the vendored set is exactly its contents.
VENDORED_ROOT = Path(__file__).resolve().parent

#: Hash manifest, beside the files it records.  Excluded from the hashed set
#: (a file cannot record its own hash), so every *other* file is guarded.
MANIFEST = VENDORED_ROOT / "MANIFEST.txt"

#: How to invoke this module, resolved per repo at runtime (the source stays
#: byte-identical; only the printed string differs).
_INVOKE = (
    f"python -m {__package__}.check"
    if __package__
    else ("python -m <pkg>.reports._vendored.check")
)


def vendored_files() -> list[str]:
    """Return every vendored file's path relative to this directory, sorted.

    Skips ``MANIFEST.txt`` and ``__pycache__`` / compiled files; the result is
    exactly what must be byte-identical across packages.
    """
    out: list[str] = []
    for p in sorted(VENDORED_ROOT.rglob("*")):
        if p.is_dir() or p == MANIFEST:
            continue
        rel = p.relative_to(VENDORED_ROOT)
        # Skip compiled files and any dot-prefixed component (e.g. a macOS
        # ``.DS_Store``, ``__pycache__``) — else the set differs per machine and
        # the test fails locally while CI stays green.
        if p.suffix == ".pyc" or any(
            part == "__pycache__" or part.startswith(".") for part in rel.parts
        ):
            continue
        out.append(rel.as_posix())
    return out


def sha256(path: Path) -> str:
    """Return the hex sha256 of a file's *content*, normalized to LF line endings.

    "Byte-identical across packages" means identical text, not identical line
    endings: CRLF (a Windows checkout, or a sibling with a different
    ``core.autocrlf``) is normalized to LF before hashing, so the hash matches on
    every platform instead of failing on Windows for every file.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_expected() -> dict[str, str]:
    """Parse ``MANIFEST.txt`` into a ``{relative-path: sha256}`` mapping.

    Exits 1 with a clear message on a missing manifest, a malformed line, or a
    duplicate path — a silent last-wins would hide a contradictory entry.
    """
    if not MANIFEST.exists():
        raise SystemExit(f"{MANIFEST.name} not found — run: {_INVOKE} --update")
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


def sibling_vendored(repo: Path) -> Path | None:
    """Return *repo*'s copy of this directory, or ``None`` if it has none.

    Located by the sibling's own ``check.py`` (``<repo>/*/*/_vendored/check.py``),
    so neither the package name — which need not equal the distribution name
    (``AMOCatlas`` installs as ``amocatlas``) — nor the ``reports`` vs ``report``
    spelling of the layer's parent directory is assumed.
    """
    matches = sorted(repo.glob("*/*/_vendored/check.py"))
    return matches[0].parent if matches else None


def write_manifest() -> None:
    """Rewrite ``MANIFEST.txt`` from the current local files."""
    lines = [
        "# sha256 of the report-design files vendored byte-identical across",
        "# ctdcast, oceanarray and glidertest.  Source of truth: ctdcast main.",
        "# The set is the contents of this directory, minus this file.",
        "# Regenerate after an intentional edit: "
        "python -m <pkg>.reports._vendored.check --update",
    ]
    lines += [f"{sha256(VENDORED_ROOT / rel)}  {rel}" for rel in vendored_files()]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_local() -> int:
    """Check each local file against its recorded hash.  Return a failure count.

    Flags both directions: a file on disk not in ``MANIFEST.txt`` (ran without
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
        elif want != sha256(VENDORED_ROOT / rel):
            print(f"DRIFTED       {rel} (edited since --update)")
            failures += 1
    for rel in expected:
        if rel not in present:
            print(f"MISSING       {rel} (recorded but not on disk)")
            failures += 1
    if not failures:
        print(f"OK            {len(present)} vendored files match {MANIFEST.name}")
    return failures


def compare_sibling(repo: Path) -> int:
    """Byte-compare every vendored file against *repo*'s copy.  Return a mismatch count.

    A vendored file missing in the sibling counts as drift; an absent sibling
    *repository* is reported and skipped.
    """
    print(f"\n== {repo} ==")
    if not repo.exists():
        print("  absent — skipped")
        return 0
    there_root = sibling_vendored(repo)
    if there_root is None:
        print("  no _vendored/ copy found — not synced")
        return 1
    mismatches = 0
    for rel in vendored_files():
        there = there_root / rel
        if not there.exists():
            print(f"  MISSING   {there}")
            mismatches += 1
        elif sha256(VENDORED_ROOT / rel) != sha256(there):
            print(f"  DIFFERS   {there}")
            mismatches += 1
        else:
            print(f"  ok        {rel}")
    return mismatches


def main(argv: list[str]) -> int:
    """Run the check; see the module docstring for the argument forms."""
    if "--update" in argv:
        write_manifest()
        print(f"wrote {MANIFEST.name} ({len(vendored_files())} files)")
        return 0
    siblings = [a for a in argv if not a.startswith("-")]
    if not siblings:
        return 1 if verify_local() else 0
    total = sum(compare_sibling(Path(s)) for s in siblings)
    print(f"\n{total} mismatch(es) across {len(siblings)} sibling(s)")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
