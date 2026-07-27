# ctd_report

Self-contained HTML report generator for shipboard CTD data from SeaBird SBE9/11 systems.
Produces portable HTML files — all figures embedded as base64 PNGs, no external requests needed —
for three report types: per-cast station pages, transect section pages, and a cruise-wide time
series page.

---

## Prerequisites

```bash
pip install -e .
```

Dependencies: `gsw`, `matplotlib`, `numpy`, `xarray`, `jinja2`, `pyyaml`

The CNV conversion scripts also require **seasenselib** (in-house package, not on PyPI):

```bash
pip install -e ../seasenselib    # adjust path as needed
```

---

## Workflow on the Odon de Buen

### Data location

Raw CTD data lives on the **T9 drive** (`/Volumes/T9ifmeo/odb2026/`) under:

```
/Volumes/T9ifmeo/odb2026/CTD/
    cnv/          ← .cnv files from SBE Seasave, named mixsed2_NNN.cnv
    cnv_nc/       ← per-cast netCDF files (one per .cnv), created by step 1
    profiles.nc   ← compiled 2D grid, created by step 2
```

If a cast was repeated (e.g. winch problem), the repeat file is named `mixsed2_NNN_b.cnv`.
Both scripts automatically prefer the `_b` version when both exist.

### Step 1 — Convert CNV files to netCDF

Run after each watch or batch of new casts:

```bash
python cnv_to_nc.py
```

This reads every `.cnv` in `/Volumes/T9ifmeo/odb2026/CTD/cnv/` and writes a matching `.nc`
to `cnv_nc/`. Already-converted files are skipped unless you pass `--force`.

To use different paths:

```bash
python cnv_to_nc.py --in-dir /path/to/cnv --out-dir /path/to/cnv_nc
```

### Step 2 — Build the compiled profiles file

Run after step 1 whenever you want section or time-series pages updated:

```bash
python cnv_build_profiles.py
```

This reads all `cnv_nc/mixsed2_NNN.nc` files, splits each cast at the turnaround point
(last index within 2 dbar of maximum pressure), bins both downcast and upcast onto a
common 1 dbar pressure grid, and writes a single `profiles.nc` with dimensions
`(N_PROF × pressure)`. Profile numbering: integer = downcast, integer + 0.5 = upcast.

To use different paths:

```bash
python cnv_build_profiles.py --in-dir /path/to/cnv_nc --out /path/to/profiles.nc
```

### Step 3 — Edit config.yaml

Open `config.yaml` and set the paths for your cruise:

```yaml
data:
  nc_dir:      /Volumes/T9ifmeo/odb2026/CTD/cnv_nc
  profiles_nc: /Volumes/T9ifmeo/odb2026/CTD/profiles.nc
  section_yaml: /path/to/config/ctd_sections.yaml
  gebco_nc:    /path/to/GEBCO_2025.nc   # omit for maps without bathymetry

output:
  dir: /path/to/outputs/ctd_report

generate:
  stations:   true
  sections:   true    # requires profiles.nc and ctd_sections.yaml
  timeseries: true    # requires profiles.nc
```

The `section_yaml` file (e.g. `config/ctd_sections.yaml` in the cruise repo) defines which
casts belong to each named transect. Format:

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

### Step 4 — Generate the report

```bash
python -m ctd_report config.yaml
```

Open `outputs/ctd_report/index.html` in any browser. The file is fully self-contained —
copy the entire `ctd_report/` output directory anywhere and it works offline.

### Updating mid-cruise

Steps 1 and 2 skip files that already exist (`--force` to regenerate). Step 4 also skips
existing HTML pages by default. To regenerate everything:

```bash
python cnv_to_nc.py --force
python cnv_build_profiles.py
python -m ctd_report config.yaml  # add force: true in config.yaml to rebuild HTML
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
        section_FARDWO.html
        ...
```

Each station page contains: CT profile, triple-axis T/S/σ₀ profile, T-S diagram coloured
by O₂ saturation, auxiliary profiles (O₂, fluorescence, turbidity), N²/Turner-angle
stability panels, and a cruise-track map with the cast highlighted.

---

## GEBCO bathymetry

Section maps and station maps show GEBCO 2025 bathymetry if `gebco_nc` is set in
`config.yaml`. The file is large (~8 GB); it is not bundled here. On the Odon de Buen
it is typically available on the shared analysis drive or in `../cruiseplan/data/bathymetry/`.
Maps render without bathymetry if the path is missing or left blank — not an error.
