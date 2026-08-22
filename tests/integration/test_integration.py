"""Integration tests: end-to-end report generation from fixture data.

These tests call the real generators (station, section, timeseries, full
entry-point) against the committed fixture cast files and LADCP .mat files.
They are slower than the unit tests (~30 s total) and are kept in a
separate directory so they can be targeted with ``pytest tests/integration/``.
"""

import importlib
import re
import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ctdcast.analysis.derive import derive_teos10 as add_teos10
from ctdcast.processors.profiles import build_profiles
from ctdcast.processors.stage1 import stage1 as convert_ctd_files
from ctdcast.processors.stage_layout import stage_path
from ctdcast.reports._cast import generate_station_page
from ctdcast.reports._index import _read_cast_meta, report
from ctdcast.reports._section import generate_section_page
from ctdcast.reports._timeseries import generate_timeseries_page

pytestmark = pytest.mark.slow

_HERE = Path(__file__).parent
_FIXTURES = _HERE.parent / "fixtures"
_NC = _FIXTURES / "nc"
_LADCP = _FIXTURES / "ladcp"

_CAST_011 = _NC / "mixsed2_011.nc"
_CAST_012 = _NC / "mixsed2_012.nc"
_CAST_128 = _NC / "mixsed2_128.nc"
_CAST_129 = _NC / "mixsed2_129.nc"

_SECTION_YAML = """\
sections:
  KO:
    description: Kangerlussuaq Outer (fixture)
    cast_numbers: [[11, 12]]
    color: "#1f77b4"

timeseries:
  Triangle:
    description: Triangle repeat station (fixture)
    cast_numbers: [[128, 129]]
    color: "#d62728"
"""


def _no_external_resources(html: str) -> list[str]:
    """Return list of external resource links (src= or <link href=) found in HTML."""
    found = re.findall(r'\bsrc=["\']https?://', html)
    found += re.findall(r'<link\b[^>]+\bhref=["\']https?://', html)
    return found


@pytest.fixture(scope="module")
def all_meta():
    """Metadata for all four fixture casts."""
    metas = [_read_cast_meta(p) for p in (_CAST_011, _CAST_012, _CAST_128, _CAST_129)]
    return [m for m in metas if m is not None]


@pytest.fixture(scope="module")
def profiles_nc(tmp_path_factory):
    """Build profiles.nc once for the module from the fixture nc files."""
    out = tmp_path_factory.mktemp("profiles") / "profiles.nc"
    build_profiles(_NC, out, force=True)
    return out


