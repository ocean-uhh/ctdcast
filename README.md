# oceancast

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

---

## Quick start

### 1. Edit config.yaml

```yaml
data:
  nc_dir:       /path/to/cnv_nc           # per-cast netCDF files
  profiles_nc:  /path/to/profiles.nc      # compiled 2D profiles
  section_yaml: /path/to/ctd_sections.yaml
  gebco_nc:     /path/to/GEBCO_2025.nc    # optional; omit for maps without bathymetry

output:
  dir: /path/to/output

generate:
  stations:   true
  sections:   true    # requires profiles.nc and ctd_sections.yaml
  timeseries: true    # requires profiles.nc
```

### 2. Generate

```bash
oceancast config.yaml
```

Or to force regeneration of all pages:

```bash
oceancast config.yaml --force
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

Full documentation: [oceancast docs](https://eleanorfrajka.github.io/ctd_report)
