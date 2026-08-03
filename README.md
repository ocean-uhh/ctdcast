# ctdreport

Self-contained HTML report generator for shipboard CTD and LADCP data.
Produces portable HTML files — all figures embedded as base64 PNGs, no external requests —
for three report types: per-cast station pages, transect section pages, and a cruise-wide
time series page.

Designed for use at sea where internet connectivity is limited or absent.
All output files are fully self-contained and work offline.

---

## Install

```bash
pip install -e .
```

Dependencies: `gsw`, `matplotlib`, `numpy`, `xarray`, `netcdf4`, `jinja2`, `pyyaml`, `scipy`

CTD conversion: `seasenselib` converts raw CNV files to the netCDF format expected by ctdreport (`ctdreport run --ctd`). Install separately; not on PyPI. Pre-converted netCDF files from other tools must match ctdreport's variable naming convention (see docs).

---

## Quick start

### 1. Write a config

```bash
ctdreport init                        # writes a template config.yaml
ctdreport validate config.yaml        # check paths before the first run
```

### 2. Generate

```bash
ctdreport run config.yaml             # smart update — skips up-to-date pages
ctdreport run config.yaml --force     # rebuild everything
ctdreport run config.yaml --cast 42   # rebuild one cast page
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
    cast_numbers: [[20, 35]]
```

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

Full documentation: [ctdreport docs](https://eleanorfrajka.github.io/ctdreport)
