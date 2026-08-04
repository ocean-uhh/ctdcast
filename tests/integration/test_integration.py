"""Integration tests: end-to-end report generation from fixture data.

These tests call the real generators (station, section, timeseries, full
entry-point) against the committed fixture cast files and LADCP .mat files.
They are slower than the unit tests (~30 s total) and are kept in a
separate directory so they can be targeted with ``pytest tests/integration/``.
"""

import re
import warnings
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

pytestmark = pytest.mark.slow

from ctdreport.analysis import _add_teos10
from ctdreport.converters import build_profiles, convert_ctd_files
from ctdreport.index import _read_cast_meta, generate_ctd_report
from ctdreport.section import generate_section_page
from ctdreport.station import generate_station_page
from ctdreport.timeseries import generate_timeseries_page

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
# Full entry-point: generate_ctd_report
# ---------------------------------------------------------------------------


class TestFullReport:
    """Drive generate_ctd_report end-to-end with section + timeseries YAML."""

    def test_generates_all_station_pages(
        self, tmp_path, section_yaml_path, profiles_nc
    ):
        generate_ctd_report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            ladcp_dir=_LADCP,
            force=True,
        )
        for cast_num in (11, 12, 128, 129):
            p = tmp_path / "stations" / f"cast_{cast_num:03d}.html"
            assert p.exists(), f"Missing station page: {p.name}"

    def test_generates_section_page(self, tmp_path, section_yaml_path, profiles_nc):
        generate_ctd_report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            force=True,
        )
        assert (tmp_path / "sections" / "section_KO.html").exists()

    def test_generates_timeseries_page(self, tmp_path, section_yaml_path, profiles_nc):
        generate_ctd_report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            force=True,
        )
        assert (tmp_path / "timeseries" / "timeseries_Triangle.html").exists()

    def test_generates_index_pages(self, tmp_path, section_yaml_path, profiles_nc):
        generate_ctd_report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            force=True,
        )
        for name in (
            "index.html",
            "station_index.html",
            "sections.html",
            "leaflet.html",
        ):
            assert (tmp_path / name).exists(), f"Missing index page: {name}"

    def test_no_external_resources_in_station(
        self, tmp_path, section_yaml_path, profiles_nc
    ):
        generate_ctd_report(
            _NC,
            tmp_path,
            profiles_path=profiles_nc,
            section_yaml=section_yaml_path,
            ladcp_dir=_LADCP,
            force=True,
        )
        html = (tmp_path / "stations" / "cast_011.html").read_text(encoding="utf-8")
        assert _no_external_resources(html) == []

    def test_stations_only_no_yaml(self, tmp_path):
        """generate_ctd_report must work with no section_yaml (stations only)."""
        generate_ctd_report(
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
            assert (tmp_path / "stations" / f"cast_{cast_num:03d}.html").exists()


_OXY_CNV = _FIXTURES / "oxy" / "msm_142_1_056_1sec.cnv"


@pytest.mark.skipif(not _OXY_CNV.exists(), reason="MSM142 oxygen fixture not present")
class TestOxygenConversion:
    """Integration test for µmol/L → % saturation conversion via _add_teos10."""

    def test_oxygen_units_converted(self, tmp_path):
        """convert_ctd_files → _add_teos10 must yield oxygen in % saturation."""
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="gsw")
            n = convert_ctd_files(
                _OXY_CNV.parent,
                tmp_path,
                force=True,
                pattern=_OXY_CNV.name,
            )
        assert n == 1, "Expected exactly one NC file written"

        nc_path = tmp_path / (_OXY_CNV.stem + ".nc")
        assert nc_path.exists()

        ds = xr.open_dataset(nc_path, engine="netcdf4")
        assert "oxygen_1" in ds, "oxygen_1 variable missing from converted NC"

        raw_units = ds["oxygen_1"].attrs.get("units", "")
        assert any(tok in raw_units.lower() for tok in ("umol", "µmol")), (
            f"Expected µmol units before conversion; got {raw_units!r}"
        )

        with warnings.catch_warnings():
            warnings.simplefilter("always")
            ds_converted = _add_teos10(ds)

        assert ds_converted["oxygen_1"].attrs["units"] == "% saturation", (
            f"Expected '% saturation'; got {ds_converted['oxygen_1'].attrs['units']!r}"
        )
        assert "original_units" in ds_converted["oxygen_1"].attrs, (
            "original_units attribute must be preserved after conversion"
        )

        vals = ds_converted["oxygen_1"].values
        finite = vals[~np.isnan(vals)]
        assert len(finite) > 0, "No finite oxygen values after conversion"
        assert finite.min() >= 0.0, f"Negative % saturation: min={finite.min():.2f}"
        assert finite.max() <= 200.0, (
            f"Implausibly high % saturation: max={finite.max():.2f}"
        )
