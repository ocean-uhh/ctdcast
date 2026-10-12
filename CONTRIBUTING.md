# Contributing to ctdcast

Thanks for your interest. ctdcast is a small scientific package maintained by a
research group, so contributions are welcome and reviewed by a person rather than
a bot. Please read the two short sections on licensing and credit before opening a
pull request — they exist so that nobody has to have an awkward retrospective
conversation about attribution.

- Repository: <https://github.com/ocean-uhh/ctdcast>
- Licence: MIT (see `LICENSE`)
- Bugs and feature requests: GitHub Issues

---

## Licensing of contributions

ctdcast is MIT licensed, and contributions are accepted **under the same
licence** — what GitHub calls "inbound = outbound". By opening a pull request you
confirm that:

1. you wrote the contribution, or you have the right to submit it; and
2. you agree to license it to the project under the MIT licence.

This does not transfer your copyright, which remains yours.

**If your contribution contains code from somewhere else** — another repository, a
paper's supplementary material, a Stack Overflow answer, a colleague's script,
generated output you did not review — say so in the pull request and name the
source and its licence. This is the single most useful thing you can tell a
reviewer. Code from an unlicensed source cannot be merged until its author agrees,
so flagging it early avoids the work being wasted.

---

## Credit and authorship

Three separate things.

**Copyright** stays with whoever wrote the code. You are not asked to assign it.

**Contributor credit** is automatic and generous. Everyone whose pull request is
merged appears in the git history. If your name or preferred email in the git log
is wrong, open an issue — the fix is a `.mailmap` entry, and it is welcome.

**Citation authorship** is the list in `CITATION.cff`, which propagates into the
Zenodo DOI for every release and therefore into other people's bibliographies. It
reflects *substantial* contribution to the software — its design, a significant
body of its implementation, its test suite, or its documentation architecture —
and is decided by the maintainers at release time. Funding or supervision alone
does not qualify.

There is no line count that guarantees citation authorship, and none that excludes
it: a well-designed 200-line module that fixes a whole class of problem may count
where 2,000 lines of mechanical change does not. If you believe your contribution
crosses that line and it has not been reflected, please just say so in an issue.
Being asked is better than being resented.

Where a contribution is adapted from someone else's work rather than written from
scratch, we credit it **in the docstring of the code itself**, so the attribution
travels with the code rather than living only in a file nobody reads.

---

## Scope

ctdcast owns the CTD lifecycle from a proprietary instrument file to a QC'd,
CF/CCHDO-aligned netCDF and a compiled profiles grid, plus the self-contained HTML
report. Some of that is settled; some is open to contribution; a few things are
deliberately out of scope.

**Fixed** — changing these changes every user's output files, so open an issue
before a pull request:

- CCHDO variable naming on disk.
- One QC stream, QARTOD-native; WOCE and OceanSITES flags are write-time
  translations of it.
- Salinity is always derived from C/T/P, never stored, and re-derived whenever any
  of them changes.
- Provenance reconstructable from the output file alone: a calibration slope or
  threshold lives on the variable's own attributes.
- The per-stage file layout and the stage registry.
- Canonical unit spellings (from 0.4.0).

**Open** — selectable methods, added with the existing default unchanged:

- Stage-3 processing-chain steps: alignment and cell-thermal-mass parameter
  finders, bottle-stop conductivity-slope fits (the ctdproc ports).
- QC tests and thresholds — config-driven, recorded in the output attributes.
- Report figures — new panels through the section manifest.
- Readers for other instrument formats. The `.hex` / `.xmlcon` path is deferred on
  purpose, pending the Sea-Bird processing chain.

**Out of scope, on purpose** — cruise-level gridded products (sections and time
series as interpolated fields). The interpolation choice *is* the product, so
gridding irregular casts would invent data. This is where ctdcast's scope differs
in kind from the sibling `oceanarray`, whose grid step is an open, central part of
what it does.

---

## Getting set up

```bash
git clone https://github.com/ocean-uhh/ctdcast.git
cd ctdcast
python -m venv venv && source venv/bin/activate      # or conda
pip install -e ".[dev]"                              # runtime + test + docs + ruff
```

Python 3.10–3.13 are supported; CI runs the full range on Ubuntu and Python 3.11
on macOS and Windows.

## Before you open a pull request

Run what CI runs:

```bash
ruff check .                      # lint (rule families configured in pyproject.toml)
pytest -m "not slow"              # unit tests (addopts already adds --cov)
pytest tests/integration/ -v --no-cov   # integration tests (excluded from the matrix)
pytest --cov-fail-under=79        # the coverage gate CI enforces, plus the per-module floors
```

The integration suite is marked `slow` and is skipped by `-m "not slow"`, so it
does **not** run in the cross-platform matrix. Please run it locally — it is the
part most likely to catch a real regression, because it builds whole reports.

Documentation:

```bash
cd docs && make clean html
```

## House conventions

- **Docstrings are numpydoc**, with types in the signature *and* in the
  `Parameters` / `Returns` sections. Say what a function does, and where the
  reasoning is not obvious, why.
- **Documentation source files are reStructuredText** (`.rst`), not Markdown. The
  repo-root files (`README.md`, this file) are the exception, because GitHub
  expects Markdown there.
- **Identifiers, comments and docstrings in English.** The codebase has a mixed
  heritage; new code should be consistent.
- **Never silently substitute a default** where the correct value cannot be
  determined. Raise, or warn and record what was assumed in the output's metadata.
  A plausible wrong number is worse than an error, because nothing downstream can
  detect it.
- **Record provenance.** If a processing step applies a threshold, a coefficient,
  or a calibration, that value belongs in the output file's attributes. The
  standard is that the treatment can be reconstructed from the output alone.
- One logical change per pull request. A rename PR that also fixes a bug is a PR
  nobody can review.

## Tests

New behaviour needs a test. For anything numerical, assert a **value** —
`pytest.approx`, `numpy.testing.assert_allclose` — against a figure you can
justify independently of the code: an analytic case, an invariant that must hold
for any input, or a cross-check against `gsw` or another implementation. A test
whose expected value was produced by running the code proves only that the code
has not changed; if that is genuinely the best available, say so in the test's
docstring.

Please do not add tests that pass when nothing happened. `assert result is not
None` on a function that returns `None` on failure is the shape to avoid.

## Data files

Test fixtures should be real instrument data, trimmed small — a few hundred scans
is plenty. Keep the file header verbatim; that is usually the interesting part. If
the data are not yours to publish, open an issue rather than committing them.

## Commit messages

Conventional-commit prefixes (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`,
`ci:`, `cleanup:`) and an imperative subject. Pull requests are squash-merged under
a bracket-tagged title (`[FEAT]`, `[FIX]`, `[REFACTOR]`, `[CLEANUP]`, …), so that
tag is what appears on `main` and what the changelog groups by. If you worked with
someone, or adapted their code, add a trailer:

```
Co-authored-by: Name <email@example.com>
```

## Questions

Open an issue. A question that turns out to be a documentation gap is a useful
contribution in itself.
