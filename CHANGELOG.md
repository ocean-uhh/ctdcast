# Changelog

All notable changes to ctdcast are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

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