@pytest.fixture(scope="module")
def section_yaml_path(tmp_path_factory):
    """Write the fixture section YAML to a temp file."""
    p = tmp_path_factory.mktemp("yaml") / "ctd_sections.yaml"
    p.write_text(_SECTION_YAML, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Station page: LADCP present vs absent
# ---------------------------------------------------------------------------


class TestStationLadcp:
    """Verify that the LADCP panel appears iff a LADCP directory is supplied."""

    def test_without_ladcp_no_ladcp_section(self, tmp_path, all_meta):
        out = generate_station_page(
            _CAST_011, tmp_path, all_meta=all_meta, force=True, ladcp_dir=None
        )
        assert out is not None and out.exists()
        html = out.read_text(encoding="utf-8")
        assert 'id="s-ladcp"' not in html, "LADCP section present despite no ladcp_dir"

    def test_with_ladcp_has_ladcp_section(self, tmp_path, all_meta):
        out = generate_station_page(
            _CAST_011, tmp_path, all_meta=all_meta, force=True, ladcp_dir=_LADCP
        )
        assert out is not None and out.exists()
        html = out.read_text(encoding="utf-8")
        assert 'id="s-ladcp"' in html, (
            "LADCP section missing despite ladcp_dir supplied"
        )

    def test_with_ladcp_self_contained(self, tmp_path, all_meta):
        out = generate_station_page(
            _CAST_011, tmp_path, all_meta=all_meta, force=True, ladcp_dir=_LADCP
        )
        html = out.read_text(encoding="utf-8")
        assert _no_external_resources(html) == []

    def test_without_ladcp_self_contained(self, tmp_path, all_meta):
        out = generate_station_page(
            _CAST_011, tmp_path, all_meta=all_meta, force=True, ladcp_dir=None
        )
        html = out.read_text(encoding="utf-8")
        assert _no_external_resources(html) == []

    def test_deep_cast_with_ladcp(self, tmp_path, all_meta):
        """Cast 128 (~680 dbar) with LADCP should also produce a valid page."""
        out = generate_station_page(
            _CAST_128, tmp_path, all_meta=all_meta, force=True, ladcp_dir=_LADCP
        )
        assert out is not None and out.exists()
        html = out.read_text(encoding="utf-8")
        assert 'id="s-ladcp"' in html
        assert _no_external_resources(html) == []


# ---------------------------------------------------------------------------
# Section page
# ---------------------------------------------------------------------------


class TestSectionPage:
    """Verify section page generation from profiles.nc + section config."""

    def test_section_generates(self, tmp_path, profiles_nc):
        sec_cfg = {
            "description": "KO fixture",
            "cast_numbers": [[11, 12]],
            "color": "#1f77b4",
        }
        out = generate_section_page("KO", sec_cfg, profiles_nc, tmp_path, force=True)
        assert out is not None, "generate_section_page returned None"
        assert out.exists()
        assert out == tmp_path / "sections" / "section_KO.html"

    def test_section_is_valid_html(self, tmp_path, profiles_nc):
        sec_cfg = {
            "description": "KO fixture",
            "cast_numbers": [[11, 12]],
            "color": "#1f77b4",
        }
        out = generate_section_page("KO", sec_cfg, profiles_nc, tmp_path, force=True)
        html = out.read_text(encoding="utf-8")
        assert html.lower().startswith("<!doctype html")
        assert "</html>" in html.lower()

    def test_section_is_self_contained(self, tmp_path, profiles_nc):
        sec_cfg = {
            "description": "KO fixture",
            "cast_numbers": [[11, 12]],
            "color": "#1f77b4",
        }
        out = generate_section_page("KO", sec_cfg, profiles_nc, tmp_path, force=True)
        html = out.read_text(encoding="utf-8")
        assert _no_external_resources(html) == []

    def test_section_with_ladcp(self, tmp_path, profiles_nc):
        sec_cfg = {
            "description": "KO fixture",
            "cast_numbers": [[11, 12]],
            "color": "#1f77b4",
        }
        out = generate_section_page(
            "KO", sec_cfg, profiles_nc, tmp_path, force=True, ladcp_dir=_LADCP
        )
        assert out is not None and out.exists()

    @staticmethod
    def _pill_order(html):
        # Cast pills link each selected cast, in the section's plotted order.
        return re.findall(r"casts/cast_(\w+)\.html", html)

    def test_section_preserves_config_order(self, tmp_path, profiles_nc):
        # Mode 1: casts appear in the order written, not profiles.nc order.
        sec_cfg = {
            "description": "out of order",
            "cast_numbers": [128, 11, 129, 12],
            "color": "#1f77b4",
        }
        out = generate_section_page("OO", sec_cfg, profiles_nc, tmp_path, force=True)
        assert self._pill_order(out.read_text(encoding="utf-8")) == [
            "128",
            "011",
            "129",
            "012",
        ]

    def test_section_key_cast_orders_by_distance(self, tmp_path, profiles_nc):
        # Mode 2: key_cast=128 orders casts by distance from 128, regardless of
        # the written order (fixture geometry: 128,129 are ~30 km from 11,12).
        sec_cfg = {
            "description": "key cast",
            "cast_numbers": [11, 12, 128, 129],
            "key_cast": 128,
            "color": "#1f77b4",
        }
        out = generate_section_page("KC", sec_cfg, profiles_nc, tmp_path, force=True)
        assert self._pill_order(out.read_text(encoding="utf-8")) == [
            "128",
            "129",
            "012",
            "011",
        ]


# ---------------------------------------------------------------------------
# Timeseries page
# ---------------------------------------------------------------------------


class TestTimeseriesPage:
    """Verify timeseries page generation from profiles.nc + timeseries config."""

    def test_timeseries_generates(self, tmp_path, profiles_nc, all_meta):
        ts_cfg = {
            "description": "Triangle fixture",
            "cast_numbers": [[128, 129]],
            "color": "#d62728",
        }
        out = generate_timeseries_page(
            "Triangle", ts_cfg, profiles_nc, tmp_path, force=True, all_meta=all_meta
        )
        assert out is not None, "generate_timeseries_page returned None"
        assert out.exists()
        assert out == tmp_path / "timeseries" / "timeseries_Triangle.html"

    def test_timeseries_is_valid_html(self, tmp_path, profiles_nc, all_meta):
        ts_cfg = {
            "description": "Triangle fixture",
            "cast_numbers": [[128, 129]],
            "color": "#d62728",
        }
        out = generate_timeseries_page(
            "Triangle", ts_cfg, profiles_nc, tmp_path, force=True, all_meta=all_meta
        )
        html = out.read_text(encoding="utf-8")
        assert html.lower().startswith("<!doctype html")
        assert "</html>" in html.lower()

    def test_timeseries_is_self_contained(self, tmp_path, profiles_nc, all_meta):
        ts_cfg = {
            "description": "Triangle fixture",
            "cast_numbers": [[128, 129]],
            "color": "#d62728",
        }
        out = generate_timeseries_page(
            "Triangle", ts_cfg, profiles_nc, tmp_path, force=True, all_meta=all_meta
        )
        html = out.read_text(encoding="utf-8")
        assert _no_external_resources(html) == []


# ---------------------------------------------------------------------------
# Full entry-point: report
# ---------------------------------------------------------------------------


class TestFullReport:
    """Drive report end-to-end with section + timeseries YAML."""

    def test_generates_all_station_pages(
        self, tmp_path, section_yaml_path, profiles_nc
    ):
        report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            ladcp_dir=_LADCP,
            force=True,
        )
        for cast_num in (11, 12, 128, 129):
            p = tmp_path / "casts" / f"cast_{cast_num:03d}.html"
            assert p.exists(), f"Missing cast page: {p.name}"

    def test_generates_section_page(self, tmp_path, section_yaml_path, profiles_nc):
        report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            force=True,
        )
        assert (tmp_path / "sections" / "section_KO.html").exists()

    def test_generates_timeseries_page(self, tmp_path, section_yaml_path, profiles_nc):
        report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            force=True,
        )
        assert (tmp_path / "timeseries" / "timeseries_Triangle.html").exists()

    def test_generates_index_pages(self, tmp_path, section_yaml_path, profiles_nc):
        report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            force=True,
        )
        for name in (
            "index.html",
            "casts.html",
            "sections.html",
            "leaflet.html",
        ):
            assert (tmp_path / name).exists(), f"Missing index page: {name}"

    def test_profiles_only_fallback_no_station_pages(
        self, tmp_path, section_yaml_path, profiles_nc
    ):
        """No per-cast files → cruise-level report from profiles.nc, no station pages.

        The index and casts list say per-cast pages are absent, and no row links to
        a per-cast page that was never built.
        """
        empty_nc = tmp_path / "empty_nc"
        empty_nc.mkdir()
        report(
            empty_nc,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            force=True,
        )
        # Cruise-level (synthesis) pages are built from profiles.nc ...
        for name in ("index.html", "casts.html", "sections.html"):
            assert (tmp_path / name).exists(), f"Missing cruise page: {name}"
        # ... but no per-cast station pages exist.
        assert not list((tmp_path / "casts").glob("cast_*.html"))
        # The index states why per-cast pages are absent (honesty, not silence).
        index_html = (tmp_path / "index.html").read_text(encoding="utf-8")
        assert "per-cast" in index_html.lower()
        # casts.html lists the casts but links no row to a missing per-cast page.
        casts_html = (tmp_path / "casts.html").read_text(encoding="utf-8")
        assert 'href="casts/cast_' not in casts_html

    def test_no_external_resources_in_station(
        self, tmp_path, section_yaml_path, profiles_nc
    ):
        report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            ladcp_dir=_LADCP,
            force=True,
        )
        html = (tmp_path / "casts" / "cast_011.html").read_text(encoding="utf-8")
        assert _no_external_resources(html) == []

    def test_stations_only_no_yaml(self, tmp_path):
        """report must work with no section_yaml (stations only)."""
        report(
            _NC,
            tmp_path,
            generate={
                "stations": True,
                "sections": False,
                "timeseries": False,
                "index": False,
                "map": False,
            },
            force=True,
        )
        for cast_num in (11, 12, 128, 129):
            assert (tmp_path / "casts" / f"cast_{cast_num:03d}.html").exists()


