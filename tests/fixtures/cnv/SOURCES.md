# CNV fixtures

| file | source | pins |
|------|--------|------|
| `mixsed2_050_24Hz_slice.cnv` | OdB 2026 (MIXSED2) `CTD/cnv_24Hz_WithoutAlign/mixsed2_050.cnv`: the header through `*END*` and the first 1150 scans, verbatim (the header's `nvalues` still says 28003) | Sea-Bird's Loop Edit marks in the `flag` column (`-9.990e-29`, 1076 of the 1150 scans: the surface soak and early reversals) survive reading and writing |
