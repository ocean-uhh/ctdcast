"""CLI entry point: python -m ctd_report <config.yaml>."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main() -> None:
    """Run ctd_report from a config YAML file."""
    if len(sys.argv) < 2:
        print("Usage: python -m ctd_report <config.yaml>")
        sys.exit(1)

    cfg_path = Path(sys.argv[1])
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}")
        sys.exit(1)

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    data = cfg.get("data", {})
    output = cfg.get("output", {})
    gen = cfg.get("generate", {})
    display = cfg.get("display", {})
    force = bool(cfg.get("force", False))
    section_style = display.get("section_style", "pcolormesh")

    nc_dir = Path(data["nc_dir"])
    profiles_path = Path(data["profiles_nc"])
    section_yaml = Path(data["section_yaml"])
    out_dir = Path(output["dir"])

    # Configure GEBCO bathymetry path if provided
    gebco = data.get("gebco_nc", "")
    if gebco:
        import ctd_report._plots as plots
        plots.GEBCO_PATH = Path(gebco)

    # Import here so GEBCO_PATH is set before any plotting
    from ctd_report._index import (
        _read_cast_meta,
        _select_cast_files,
        _write_index,
        _write_sections_list,
        _write_stations_list,
    )
    from ctd_report._section import generate_section_page
    from ctd_report._station import generate_station_page

    import numpy as np
    import yaml as _yaml

    out_dir.mkdir(parents=True, exist_ok=True)

    cast_files = _select_cast_files(nc_dir)
    if not cast_files:
        print(f"No cast .nc files found in {nc_dir}")
        sys.exit(1)

    print(f"Found {len(cast_files)} cast files")
    all_meta_raw = [_read_cast_meta(p) for p in cast_files]
    all_meta = sorted(
        [m for m in all_meta_raw if m is not None],
        key=lambda m: m["time_start"],
        reverse=True,
    )
    cruise = all_meta[0].get("cruise", "odb2026") if all_meta else "odb2026"

    if gen.get("stations", True):
        cast_nums = [m["cast_num"] for m in all_meta]
        for i, meta in enumerate(all_meta):
            prev_num = cast_nums[i - 1] if i > 0 else None
            next_num = cast_nums[i + 1] if i < len(all_meta) - 1 else None
            out = generate_station_page(
                meta["path"], out_dir, all_meta,
                prev_num=prev_num, next_num=next_num, force=force,
            )
            print(f"  station cast_{meta['cast_num']:03d}: {'ok' if out else 'FAILED'}")

    sections_cfg: dict = {}
    if section_yaml.exists():
        with open(section_yaml) as f:
            sections_cfg = _yaml.safe_load(f).get("sections", {})

    if gen.get("sections", True):
        for sec_name, sec_cfg in sections_cfg.items():
            out = generate_section_page(sec_name, sec_cfg, profiles_path, out_dir,
                                        force=force, section_style=section_style)
            status = "ok" if out else "skipped"
            print(f"  section {sec_name}: {status}")

    # Phase 2: stacked overview plots embedded on index.html — not a separate page.

    _write_index(all_meta, sections_cfg, cruise, out_dir, force)
    _write_stations_list(all_meta, cruise, out_dir)
    _write_sections_list(sections_cfg, cruise, out_dir)
    print(f"\nReport written to {out_dir}/index.html")


if __name__ == "__main__":
    main()
