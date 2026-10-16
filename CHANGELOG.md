# Changelog

All notable changes to ctdcast are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Per-figure `source:` caption** — each report figure can carry a line naming the draw function that produced it (`<module>.py:<function>`), for provenance. The mechanism is vendored (`reports/_vendored/figure_png.source_for`/`source_of`, gated by a default-off `SHOW_FIGURE_SOURCE` flag); ctdcast turns it on in its owned `reports/design.py` (`FIGURE_SOURCE = True`), the same override pattern as the colormaps. With the flag off a page is visually identical to before; the stylesheet gains one unused `.fig-source` rule (no element matches it).

### Changed

- The vendored report layer is now self-contained: the hash manifest and the drift-check gate moved into `reports/_vendored/` as `MANIFEST.txt` and `check.py` (were `scripts/VENDORED.txt` and `scripts/check_vendored.py`), so a consumer vendors the directory and nothing else. Manifest paths are now directory-relative, and `check.py` locates its own directory, so both files are byte-identical across ctdcast, oceanarray and glidertest. Run the gate with `python -m ctdcast.reports._vendored.check`.
- The bundled Leaflet assets (`leaflet.min.js`, `leaflet.min.css`) and their `LICENSE` moved into `reports/_vendored/leaflet/`, shared byte-identical across the sibling packages, so the ~160 KB library is bundled once; the cruise map reads them there. No change to generated output.
- The cruise map no longer falls back to a CDN: a missing bundled Leaflet asset now raises rather than fetching from jsdelivr/cdnjs or emitting an empty map, so the offline-at-sea guarantee holds at build time instead of failing silently at view time.

### Fixed

- `time_coverage_end` was written from the per-profile **start** times, so a compiled file's stated end was the start of the last profile, not the last data timestamp (on the demo cruise, ~19 minutes short). `coverage_attrs`/`cruise_global_attrs` now take start and end times separately: `time_coverage_start` is the earliest start and `time_coverage_end` the latest end, each from its own variable (`time_start`/`time_end`); the LADCP product, with one time per profile, uses it for both. The value of `time_coverage_end` in every regenerated stage file changes accordingly.

## [0.3.0] — 2026-10-12

### Added

- **Shared report layer vendored under `reports/_vendored/`** — the design tokens, matplotlib style, figure encoder, CSS generator, page model and nav template, kept byte-identical across ctdcast, oceanarray and glidertest; `scripts/check_vendored.py` walks the directory and gates drift against `scripts/VENDORED.txt`.
- **Per-quantity colormaps** — a vendored `CMAPS` table keyed by physical quantity with a `QUANTITY_BY_STANDARD_NAME` bridge, resolved per variable by the owned `reports/design.py`, which a package can override for its own science without editing the shared table. `cmocean` is now a dependency (for the `cmo.*` defaults).
- **Preferred sensor per cast** — `processing.preferred_pair` and `processing.preferred_oxygen` declare which channel (`primary`/`secondary`) is the better one on a dual-sensor cast, as a cruise-wide `default` plus per-cast-range exceptions. Stage 3 builds the plain composites `ctd_temperature` / `ctd_salinity` / `conductivity` / `ctd_oxygen` from the chosen channel (per-cast selection, never a blend; an undeclared dual cast gets no plain name, never a silent `_1`), stamps the choice and the resolved sensor (`sensor_<role>_preferred`), and `profiles.nc` records `preferred_pair`/`preferred_oxygen` and `sensor_<role>_preferred` per profile. `oxygen_saturation`/AOU are derived per oxygen line from that line's own T/S, with the composite following `preferred_oxygen` (an undeclared dual-oxygen cast's figure falls back to the primary line; the composite records the line and that it was undeclared). The declaration is reconciled against the per-cast sensor serials at compile and in `ctdcast validate` (warnings only; a lettered-sibling serial mismatch is flagged). `ctd_oxygen_1`/`_2` carry the line-plumbing assumption (`oxygen_1` = primary line / Sea-Bird `sbox0`) as a `comment`.

### Changed

