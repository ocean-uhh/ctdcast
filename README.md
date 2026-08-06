# ctdcast

[![Tests](https://github.com/eleanorfrajka/ctdcast/actions/workflows/tests.yml/badge.svg)](https://github.com/eleanorfrajka/ctdcast/actions/workflows/tests.yml)
[![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%20–%203.13-blue?logo=python&logoColor=white)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://opensource.org/licenses/MIT)
[![Docs](https://img.shields.io/badge/docs-gh--pages-blue)](https://eleanorfrajka.github.io/ctdcast/)

Self-contained HTML report generator for shipboard CTD and LADCP data.
Produces portable HTML files — all figures embedded as base64 PNGs, no external requests —
for three report types: per-cast station pages, transect section pages, and a cruise-wide
time series page.

Designed for use at sea where internet connectivity is limited or absent.
All output files are fully self-contained and work offline.

---

## Install

```bash
git clone https://github.com/eleanorfrajka/ctdcast
cd ctdcast
python -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
pip install -e .
```

Dependencies: `gsw`, `matplotlib`, `numpy`, `xarray`, `netcdf4`, `jinja2`, `pyyaml`, `scipy`

CTD conversion: `seasenselib` converts raw CNV files to the netCDF format expected by ctdcast (`ctdcast draft` or `ctdcast run --ctd`). Install with `pip install seasenselib`. Pre-converted netCDF files from other tools must match ctdcast's variable naming convention (see docs).

To verify the installation, run the bundled demo against the committed fixture casts:

```bash
ctdcast run config_demo.yaml   # writes demo_report/index.html
```

For a full walkthrough see the [Quickstart guide](https://eleanorfrajka.github.io/ctdcast/quickstart.html).

---

## Quick start

### Quick look (no config file needed)

Raw CNV files fresh off the instrument? One command gives you station pages + index + map:

```bash
ctdcast draft /path/to/cnv/           # generates ./ctd_draft/index.html
ctdcast draft /path/to/cnv/ out/ --cruise odb2026   # with cruise ID
ctdcast draft /path/to/cnv/ --dry-run               # preview what would happen
```

Requires `seasenselib` for CNV conversion (`pip install seasenselib`).

### Full workflow (with config)

For sections, time series, and LADCP panels you need a `config.yaml`:

#### 1. Write a config

```bash
ctdcast init                        # writes a template config.yaml
ctdcast init --interactive          # guided setup: prompts for paths and
                                      # auto-detects sections/timeseries from profiles.nc
ctdcast validate config.yaml        # check paths before the first run
```

#### 2. Generate

```bash
ctdcast run config.yaml             # smart update — skips up-to-date pages
ctdcast run config.yaml --force     # rebuild everything
ctdcast run config.yaml --cast 42   # rebuild one cast page
```

Open `<output.dir>/index.html` in any browser.

---

## Input data

| File | Description |
|---|---|
| `cnv_nc/*.nc` | Per-cast netCDF files, one per CTD cast |
| `profiles.nc` | Compiled profiles on a 1 dbar grid |
| `ctd_sections.yaml` | Section definitions — which casts belong to each transect |

### ctd_sections.yaml format

```yaml
sections:
  KTout:
    description: "Kögur Transect outflow"
    color: "#e41a1c"
    cast_numbers: [[1, 12], 15]   # ranges and/or individual cast numbers
  FARDWO:
    description: "FARDWO mooring array"
    color: "#377eb8"
    cast_numbers: [[20, 35], "22b"]   # add "NNNb" to include a lettered sibling cast
```

Cast numbers are kept in the order written. An integer or range selects the
plain casts; a lettered sibling event (from a ``NNNb`` / ``NNN_b`` file) is a
distinct cast and must be named explicitly as a quoted ``"NNNb"`` string.

---

## Output structure

```
<output.dir>/
    index.html              front page — map + stats + navigation
    station_index.html      table of all casts (latest first)
    sections.html           section cards with links
    timeseries.html         T, S, O₂ vs time × pressure
    stations/
        cast_001.html
        cast_002.html
        ...
    sections/
        section_KTout.html
        ...
```

Each station page shows: CT profile, T/S/σ₀ triple-axis profile, T-S diagram coloured by
O₂ saturation, auxiliary profiles (O₂, fluorescence, turbidity), N²/Turner-angle stability
panels, and a cruise-track map with the cast highlighted.

---

## GEBCO bathymetry

Maps show GEBCO 2025 bathymetry when `gebco_nc` is set in `config.yaml`.
The file (~8 GB) is not bundled. Maps render without bathymetry if the path is missing — not an error.

---

## Documentation

Full documentation: [eleanorfrajka.github.io/ctdcast](https://eleanorfrajka.github.io/ctdcast/)
