# CNV header-excerpt fixtures

Header-only excerpts of real Sea-Bird CNV files, used to test the `#`/`*` header
parser (`ctdcast.config.cnv_header`). They are truncated through `*END*` and are **not**
convertible casts — they live here, not in `fixtures/cnv/`, so the stage-1 converter
does not try to read them as data. Bytes are kept verbatim from the source.

| file | source | pins |
|------|--------|------|
| `MSM121_054_1db.cnv` | seasenselib `examples/MSM121_054_1db.cnv` (header through `*END*`) | the wildedit-after-loopedit chain order (`datcnv, filter, alignctd, celltm, loopedit, wildedit, binavg`) |
