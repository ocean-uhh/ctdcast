"""CLI entry point: python -m ctd_report <config.yaml> [--type TYPE] [--force]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import yaml


def main() -> None:
    """Run ctd_report from a config YAML file."""
    parser = argparse.ArgumentParser(
        prog="python -m ctd_report",
        description="Generate CTD report HTML from a config YAML.",
    )
    parser.add_argument("config", type=Path, help="Path to config YAML file")
    parser.add_argument(
        "--type",
        dest="report_type",
        choices=["all", "stations", "sections", "timeseries"],
        default="all",
        help="Which report type(s) to generate (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing output files even if up-to-date",
    )
    args = parser.parse_args()

    cfg_path: Path = args.config
    if not cfg_path.exists():
        print(f"Config file not found: {cfg_path}")
        sys.exit(1)

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    data = cfg.get("data", {})
    output = cfg.get("output", {})
    display = cfg.get("display", {})
    cruise_info = cfg.get("cruise_info", {})

    # --force on CLI overrides config; otherwise use config value
    force = args.force or bool(cfg.get("force", False))

    # --type on CLI overrides config generate: flags
    gen_cfg = cfg.get("generate", {})
    if args.report_type == "all":
        gen = gen_cfg
    else:
        gen = {
            "stations": args.report_type == "stations",
            "sections": args.report_type == "sections",
            "timeseries": args.report_type == "timeseries",
        }

    section_style = display.get("section_style", "pcolormesh")
    timeseries_style = display.get("timeseries_style", "pcolormesh")
    vmin_override: dict = {
        k: v for k, v in (display.get("vmin") or {}).items() if v is not None
    }
    vmax_override: dict = {
        k: v for k, v in (display.get("vmax") or {}).items() if v is not None
    }

    nc_dir = Path(data["nc_dir"])
    profiles_path = Path(data["profiles_nc"])
    section_yaml = Path(data["section_yaml"])
    out_dir = Path(output["dir"])

    # Configure module-level plot options before any figures are made
    import ctd_report._plots as plots

    gebco = data.get("gebco_nc", "")
    if gebco:
        plots.GEBCO_PATH = Path(gebco)

    ladcp_dir: Optional[Path] = None
    ladcp_raw = data.get("ladcp_dir", "")
    if ladcp_raw:
        ladcp_dir = Path(ladcp_raw)
    plots.CLEAN_SPINES = bool(display.get("clean_spines", True))
    pf = display.get("profile_figsize", [7, 10])
    plots.PROFILE_FIGSIZE = (float(pf[0]), float(pf[1]))
    ov = display.get("overview_figsize", [12, 4])
    plots.OVERVIEW_FIGSIZE = (float(ov[0]), float(ov[1]))

    ci = cfg.get("cruise_info", {})
    if ci.get("map_lat_min") is not None:
        plots.MAP_LAT_MIN = float(ci["map_lat_min"])
    if ci.get("map_lat_max") is not None:
        plots.MAP_LAT_MAX = float(ci["map_lat_max"])
    if ci.get("map_lon_min") is not None:
        plots.MAP_LON_MIN = float(ci["map_lon_min"])
    if ci.get("map_lon_max") is not None:
        plots.MAP_LON_MAX = float(ci["map_lon_max"])

    # Import here so GEBCO_PATH is set before any plotting
    from ctd_report._index import (
        _read_cast_meta,
        _select_cast_files,
        _write_index,
        _write_sections_list,
        _write_stations_list,
        _write_timeseries_list,
    )
    from ctd_report._section import generate_section_page
    from ctd_report._station import generate_station_page
    from ctd_report._timeseries import generate_timeseries_page

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
                meta["path"],
                out_dir,
                all_meta,
                prev_num=prev_num,
                next_num=next_num,
                force=force,
                ladcp_dir=ladcp_dir,
            )
            print(f"  station cast_{meta['cast_num']:03d}: {'ok' if out else 'FAILED'}")

    yaml_data: dict = {}
    if section_yaml.exists():
        with open(section_yaml) as f:
            yaml_data = _yaml.safe_load(f) or {}

    sections_cfg: dict = yaml_data.get("sections", {})
    timeseries_cfg: dict = yaml_data.get("timeseries", {})

    if gen.get("sections", True):
        for sec_name, sec_cfg in sections_cfg.items():
            out = generate_section_page(
                sec_name,
                sec_cfg,
                profiles_path,
                out_dir,
                force=force,
                section_style=section_style,
                vmin_override=vmin_override,
                vmax_override=vmax_override,
                ladcp_dir=ladcp_dir,
            )
            status = "ok" if out else "skipped"
            print(f"  section {sec_name}: {status}")

    if gen.get("timeseries", True) and timeseries_cfg:
        for ts_name, ts_cfg in timeseries_cfg.items():
            out = generate_timeseries_page(
                ts_name,
                ts_cfg,
                profiles_path,
                out_dir,
                force=force,
                section_style=timeseries_style,
                vmin_override=vmin_override,
                vmax_override=vmax_override,
                all_meta=all_meta,
            )
            status = "ok" if out else "skipped"
            print(f"  timeseries {ts_name}: {status}")

    _write_index(
        all_meta,
        sections_cfg,
        cruise,
        out_dir,
        force,
        profiles_path=profiles_path,
        section_style=section_style,
        vmin_override=vmin_override,
        vmax_override=vmax_override,
        cruise_info=cruise_info,
        timeseries_cfg=timeseries_cfg,
    )
    _write_stations_list(
        all_meta,
        cruise,
        out_dir,
        sections_cfg=sections_cfg,
        timeseries_cfg=timeseries_cfg,
        ladcp_dir=ladcp_dir,
    )
    _write_sections_list(
        sections_cfg, cruise, out_dir, all_meta=all_meta, ladcp_dir=ladcp_dir
    )
    _write_timeseries_list(
        timeseries_cfg, cruise, out_dir, all_meta=all_meta, ladcp_dir=ladcp_dir
    )

    ship_track_nc: Optional[Path] = None
    ship_track_raw = data.get("ship_track", "")
    if ship_track_raw:
        ship_track_nc = Path(ship_track_raw)

    try:
        from ctd_report._map_leaflet import generate_leaflet_map  # noqa: PLC0415

        lf_out = generate_leaflet_map(
            all_meta, sections_cfg, out_dir, force=force, ship_track_nc=ship_track_nc
        )
        if lf_out:
            print(f"  leaflet map: ok → {lf_out}")
        else:
            print("  leaflet map: skipped (no casts)")
    except Exception:  # noqa: BLE001
        import traceback as _tb2

        print("  leaflet map: FAILED")
        _tb2.print_exc()

    print(f"\nReport written to {out_dir}/index.html")


if __name__ == "__main__":
    main()
