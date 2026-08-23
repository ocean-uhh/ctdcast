# CNV/HEX header-excerpt fixtures

Header-only excerpts of real Sea-Bird files, used to test the `#`/`*` header parser
(`ctdcast.config.cnv_header`). They are truncated through `*END*` and are **not**
convertible casts — they live here, not in `fixtures/cnv/` or the local-only
`fixtures/hex/`, so the stage-1 converter does not try to read them as data and the
tests do not depend on git-excluded fixtures. Bytes are kept verbatim from the source.

| file | source | pins |
|------|--------|------|
| `MSM121_054_1db.cnv` | seasenselib `examples/MSM121_054_1db.cnv` (header through `*END*`) | the wildedit-after-loopedit chain order (`datcnv, filter, alignctd, celltm, loopedit, wildedit, binavg`) |
| `msm_021_1_168_header.hex.txt` | `fixtures/hex/msm_021_1_168_short.hex` (`*` block through `*END*`) | 11plus V 5.0 **asymmetric** advance (c0 +0.073 s, c1 +0.043 s) |
| `PS129_014_01_header.hex.txt` | `fixtures/hex/PS129_014_01_short.hex` (`*` block through `*END*`) | no deck-unit line — absence is not an error |
