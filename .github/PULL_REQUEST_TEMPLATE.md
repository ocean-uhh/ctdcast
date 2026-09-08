<!--
Title: prefix with one tag — [DOC] [FIX] [FEAT] [REFACTOR] [TEST] [CI] [CLEANUP]
Example: [FIX] Correct dimension handling in RBR reader
Keep it concise. Delete any section that does not apply (except Summary).
Write each bullet/paragraph as one continuous line — GitHub soft-wraps.
-->

## Summary

What changed and why, in one short paragraph.

## What's changed

- Concrete change (one bullet each).

## Breaking changes

Each breaking change and how to migrate (removed/renamed public API or CLI flag, changed signature or parameter meaning, changed output/config layout). Write "None" if there are none — keep the section so reviewers see it was considered.

## Notes

Optional — design decisions or trade-offs, screenshots if outputs changed, related issues (Fixes #, Related to #), and anything reviewers should look at closely.

## Checklist

- [ ] Followed the [code conventions](CONTRIBUTING.md)
- [ ] Added or updated tests to cover the change
- [ ] Updated documentation if needed
- [ ] Ran `ruff check . --fix` and `pytest` — all pass