- **QC flag colours** are now a colour-blind-safe Okabe–Ito set (good teal `#009E73`, suspect orange `#E69F00`, fail vermillion `#D55E00`, plus the rest of the 0–9 scale), replacing the red/green pair a deuteranope could not separate; visible on every QC table.
- **Section and profile colormaps** moved to the shared family defaults: oxygen off red–green `RdYlGn` to `cmo.oxy`, density `Purples` to `BuPu`, oxygen saturation `RdYlGn` to `BrBG`; temperature, salinity, chlorophyll and turbidity unchanged.
- **Report page modules renamed to public names** — `reports.index` / `cast` / `section` / `timeseries` / `dataset` / `cruise_map` / `qc_tables` (were underscore-prefixed) and `reports/_report_css` to `reports/design`; the public API (`ctdcast.report`) is unchanged.
- Masthead-nav and heading styling: a back pill that renders without rows, pill hover hints and a contrast edge for same-colour mastheads, tighter multi-row spacing, and an `h3` subsection-heading rule; `Stub` panel reasons are shaped to one length-capped line on construction; `validate_nav` requires an explicit pill `state`.
- netCDF output is written with lossless zlib compression (level 4) on every numeric variable with a dimension, coordinates included; the shuffle filter is applied to all except `float64`, where it was measured to enlarge the science columns. Transparent to readers; no schema or value change.

### Fixed

- The cruise-overview panels now resolve the single/dual-sensor variable form, so oxygen is no longer dropped from the overview on single-sensor cruises (the section pages already resolved it).
- `oxygen_saturation` derivation passed latitude and longitude to `gsw.O2sol` in the wrong order (`O2sol(SA, CT, p, lon, lat)` expects longitude first), evaluating solubility at a transposed position. The effect is a small, systematic bias in the derived % saturation; fixing it changes `oxygen_saturation` (and the AOU proxy) slightly. These are derived-on-demand report quantities, not stored, so no on-disk file changes.

## [0.2.1] — 2026-09-19

### Fixed

- Cruise-name fallback in the report index now uses the `UNKNOWN_CRUISE_ID` constant (`"UNKCRUISE"`) instead of a literal `"UNK"`, matching the rest of the report paths.

## [0.2.0] — 2026-09-08

### Added

