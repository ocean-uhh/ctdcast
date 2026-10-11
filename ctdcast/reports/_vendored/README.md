# Vendored report layer

The files in this directory are the shared report presentation layer — the
design tokens, the figure encoder, the CSS generator, the page model, the
matplotlib style, and the shared templates. They are kept **byte-identical**
across ctdcast, oceanarray and glidertest.

ctdcast `main` is the source of truth. Make an edit here in ctdcast, then
re-vendor it out to the siblings. Never edit a sibling's copy in place — the
gate below will flag it as drift.

## Re-vendor into a sibling

From the sibling repo, copy ctdcast's directory over its own and refresh the
hash manifest:

    rsync -a --delete ../ctdcast/ctdcast/reports/_vendored/ <pkg>/reports/_vendored/
    python scripts/check_vendored.py --update

then commit. `python scripts/check_vendored.py ../ctdcast` confirms every file
matches.

## The gate

`scripts/check_vendored.py` hashes this directory against `scripts/VENDORED.txt`
and fails if a file drifts; a test runs it in CI, so an edit here that skips the
re-vendor is caught before merge.