class TestCastNotes:
    """Verify that cast_notes appear as warning banners on the station page."""

    def test_note_rendered_in_html(self, tmp_path, all_meta):
        note_text = "SBE43 malfunction — oxygen data unreliable"
        out = generate_station_page(
            _CAST_011,
            tmp_path,
            all_meta=all_meta,
            force=True,
            cast_notes=[note_text],
        )
        assert out is not None and out.exists()
        html = out.read_text(encoding="utf-8")
        assert note_text in html, "cast_notes text must appear in station page HTML"

    def test_no_note_banner_when_empty(self, tmp_path, all_meta):
        out = generate_station_page(
            _CAST_011,
            tmp_path,
            all_meta=all_meta,
            force=True,
            cast_notes=[],
        )
        html = out.read_text(encoding="utf-8")
        assert '<p class="cast-note">' not in html, (
            "No .cast-note elements when cast_notes is empty"
        )

    def test_multiple_notes_all_rendered(self, tmp_path, all_meta):
        notes = ["LADCP failed on deployment", "CTD only, no LADCP planned"]
        out = generate_station_page(
            _CAST_011,
            tmp_path,
            all_meta=all_meta,
            force=True,
            cast_notes=notes,
        )
        html = out.read_text(encoding="utf-8")
        for note in notes:
            assert note in html


