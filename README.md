# ctdcast

[![PyPI](https://img.shields.io/pypi/v/ctdcast.svg)](https://pypi.org/project/ctdcast/)
[![Python versions](https://img.shields.io/pypi/pyversions/ctdcast.svg)](https://pypi.org/project/ctdcast/)
[![License: MIT](https://img.shields.io/pypi/l/ctdcast.svg)](https://github.com/ocean-uhh/ctdcast/blob/main/LICENSE)
[![Tests](https://github.com/ocean-uhh/ctdcast/actions/workflows/tests.yml/badge.svg)](https://github.com/ocean-uhh/ctdcast/actions/workflows/tests.yml)
[![Documentation](https://img.shields.io/badge/docs-ocean--uhh.github.io-blue.svg)](https://ocean-uhh.github.io/ctdcast/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22846130.svg)](https://doi.org/10.5281/zenodo.22846130)

Processing and reporting for shipboard CTD and LADCP data: raw Sea-Bird files → per-cast
netCDF at each stage (read, trim, process/QC) → a compiled `profiles.nc` aligned with CF and
CCHDO naming → self-contained HTML reports. Built for use at sea: every output works offline,
with no external requests.

**Documentation**: https://ocean-uhh.github.io/ctdcast/ · [example report](https://ocean-uhh.github.io/ctdcast/_static/demo/index.html)

## Installation

```bash
pip install ctdcast
```

Reading raw `.cnv` files needs `seasenselib` (`pip install seasenselib`). Python 3.10–3.13 is
supported. See the [installation notes](https://ocean-uhh.github.io/ctdcast/quickstart.html)
for isolated-environment and from-source options.

## Quick start

Raw CNV files fresh off the instrument — one command gives station pages, an index and a map:

```bash
ctdcast draft /path/to/cnv/ --cruise odb2026     # writes ./ctd_draft/index.html
```

For the full pipeline — sections, time series, LADCP, the sensor inventory — write a config
and process stage by stage:

```bash
ctdcast init --interactive        # guided config.yaml
ctdcast validate config.yaml      # check paths before the first run
ctdcast process config.yaml --stage 1 2 3 profiles
ctdcast run config.yaml           # the report; --force rebuilds, --only 42 one cast
```

`ctdcast clock config.yaml` diagnoses the acquisition-clock error and prints a paste-ready
`processing.clock` block. See the [quickstart](https://ocean-uhh.github.io/ctdcast/quickstart.html)
for the recommended first-cruise workflow, the [config reference](https://ocean-uhh.github.io/ctdcast/config_yaml.html)
and the [CLI reference](https://ocean-uhh.github.io/ctdcast/cli_reference.html).

To check an installation, run the bundled demo against the committed fixture casts:

```bash
ctdcast run config_demo.yaml      # writes demo_report/index.html
```

## Python API

```python
import ctdcast

ctdcast.report("ctd_nc", "report", profiles_path="profiles.nc",
               groupings_yaml="ctd_groupings.yaml")
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