- **Sensor catalog** — a per-cast catalog built at stage 1 from the CNV `<Sensors>` block (#34), aggregated into `profiles.nc` (#35), rendered on the cast page as one merged variable→device→calibration table (#36), each entry carrying the sensor's verbatim `<Coefficients>` config (#39).
- **Processing provenance** — the SBE header read into an upstream-correction ledger at stage 1 (#27) and attributed in `history` with implications notes (#28); a processing-provenance report panel with the SBE conformance check and a corrections table (#32); conformance advisories raised as stage-1 warnings (#33).
- **File identity and metadata** — ACDD globals, EXPOCODE, people, and embargo on compiled files (#23); cruise identity on every file with a strict lift into compiled products (#25); per-file `tracking_id`/`source_tracking_id` that survive across stages (#37); OceanSITES `data_mode` and per-variable `processing_level` (#38).
- **Acquisition-clock tools** — `ctdcast clock`: a per-cast NMEA−System offset, a cruise verdict, a paste-ready `processing.clock` block, and a casts.html section (#29); a stage-2 applier that shifts the `time` coordinate by the found offset (#30).
- **QC visibility** on cast pages — a flag-count table, per-variable histograms, and provenance (#26).
- **LADCP** — convert LDEO IX `.mat` velocity solutions to per-cast netCDF (#19).
- **Reports** — every page driven by a section manifest (#16); a netCDF-inventory page listing variables and attributes (#17); section numbering, prose classes, and injected print CSS (#9); a cruise-map redesign with a plotters primitives layer and a golden-image gate (#12); a per-figure debug overlay (#14); sensor provenance catalog and per-profile linkage with an SBE sensors report (#21).
- **CLI** — a unified CLI/API `process` entry point (#5); `ctdcast list` for registries (#31); `--casts` / `--only` / `--all` selectors with a non-zero exit on a failed page (#11).

### Changed

- Report internals — centralized design tokens and figure encoding (#7); report CSS generated from tokens with normalised figure typography (#8); a frozen `ReportConfig` replacing mutable plots-module globals (#10); docs styling restored with a package logo (#3).
- Ruff configuration tightened to 17 rule families (`D`/`ANN` under the numpy convention plus `D417`, and `I`/`UP`/`C4`/`RET`/`PIE`/`SIM`/`NPY`/`PTH`), with numpy-style docstrings and type annotations across the public API (#41).

### Fixed

- CTD conversion and conductivity units (#18).
- Report finetuning — T–S grid, unit labels, filled maps, Leaflet (#22).
- Audit fixes on cruise-id and oxygen-saturation handling (#4).
- `zip(strict=)` correctness and sensor-variable resolver deduplication (#15).

### Removed

- Public `draw_*_fig` plotter functions — `draw_ts_diagram_fig`, `draw_stability_fig`, `draw_aux_profiles_fig`, `draw_ct_sa_sigma0_fig`, `draw_ts_updown_fig`, `draw_ts_diagram_timeseries_fig`, `draw_section_ts_histogram_fig`, `draw_section_ts_o2_fig`, `draw_sensor_diff_fig`, `draw_pressure_time_fig`, `draw_updown_diff_fig`, `draw_ladcp_bottomtrack_fig` — replaced by the internal `_make_*_b64` base64 figure encoders.

### Breaking changes

- **Output layout is now per-stage files** (#24). A cruise's CTD root holds `stage1/` … `stage3/` (one file per cast per stage) with `profiles.nc` at its top, discovered best-available. A 0.1.0 flat directory of unsuffixed per-cast files is still read — as stage 1 — so existing inputs keep working, but new output no longer lands as a single flat `nc_dir`.
- **Variable names follow CCHDO `nc_var` conventions** (#6). On disk: `temperature_1`→`ctd_temperature_1`, `salinity_1`→`ctd_salinity_1`, `oxygen_1`→`ctd_oxygen_1`, `fluorescence`→`ctd_fluor`, `turbidity`→`ctd_turbidity`, `altimeter`→`ctd_altimeter`; `oxsat_1` is no longer stored (derived on demand as `oxygen_saturation`). A reader of 0.1.0 files must map the old names.
- **CLI verb and flag changes** (#20). `ctdcast convert` is deprecated (prints a notice; use `process --stage …`); `--stations`→`--casts` and `--cast`→`--only` (old spellings warn); stage processors' `run()` returns an `int` (count written) instead of a `bool`.
- **Stage 1 keeps every CNV column** (#40). Sea-Bird-derived channels are kept under an `sbe_` prefix rather than dropped; dropping is a curated stage-2 step (`processing.trim.drop_sbe`, default all `sbe_*`); `build_profiles` takes the union of variables across casts. A 0.2.0 stage-1 file therefore has more variables than a 0.1.0 one, and some former names now sit under `sbe_`.

## [0.1.0] — 2026-08-07

First public release. Extracted and repackaged from the `odb2026` cruise repo.

### Added

- `ctdcast report` / `ctdcast run` — generate self-contained HTML reports from processed CTD netCDF files: per-cast station pages, transect section pages, cruise-wide time series pages, and an interactive Leaflet map.
- `ctdcast draft` — one-command quick look directly from raw CNV files (requires `seasenselib`).
- `ctdcast process --stage 1|2|3|profiles` — full CNV → QC'd netCDF pipeline: CNV ingest (stage 1), soak/deck trimming (stage 2), gross-range QC and calibration (stage 3), compiled profiles grid.
- `ctdcast validate` / `ctdcast init` — config file validation and interactive setup.
- TEOS-10 derived variables (Absolute Salinity, Conservative Temperature, σ₀) computed on the fly via `gsw`; never stored as approximations.
- Lettered sibling casts (`"10b"`) treated as distinct cast events throughout the pipeline and reports.
- Section ordering by config order or by distance from a key anchor cast (`key_cast:`).
- Jinja2 HTML templates with a shared `base.html` nav/CSS/footer; all output is fully self-contained (figures as base64 data URIs, Leaflet.js bundled).
- `SectionsConfig` dataclass for typed config loading; vocabulary in `config/parameters.py`.
- QARTOD QC flags with CF-1.13-compliant attributes written to netCDF output.
- `CITATION.cff` for software citation.

### Variable naming conventions

- `oxygen_1` — dissolved O₂ in µmol kg⁻¹ (CCHDO convention).
- `oxsat_1` — O₂ saturation in % (derived from `oxygen_1` or from the raw SBE 43 % channel).
- `conservative_temperature`, `absolute_salinity`, `sigma0` — TEOS-10 outputs (long CF names throughout).
