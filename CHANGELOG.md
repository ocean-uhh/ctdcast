# Changelog

All notable changes to ctdcast are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

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
