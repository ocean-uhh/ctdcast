# Changelog

All notable changes to ctdcast are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Interactive cast map on `casts.html`** — the cruise map is now the live Leaflet map (the vendored `track_map` layer): one marker per cast and one polyline per section, each hover-linked to its table row (rows carry `data-track-id`), with click-through to the station/section page. The static cruise-map PNG stays as the print / no-JavaScript fallback. Land coastline needs the optional `[maps]` extra (`pip install ctdcast[maps]`, cartopy); without it the map draws tracks over the lat/lon graticule and the build warns. The GEBCO bathymetry map (`leaflet.html`) is unchanged and still linked, until bathymetry moves into the shared map layer.

### Changed

- `ctdcast.plotters.plots` is split by subject into `ctdcast.plotters.maps`, `profiles`, `sections`, `timeseries` and `ladcp`; helpers shared by more than one module move to `ctdcast.plotters.primitives`. Four helpers the report layer uses are now public: `primitives.hide_outer_spines`, `primitives.nice_colorbar_bounds`, `maps.square_map_limits`, `maps.GEBCO_RENDER_PAD`. Draw functions with a fixed width take `width_in` (default: the previous width; height follows at a fixed aspect); on the cast page each fixed-slot figure is drawn at its slot's width, named once per panel. No figure output changes. The per-figure `source:` caption now names the new module (e.g. `ctdcast/plotters/maps.py:draw_all_sections_map_fig`).
- LADCP report panels read each cast once: `plotters.ladcp.ladcp_section_grid` and `ladcp_overview_grid` load, grid and scale the data once per page, shared by the U and V panels (section and time-series pages previously read every `.mat` file and repeated the GEBCO lookup twice). The cruise LADCP overview is drawn by the new `draw_ladcp_overview_fig`, so its `source:` caption names a draw function; `draw_ladcp_section_fig` takes an optional `grid=`. Same pixels.

### Deprecated

- `ctdcast.plotters.plots` re-exports the public figure builders from the new modules and emits a `DeprecationWarning` on import; it is removed in 0.7.0.

## [0.4.0] — 2026-10-23

### Added