_OXY_CNV = _FIXTURES / "oxy" / "msm_142_1_056_1sec.cnv"


@pytest.mark.skipif(
    not _OXY_CNV.exists() or importlib.util.find_spec("seasenselib") is None,
    reason="MSM142 oxygen fixture or seasenselib not present",
)
class TestOxygenConversion:
    """Integration test for µmol/L → µmol/kg conversion (stage1) and % saturation derivation."""

    def test_oxygen_units_converted(self, tmp_path):
        """stage1 must yield ctd_oxygen_1 in µmol/kg; add_teos10 must add oxygen_saturation."""
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            n = convert_ctd_files(
                _OXY_CNV.parent,
                tmp_path,
                force=True,
                pattern=_OXY_CNV.name,
            )
        assert n == 1, "Expected exactly one NC file written"

        nc_path = stage_path(tmp_path, _OXY_CNV.stem, 1)
        assert nc_path.exists()

        ds = xr.open_dataset(nc_path, engine="netcdf4")
        # After normalise, MSM oxygen (2 sensors) appears as ctd_oxygen_1/ctd_oxygen_2
        oxy_var = next((v for v in ("ctd_oxygen", "ctd_oxygen_1") if v in ds), None)
        assert oxy_var is not None, (
            "No ctd_oxygen or ctd_oxygen_1 in converted NC; "
            f"vars present: {sorted(ds.data_vars)}"
        )

        raw_units = ds[oxy_var].attrs.get("units", "")
        assert any(tok in raw_units.lower() for tok in ("umol", "µmol")), (
            f"Expected µmol units; got {raw_units!r}"
        )

        with warnings.catch_warnings():
            warnings.simplefilter("always")
            ds_converted = add_teos10(ds)

        # After add_teos10, oxygen_saturation = derived % saturation; oxy_var unchanged
        assert "oxygen_saturation" in ds_converted, (
            "oxygen_saturation missing after add_teos10"
        )
        assert ds_converted["oxygen_saturation"].attrs["units"] == "% saturation", (
            f"Expected '% saturation'; got "
            f"{ds_converted['oxygen_saturation'].attrs['units']!r}"
        )
        assert "source_units" in ds_converted["oxygen_saturation"].attrs, (
            "source_units attribute must be preserved in oxygen_saturation after conversion"
        )

        vals = ds_converted["oxygen_saturation"].values
        finite = vals[~np.isnan(vals)]
        assert len(finite) > 0, "No finite oxygen values after conversion"
        assert finite.min() >= 0.0, f"Negative % saturation: min={finite.min():.2f}"
        assert finite.max() <= 200.0, (
            f"Implausibly high % saturation: max={finite.max():.2f}"
        )
