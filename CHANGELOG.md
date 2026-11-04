# Changelog

All notable changes to ctdcast are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Stage 3 runs the steps listed in `data_processing.steps`, in that order.** Each entry is one step and its parameters, as Sea-Bird names its modules; a step may repeat. `wildedit`, `alignctd` and `celltm` are applied; A step stage 3 does not apply is refused unless `data_processing.allow_unapplied: true`, which skips it with a warning and a `history` note; `split` and `binavg` in the stage-3 steps are refused (they belong in a product). One table, `processors.steps.STEPS`, lists the steps, how each is applied and checked. The stage-3 file records the order the steps ran in (`data_processing_steps`), and the cast page's corrections table follows it.
- **Filter, Window Filter and Loop Edit at stage 3** (`processors.filtering`, `processors.editing`), with `seabirdscientific`: `filter` (Sea-Bird's low-pass filter, forward and backward; Filter A and B are two steps), `window_filter` (boxcar, cosine, triangle, gaussian, median), `loopedit` (whole scans: reversals, too slow, surface soak). Filters change values and record each filter on the variable (`filters`), stepping over values Wild Edit marked; Loop Edit keeps every value and writes `loop_edit_flag` plus QARTOD 4 in each `_qc`, which later Wild Edit, Window Filter and Bin Average leave out. On OdB cast 050, `.hex` processed with the steps from its own CNV header now matches the CNV to the CNV's rounding: conductivity identical, salinity 0.00004, pressure 0.0003 dbar. Loop Edit's `deck_pressure: true` follows `seabirdscientific` (offset by the first scan); SBE Data Processing matched no offset on OdB's casts, which `deck_pressure: 0` reproduces.
- Cast page: *Corrections applied by ctdcast* lists Filter (one row per filter, the 0.15 s pressure filter ticked against the SBE manual), Window Filter and Loop Edit, in the order they ran, with a caption on Loop Edit's deck-pressure offset when it was used.
- **Products** (`data_processing.products`, `processors.products`): files made from the stage-3 data by further steps, each `{name, steps}`, written to `<ctd_root>/products/<name>/<cast>_<name>.nc`; `split` (one leg) and `binavg` (Bin Average by decibars, seconds or scans, with `seabirdscientific`; a value flagged 4 or 9 leaves only its own bin, salinity re-derived) are product-only. `ctdcast inspect` puts a CNV's Split and Bin Average into products. On OdB cast 004, the 1 dbar product from `.hex` matches the cruise's `cnv_cal` CNV with median differences of 0.00001 in temperature, conductivity and salinity once `cnv_cal`'s conductivity slopes are given as `slope_offset`.
- **Wild Edit at stage 3** (`ctdcast.processors.editing`): marks values far from their block of scans QARTOD 4 in `{var}_qc`, with `seabirdscientific`'s `wild_edit`; the values are kept, and the parameters, the number marked and how many scans `exclude_flagged` left out are recorded on each variable. On OdB cast 050 every value ctdcast marks is one OdB's CNV marks too. OdB's CNV marks more: where a channel sits at one or two A/D levels for a whole block (oxygen, fluorescence, altimeter near the surface), SBE Data Processing marks the entire block when `mindelta` is 0, and `seabirdscientific` marks only the values off the block's majority level.
- **Per-sensor conductivity slope and offset**, `data_processing.slope_offset.conductivity_<N>: {slope:, offset:}` (bare, or `default:`/`ranges:` for a sensor swapped mid-cruise), applied first, as Sea-Bird applies them at conversion; salinity is re-derived.
- **`ctdcast inspect <file>.cnv`** prints the SBE Data Processing steps recorded in a CNV header as a `data_processing:` block, in the order they ran, ready to paste; `-o page.html` also writes a page with a copy button and each module's header fields, time and version. `config.sbe_steps`, `reports.sbe_processing`.
- **A conductivity advanced twice is flagged**: an Align CTD advance of a conductivity the deck unit had already advanced in hardware shows as a `# check:` line in that block, an amber row on the inspect page, an amber ✗ row and an advisory on the cast page's *Corrections applied before ctdcast*, and a stage-1 warning (`config.cnv_header.stacked_advances`). OdB's `cnv_24Hz` CNVs advance the primary conductivity 0.073 s on top of the deck unit's 0.073 s.
- `analysis.sbe_compare` and `plotters.sbe_compare`: compare a stage file with a Sea-Bird CNV made from the same `.hex`, scan by scan — differences where neither side flags a scan, and Wild Edit's per-value marks and Loop Edit's scan marks kept apart.
- **`ctdcast fit`: suggest alignment and cell thermal mass parameters from a cruise's casts.** Reads every native-rate stage-2 cast, scores each conductivity line's salinity-spike (alignment) and down/up-mismatch (cell thermal mass) costs, and writes the cost surfaces, per-block fits and a per-cast sensor-configuration fingerprint to `<ctd_root>/fits.nc`. `ctdcast report` draws a *T/S corrections* page (`corrections_ts.html`) from it: separate alignment and cell-thermal-mass tables (the recommended (α, τ) in bold — the point within `fit.ctm_tolerance` of the cost minimum closest to Sea-Bird's default, 2% by default — with the one-parameter fits as diagnostics), per-cast and per-block figures, α/τ and advance histograms, and a copyable `data_processing:` block. A green dashed line marks where the sensor configuration changed. New config block `fit` (`ctm_pmin`, `gradient`, `align_pmin`, `min_speed`, `gap_seconds`, `ctm_tolerance`, `block`).
- **Copyable YAML snippet boxes**, vendored (`reports/_vendored/templates/_snippet.html`: the `yaml_snippet` macro with a Copy button, clipboard with an `execCommand` fallback for offline `file://` pages). Used on the corrections page's suggested `data_processing:` block and the `casts.html` acquisition-clock suggestion.
- **Stage 3 at the native scan rate: alignment, cell thermal mass and SBE 43 oxygen.** New `alignctd` (seconds per channel: conductivity as a residual on the deck unit's advance, the SBE 43 voltage) and `celltm` (`alpha`, `tau`) steps in `data_processing.steps`, each a bare value or a cruise `default` plus per-cast `ranges`, applied with Sea-Bird's `seabirdscientific` (`align_ctd`, `cell_thermal_mass`). On a cast that carries the SBE 43 voltage and no converted oxygen (a `.hex` cast), stage 3 derives `ctd_oxygen` with the tau correction (`data_processing.oxygen.tau_window_seconds`, default 2 s) and the hysteresis correction of Sea-Bird Application Note 64-3. These two are computed by ctdcast, not by `seabirdscientific` 3.1.1: its dV/dt fit takes about 11 s per deep cast (ctdcast's takes milliseconds and gives the same result), and its hysteresis feeds back the corrected previous voltage where the note uses the uncorrected one. Each derived variable records this in `oxygen_hysteresis_method`; the plan is to switch back when `seabirdscientific` changes. Every step records its parameters on the variable and in `history`; values shifted past a cast's ends become NaN, flagged 9, and no scan is removed. A binned cast, or one Sea-Bird already corrected the same way, skips these steps with a warning and still gets the slope, salinity and QC. On OdB casts 011/012 (from `.hex`), CTM with Sea-Bird's α = 0.03, τ = 7 s brings the thermocline salinity difference from Sea-Bird's processing down from 0.008–0.013 to 0.0003–0.0004, and the derived oxygen matches Sea-Bird's to 0.06–0.08 µmol/kg (median).
- `profiles.nc` carries each correction parameter as the variable's attribute when every cast agrees, and as a per-profile `<var>_<parameter>(N_PROF)` variable when it differs.
- Cast page: the processing-provenance panel lists *Corrections applied by ctdcast* after Sea-Bird's, in the order applied, with the same columns and SBE references (cell thermal mass against (0.03, 7); conductivity alignment by its total advance, deck unit plus ctdcast, against 0.073 s).
- Sensors table: every catalogued sensor links to a variable. The transmissometer links to `transmissometer`; a sensor ctdcast does not convert (pH, a user polynomial) links to its raw voltage (`volt<N>_raw`) on a `.hex` cast.
- `ctdcast report` with nothing processed, and stages 2–3 with no stage root, now say what to run.
- Stage 1 records a CNV's `# interval` as `sample_interval_kind` and `sample_interval_seconds` (or `sample_interval_dbar`); `config.cnv_header.parse_sample_interval`, `applied_sbe_corrections`, `raw_metadata_block`; `processors.qc.QARTOD_MISSING`.

- **Raw SBE 911plus `.hex` input at stage 1.** Set `data.hex_dir` (and `data.ctd_raw_format: hex` when `cnv_dir` is also set) and stage 1 reads each `.hex` with the `.xmlcon` beside it, at the native 24 Hz, using Sea-Bird's `seabirdscientific` toolkit: temperature, conductivity (mS/cm), Digiquartz pressure, fluorescence, turbidity, altimeter and beam transmission, each with the `.xmlcon` coefficients, Slope and Offset (conductivity's in S/m, before the ×10). Every voltage channel is kept as raw volts (`volt<N>_raw`, an SBE 43 as `oxygen_raw_<N>`), with a quick-look `sbe_oxygen_<N>`, and the deck unit's pump, bottom-contact, bottle-confirm and modem bits per scan. Time is the header's NMEA UTC plus one scan interval per scan, with the PC upload time as a warned fallback; when a `.bl` bottle log sits beside the `.hex`, its fire times are checked against the scan clock and the result recorded (`time_bottle_log_check`). Bottle logs are optional. Practical salinity is derived from the converted C/T/P. The sensor catalog comes from the `.xmlcon`. On OdB cast 011 temperature agrees with Sea-Bird's processing to 0.00001 °C (median, 1 dbar); conductivity agrees where the temperature gradient is small, and differs in the thermocline by Sea-Bird's cell thermal mass correction, which stage 3 now applies (a `celltm` step).
- `readers.xmlcon` (parse an `.xmlcon`; coefficient objects for seabirdscientific; sensor records in the CNV `<Sensors>` shape) and `readers.hex` (`read_hex`, `time_anchor`, `check_bottle_log`).
- Cast page header: a *Raw input* line names the file(s) the cast entered processing from and their format (`MIXSED2_012.hex + MIXSED2_012.XMLCON (raw SBE 911plus .hex)` or `mixsed2_012.cnv (Sea-Bird CNV)`); *Source* still names the netCDF the page was drawn from.
- Cast page: without LADCP, the CT/SA/σ₀ profile keeps the two-column layout with the LADCP column left empty, so it is the same width as on a cruise with LADCP and drawn at its slot width (it was 7.0 in in a 5.4 in slot, with shrunken text). `ReportConfig.profile_figsize` and `display.profile_figsize` no longer affect it.
- Cast page: the stability panel (N², Turner angle) is not drawn for a native-rate cast (unbinned `.hex` scans); an amber note says why ("applicable but not computed: on native-rate data …").
- Cast page header: a *Sampling* line gives the cast's rate: `24 Hz (native, unbinned)` for a `.hex` cast, and for a CNV what its `# interval` line says (`24 Hz (CNV, 0.0416667 s interval)`, `1 s interval (CNV)`, `1 dbar bins (CNV)`).
- `scripts/compare_hex_cnv.py`: compare a ctdcast file from the `.hex` with the cast's Sea-Bird CNV, scan by scan (a stage file against a CNV at the same rate) or bin by bin (a product against a binned CNV, matched on pressure), as a table and optionally a figure.
- `StagePaths.hex_dir`, `StagePaths.ctd_raw_format`, `StagePaths.ctd_raw_dir`; `process()` accepts `hex_dir=` and `ctd_raw_format=`.

### Changed

- **Config files are read strictly** (`config.loader.load_config` / `load_yaml`, used by every command and for the sensor, platform and institution tables): a key repeated in one block (two `data_processing:` blocks, or two steps written as one list item) is an error naming the key, both lines and what to change, where YAML would silently keep only the second. A YAML syntax error names its line. Commands print `Config error: …` and exit 1 instead of a traceback.
- Stage 2 no longer writes a `_qc` flag on the deck unit's status words (`pump_status`, `bottom_contact_status`, `bottle_confirm_status`, `modem_status`, `data_integrity`) or on unconverted raw voltages (`volt<N>_raw`); `oxygen_raw_<N>` keeps its flag. `config.parameters.STATUS_CHANNELS`, `is_unflagged_channel`.
- A scan whose pressure is flagged fail or missing (a Wild Edit mark, a gross-range fail) is left out of Split, Bin Average and `profiles.nc`: it no longer sets the bottom of the cast, a bin or the grid (`processors.qc.usable_pressure`).
- SBE 43 oxygen: a voltage, temperature, conductivity or pressure value Wild Edit marked is bridged from its neighbours before the tau and hysteresis corrections, so it no longer spreads into neighbouring oxygen; the oxygen at that scan is flagged 4 (`oxygen_marked_inputs_bridged`).
- Products re-derive salinity when a step changed conductivity, temperature or pressure, and their filters step over the values stage 3's Wild Edit marked.
- `loopedit: surface_soak: false` works (it failed inside `seabirdscientific`); Wild Edit after Loop Edit no longer counts Loop Edit's scans among its marks; `binavg: exclude_flagged: false` is refused (`ctdcast inspect` writes a `# check:` line for a CNV whose Bin Average kept bad scans).
- Config files are read and written as UTF-8 on every platform (`ctdcast init`'s output, `validate`'s duplicate-key scan; every other read goes through `load_config`). On Windows a config with an accented name or a `—` failed to load.
- Cast page: the T–S diagram is drawn without oxygen too, in one colour and with no colour bar (it was left out).
- `config.cnv_header`: the channel fields of an SBE Data Processing step (Align CTD's `adv`, Filter's A/B groups, Window Filter's `action` lines) are read by one function each, shared by the conformance ticks, the advisories, the stacked-advance check and `ctdcast inspect`; no change in output.
- `profiles.nc` leaves out only values flagged fail (4) or missing (9) before binning, as a product's Bin Average does; suspect (3) values are kept (they were left out).
- **Config layout split by what each block does** (`config.layout.processing_view`): `preferred_sensor: {tc, oxygen}`, `clock`, `qc` and `fit` at the top level, and `data_processing:` (`slope_offset`, `oxygen`, `steps`) for what stage 3 applies; `processing:` keeps `trim` and `profiles_dbar`. Preferred-sensor ranges take `value:`, as every other range does. `ctdcast fit` and `ctdcast clock` print blocks in the new layout; `ctdcast init` writes it, with the SBE Data Processing manual's 911plus steps commented out.
- Stage 1, CNV input: an SBE 43 voltage takes its suffix from the SBE column (`sbeox0V` is `oxygen_raw_1`), not seasenselib's column order, so the CNV and `.hex` paths name it the same.
- **Vendored report tables (all family packages at re-vendor): column headers are centered, and the units sub-row now carries the header's accent background** rather than muted grey text on white, so it reads as a second header row.
- **Stage 3 runs QC last**, on the corrected values (it ran first, before the conductivity slope). On a cruise that uses `calibration.conductivity_slope`, flags now judge the slope-corrected conductivity and the re-derived salinity.
- `seabirdscientific>=3.1,<4` is a core dependency.
- A sensor role whose measured variable is absent links its raw signal instead (`config.sensors.ROLE_RAW_VARIABLE`: an SBE 43 to `oxygen_raw_<N>`), rather than warning that the reader dropped it.

### Deprecated

- `processing.preferred_pair` / `preferred_oxygen`, `processing.clock`, `processing.qc` and `processing.calibration.conductivity_slope` are read with a `DeprecationWarning` until the next release; use `preferred_sensor.tc` / `.oxygen`, `clock`, `qc` and the per-sensor `data_processing.slope_offset` (the old single slope applies to both sensors, offset 0). `use:` in a preferred-sensor range is read with a warning; use `value:`.

---

## [0.4.1] — 2026-11-01

### Added

- **Interactive cast map on `casts.html`** — the cruise map is now the live Leaflet map (the vendored `track_map` layer): one marker per cast and one polyline per section, each hover-linked to its table row (rows carry `data-track-id`), with click-through to the station/section page. The static cruise-map PNG stays as the print / no-JavaScript fallback. Land coastline needs the optional `[maps]` extra (`pip install ctdcast[maps]`, cartopy); without it the map draws tracks over the lat/lon graticule and the build warns. The GEBCO bathymetry map (`leaflet.html`) is unchanged and still linked, until bathymetry moves into the shared map layer.

- **SBE sensors page: preferred sensors and calibration.** A *Preferred sensors* table gives, per run of casts, the T/C pair and oxygen sensor each dual-sensor cast uses (`primary` / `secondary` and the chosen serials, `not declared` when the cruise config gives no `preferred_pair` / `preferred_oxygen`; an undeclared dual-oxygen cast reads `line 1 shown (not declared)`; a run with an undeclared choice is amber, with the rule in the caption; a cast compiled from a stage-1/2 file reads `not resolved yet (stage N)` and one with no sensor catalog `no sensor catalog`). The sensor inventory gains *Slope* and *Offset* columns — the datcnv correction of each temperature, conductivity and pressure sensor — with an amber row and the value in bold where Slope ≠ 1 or Offset ≠ 0.
- **Sensor variables moved to the SBE sensors page.** The catalog (`SENSOR_*`), linkage (`sensor_<role>`) and channel (`sensor_channel_<role>`) tables now close the SBE sensors page, under a short explanation of what each family carries. The `profiles.nc` inventory page keeps one *Sensors* section with that explanation and a link to them; `ctdcast inspect` on a single file, which has no sensors page, still shows the tables. `reports.dataset.sensor_variable_tables` builds them for both pages.
- **Cast page: preferred-sensor line.** A dual-sensor cast's header shows its preferred T/C pair and oxygen, e.g. `T/C secondary (s/n 6000 / 3120), O₂ primary (s/n 0707)`, `not declared`, or `not resolved yet (stage N file)` for a cast built before stage 3. The oxygen-saturation axis label on the auxiliary-profiles and T–S figures names the line a dual-oxygen cast actually drew: `· secondary`, `· line 1, not declared`, or `· line 1 (secondary not available)` when the declared line could not be derived.
- `config.sensors.is_sensor_catalog_var` — the one `SENSOR_*` catalog-entry test (excluding `_qc` companions), used by stage 2, the per-cast catalog reader and the report pages; `reports.design.is_sensor` delegates to it.
- `config.parameters.color_limit_override` — looks up a `vmin` / `vmax` override under the drawn name, the registry name, or the other form (`ctd_oxygen` ↔ `ctd_oxygen_1`; a line-2 name has none, so a composite override never lands on line 2); section, time-series and cruise-summary pages share it.

### Changed

- Section, time-series and cruise-summary pages draw oxygen from the preferred-oxygen composite `ctd_oxygen` (`SECTION_BIOGEO_VARS` now names it, not `ctd_oxygen_1`), so a cruise with declared dual oxygen shows the chosen line rather than always line 1. A profile with no composite (an undeclared dual-oxygen cast compiled alongside casts that have one) is drawn from `ctd_oxygen_1` by the new `analysis.derive.fill_oxygen_composite`, which records the filled casts in the drawn variable's `filled_from_ctd_oxygen_1` attribute; `profiles.nc` is unchanged. Colour-limit overrides keyed by either name still apply.
- The cast page's QC value-distribution histogram draws the kept values of `ctd_oxygen` (single-sensor or preferred composite) in the oxygen colour, as it already did for `ctd_oxygen_1`, instead of the default blue.
- The SBE sensors page tables (and two `profiles_inventory.html` tables) render their headings through the vendored `thead` macro and are click-to-sort; section numbers follow the sections shown. The page's roles are selected by inclusion (a known role, or one with a `sensor_channel_<role>` twin) rather than by excluding suffixes, and a `SENSOR_*_qc` companion is no longer read as a device.
- `ctdcast.plotters.plots` is split by subject into `ctdcast.plotters.maps`, `profiles`, `sections`, `timeseries` and `ladcp`; helpers shared by more than one module move to `ctdcast.plotters.primitives`. Four helpers the report layer uses are now public: `primitives.hide_outer_spines`, `primitives.nice_colorbar_bounds`, `maps.square_map_limits`, `maps.GEBCO_RENDER_PAD`. Draw functions with a fixed width take `width_in` (default: the previous width; height follows at a fixed aspect); on the cast page each fixed-slot figure is drawn at its slot's width, named once per panel. No figure output changes. The per-figure `source:` caption now names the new module (e.g. `ctdcast/plotters/maps.py:draw_all_sections_map_fig`).
- LADCP report panels read each cast once: `plotters.ladcp.ladcp_section_grid` and `ladcp_overview_grid` load, grid and scale the data once per page, shared by the U and V panels (section and time-series pages previously read every `.mat` file and repeated the GEBCO lookup twice). The cruise LADCP overview is drawn by the new `draw_ladcp_overview_fig`, so its `source:` caption names a draw function; `draw_ladcp_section_fig` takes an optional `grid=`. Same pixels.
- Section, time-series and cruise-summary pages draw their fixed-width figures (section and location maps, T–S diagrams and histograms, the all-sections maps) at the width of the slot they are shown in; each page names those slots once. No figure output changes.
- `plotters.maps.draw_section_map_fig` and `plotters.timeseries.draw_timeseries_fig` take the figure width as `width_in`, like the other draw functions.
- Docs: the `sensors` block example (`config_yaml.rst` and `config_demo.yaml`) writes the serial alias as `"FLNTURTD-3508": "3508"` — the value is the canonical serial and becomes the catalog entry name — and adds `model_source: operator` to the FLNTU overrides, so a combined FLNTU(RT)D yields the short `SENSOR_FLUOROMETER_3508` / `SENSOR_TURBIDITY_3508` names rather than the long `…_FLNTURTD_3508` form.

### Fixed

- Cruise-overview panels in reports built with `ctdcast report` / `ctdcast run` were drawn 12 in wide and shown in the 9 in full-width slot, so their labels appeared at 75 % of the size of every other figure. Overview panels (CTD and LADCP) are now drawn at the slot width, keeping the configured aspect ratio, and the CLI falls back to the library defaults for `overview_figsize` / `profile_figsize` instead of its own `[12, 4]` / `[7, 10]`. The default overview shape is now 9 × 3 in (3:1) in `ReportConfig`, for API- and CLI-built reports alike (API-built panels were 9 × 4.5 in); `display: overview_figsize` still overrides the shape.

### Deprecated

- `ctdcast.plotters.plots` re-exports the public figure builders from the new modules and emits a `DeprecationWarning` on import; it is removed in 0.7.0.
- `draw_section_map_fig(fig_w=)` and `draw_timeseries_fig(figw=)` are deprecated aliases of `width_in=` and warn; passing both raises `TypeError`; removed in 0.7.0.

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