- **Per-figure `source:` caption** — each report figure can carry a line naming the draw function that produced it (`<module>.py:<function>`), for provenance. The mechanism is vendored (`reports/_vendored/figure_png.source_for`/`source_of`, gated by a default-off `SHOW_FIGURE_SOURCE` flag); ctdcast turns it on in its owned `reports/design.py` (`FIGURE_SOURCE = True`), the same override pattern as the colormaps. With the flag off a page is visually identical to before; the stylesheet gains one unused `.fig-source` rule (no element matches it).
- **Shared units layer, vendored** — `reports/_vendored/units_tables` holds the family units data (the canonical CF/UDUNITS spelling per CF `standard_name`, the accepted reader-spelling aliases with their conversion factors, and the plot labels); `reports/_vendored/units` holds the machinery over it — `resolve_units` (reader spelling → canonical + factor), `merge_tables` (a package's view over the defaults), and `format_units` (the display label, `mS cm-1` → `mS/cm`, `rad2 s-2` → `rad²/s²`, `degree_Celsius` → `°C`, dimensionless turbidity/salinity → `NTU`/`PSU`). ctdcast's own view is `config.unit_tables.TABLES`, with `unit_label` deriving every plot and table label; a package adds spellings/labels through its override dicts (`CANONICAL_UNIT_OVERRIDES` / `UNIT_ALIAS_EXTRAS` / `UNIT_LABEL_OVERRIDES`), never by editing the shared tables.
- **Canonical units at every write boundary** — `processors.units.to_canonical_units` rewrites each registered variable's `units` to its canonical spelling as the writer runs: a recognised non-canonical spelling is rewritten (and its values converted when the factor is not 1, e.g. `S/m` → `mS cm-1` ×10, integer packing dropped), a missing unit is filled from the registry, and a present-but-unrecognised spelling raises `UnitsError` and aborts the run rather than being silently stamped over. No per-variable conversion-provenance attribute is written (a factor ≠ 1 is logged).
- **Vendored `properties_table` macro** for key/value tables (`reports/_vendored/templates/_nc_tables.html`); the cast page's File provenance and Time coordinate tables render through it, so their shape matches the inventory tables.
- **Vendored QC tables** — the cast-page QC thresholds and flag-count tables are built by `reports/_vendored/nc_tables.qc_threshold_rows` / `qc_flag_rows` and rendered by the `qc_thresholds_table` / `qc_counts_table` macros, driven from each `{var}_qc` companion's own `flag_values` / `flag_meanings` (one column per declared flag, in declared order). Flag labels and colours are keyed by the meaning token (`reports/_vendored/design_tokens.QC_FLAG_LABELS` / `QC_FLAG_COLORS`, covering the QARTOD and OceanSITES vocabularies, derived from `QC_COLORS`), so a flag reads the same across conventions. The `original → name` rename also shows inline in each variable row's Variable cell (the standalone renaming table stays).
- **Plane-angle `degree` in the shared units table** — `degrees` and the display form `°` now canonicalise to the UDUNITS plane angle `degree` (for attitude channels such as glider heading/pitch/glide-angle, used by the sibling packages). The ambiguous `deg` stays scoped to latitude/longitude (`degrees_north` / `degrees_east`) and is refused on any other quantity.

### Changed

- LADCP velocity (`U`, `V`) axis labels change `m s⁻¹` → `m/s` and squared buoyancy frequency (`N2`) `s⁻²` → `rad²/s²`, now derived by the shared units rule from each variable's CF `units`. Figures labelling these three change by the label text only.
- Coverage gate floor raised from 79% to 84% (measured total is 85%).
- The vendored report layer is now self-contained: the hash manifest and the drift-check gate moved into `reports/_vendored/` as `MANIFEST.txt` and `check.py` (were `scripts/VENDORED.txt` and `scripts/check_vendored.py`), so a consumer vendors the directory and nothing else. Manifest paths are now directory-relative, and `check.py` locates its own directory, so both files are byte-identical across ctdcast, oceanarray and glidertest. Run the gate with `python -m ctdcast.reports._vendored.check`.
- The bundled Leaflet assets (`leaflet.min.js`, `leaflet.min.css`) and their `LICENSE` moved into `reports/_vendored/leaflet/`, shared byte-identical across the sibling packages, so the ~160 KB library is bundled once; the cruise map reads them there. No change to generated output.
- The cruise map no longer falls back to a CDN: a missing bundled Leaflet asset now raises rather than fetching from jsdelivr/cdnjs or emitting an empty map, so the offline-at-sea guarantee holds at build time instead of failing silently at view time.
- **Source-name provenance attribute renamed to `original_name`** — the CNV path (consolidated from seasenselib's `cnv_original_name`) and the LADCP reader (was `source_variable`) now both record a variable's raw source name as `original_name`, one family-shared spelling. Files written before 0.4.0 still read: the inventory rename table and `readers.metadata.source_to_canonical` fall back to the old attribute names. New stage files no longer carry `cnv_original_name` / `source_variable`.
- **Python support is 3.11–3.14** (3.10 dropped; the 3.14 cell is tested but allowed to fail while a dependency wheel may lag). `requires-python` is now `>=3.11`, ruff `target-version` is `py311`, and `datetime.timezone.utc` is written `datetime.UTC`.
- Stage 1 drops the CNV reader's oxygen `standard_name` when it reclassifies an oxygen channel (to the per-mass measurement, `% saturation`, or raw voltage): the raw channel's name no longer fits the reclassified variable, so the writer assigns the correct one from the registry (`ctd_oxygen_N` → moles-per-mass; the saturation/voltage channels carry none). This keeps a reader's metadata — which can differ between seasenselib releases — from driving unit canonicalisation.

### Deprecated

- `config.sensors.sanitize_serial` is a deprecated alias of `serial_slug` (the filename/variable-safe serial form) and emits a `DeprecationWarning`; it is removed in 0.5.0. The family uses one spelling-neutral name rather than the British/American `sanitize`/`sanitise` variant.

### Fixed

- `time_coverage_end` was written from the per-profile **start** times, so a compiled file's stated end was the start of the last profile, not the last data timestamp (on the demo cruise, ~19 minutes short). `coverage_attrs`/`cruise_global_attrs` now take start and end times separately: `time_coverage_start` is the earliest start and `time_coverage_end` the latest end, each from its own variable (`time_start`/`time_end`); the LADCP product, with one time per profile, uses it for both. The value of `time_coverage_end` in every regenerated stage file changes accordingly.

### Removed

- Public `reports.qc_summary` and `reports.qc_thresholds` — the cast-page QC flag-count and thresholds tables are now built by the vendored `reports/_vendored/nc_tables.qc_flag_rows` / `qc_threshold_rows` and rendered by the `qc_counts_table` / `qc_thresholds_table` macros. A caller importing `from ctdcast.reports import qc_summary` / `qc_thresholds` (both public in 0.3.0) must switch to the vendored builders.
- **`label_units`** — the registry column and the per-variable netCDF attribute are gone. The display unit is derived from the CF `units` string by `config.unit_tables.unit_label`, so there is one source of display spelling. New stage files no longer carry `label_units`; a file written before 0.4.0 keeps its copy and readers ignore it.

### Breaking changes

- Output attribute change: stage files no longer carry `label_units` (derived from `units` now) or `cnv_original_name` / `source_variable` (recorded as `original_name`). A downstream reader of those attribute names must read `original_name` (with the old names as a fallback) and derive the display unit from `units`. Files written before 0.4.0 are still read.
- Python 3.10 is no longer supported (`requires-python = ">=3.11"`).
- `label_units` was dropped from `config.parameters.VARIABLES`; a caller reading it from the registry must use `config.unit_tables.unit_label(units, standard_name)`.

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
