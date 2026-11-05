# ctdcast

[![PyPI](https://img.shields.io/pypi/v/ctdcast.svg)](https://pypi.org/project/ctdcast/)
[![Python versions](https://img.shields.io/pypi/pyversions/ctdcast.svg)](https://pypi.org/project/ctdcast/)
[![License: MIT](https://img.shields.io/pypi/l/ctdcast.svg)](https://github.com/ocean-uhh/ctdcast/blob/main/LICENSE)
[![Tests](https://github.com/ocean-uhh/ctdcast/actions/workflows/tests.yml/badge.svg)](https://github.com/ocean-uhh/ctdcast/actions/workflows/tests.yml)
[![Documentation](https://img.shields.io/badge/docs-ocean--uhh.github.io-blue.svg)](https://ocean-uhh.github.io/ctdcast/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22846130.svg)](https://doi.org/10.5281/zenodo.22846130)

Processing and reporting for shipboard CTD and LADCP data: raw Sea-Bird files (`.hex` with its
`.xmlcon`, or `.cnv`) → per-cast netCDF at each stage (read; trim; Sea-Bird's processing steps,
calibration and QC) → a compiled `profiles.nc` aligned with CF and CCHDO naming →
self-contained HTML reports, including a record of every processing step applied. Built for use
at sea: every output works offline, with no external requests.

**Documentation**: https://ocean-uhh.github.io/ctdcast/ · [example report](https://ocean-uhh.github.io/ctdcast/_static/demo/index.html)

## Installation

```bash
pip install ctdcast
```

Raw `.hex` files are read with Sea-Bird's `seabirdscientific`, which installs with ctdcast.
Reading `.cnv` files needs `seasenselib`, installed with the `cnv` extra
(`pip install "ctdcast[cnv]"`); land coastlines on
the interactive maps need the `maps` extra (`pip install "ctdcast[maps]"`). Python 3.11–3.14
is supported. See the [installation notes](https://ocean-uhh.github.io/ctdcast/quickstart.html)
for isolated-environment and from-source options.

## Quick start

Raw CNV files fresh off the instrument — one command gives station pages, an index and a map:

```bash
ctdcast draft /path/to/cnv/ --cruise odb2026     # writes ./ctd_draft/index.html
```

For the full pipeline — sections, time series, LADCP, the sensor inventory, the processing
record — write a config and run it:

```bash
ctdcast init --interactive        # guided config.yaml
ctdcast validate config.yaml      # check the config before the first run
ctdcast run config.yaml           # every stage from the raw files, then the report
```

`run` is `process` followed by `report`. To work a step at a time, run the stages with
`ctdcast process config.yaml --stage 1 2 3 profiles` and build the pages with
`ctdcast report config.yaml`; `--force` rebuilds, `--only 42` limits either to one cast.

`ctdcast clock config.yaml` diagnoses the acquisition-clock error and prints a paste-ready
`clock` block. See the [quickstart](https://ocean-uhh.github.io/ctdcast/quickstart.html)
for the recommended first-cruise workflow, the [config reference](https://ocean-uhh.github.io/ctdcast/config_yaml.html)
and the [CLI reference](https://ocean-uhh.github.io/ctdcast/cli_reference.html).

To check a source checkout, build a demo report from the committed fixture casts. They are
stage-1 files, so `--stage profiles` compiles and reports them without running stages 2–3
(which would write into the fixtures):

```bash
ctdcast run config_demo.yaml --stage profiles   # writes demo_report/index.html
```

The demo's files come with the repository, not with `pip install`. The published
[example report](https://ocean-uhh.github.io/ctdcast/_static/demo/index.html) is made from the
same casts by `scripts/make_demo.py`, which also runs stage 2 and QC, so it shows the QC tables
the local one lacks.

## Python API

```python
import ctdcast

ctdcast.report(
    "ctd_nc", "report", profiles_path="profiles.nc", groupings_yaml="ctd_groupings.yaml"
)
```

See the [API reference](https://ocean-uhh.github.io/ctdcast/api.html) for `process`,
`stage1`, `profiles` and the full interface.

## Acknowledgements

Development of this package started during the Odón de Buen cruise of AEI-DFG DS-MIXSED.
DS-MIXSED is funded by the Agencia Estatal de Investigación (AEI) through the PCI 2024 call —
projects PCI2024-155022-2 and PCI2024-155084-2 — and the Deutsche Forschungsgemeinschaft
(DFG, German Research Foundation) — Projektnummer 541914507.

Development was assisted by Claude Code (Anthropic) and GitHub Copilot code review.

## License

MIT License
