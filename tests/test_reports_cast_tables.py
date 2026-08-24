"""Tests for the cast-page table renderers: processing provenance and sensor roles.

These exercise the HTML builders over their display inputs (an attribute mapping, a
sensor-info list) — the rendering logic, not instrument data.
"""

from ctdcast.config.cnv_header import Correction, SensorCalibration
from ctdcast.reports._cast import (
    _render_provenance_table,
    _render_sensor_calibration_table,
    _render_sensor_table,
)


class TestRenderSensorCalibrationTable:
    """_render_sensor_calibration_table shows each sensor's drift Slope/Offset and state."""

    _CALS = [
        # temperature_1: identity -> no drift.  conductivity_1: slope only differs.
        # pressure: both slope AND offset differ.
        SensorCalibration(
            "temperature", "temperature_1", "6435", "1.00000000", "0.0000", False, False
        ),
        SensorCalibration(
            "conductivity",
            "conductivity_1",
            "4922",
            "1.00000452",
            "0.00000",
            True,
            False,
        ),
        SensorCalibration(
            "pressure", "pressure", "0814", "1.00004096", "0.27440", True, True
        ),
    ]

    def test_empty_returns_blank(self):
        """No sensors yields an empty string, not a table."""
        assert _render_sensor_calibration_table([]) == ""

    def test_rows_state_and_verbatim_values(self):
        """Each sensor is a row; state distinguishes drift from pre-cruise; values verbatim."""
        html = _render_sensor_calibration_table(self._CALS)
        assert "Sensor calibration state" in html
        assert "conductivity_1" in html and "1.00000452" in html
        assert "drift/span correction applied" in html
        assert "pre-cruise coefficients" in html

    def test_drift_row_is_amber(self):
        """A row carrying a correction is tinted with the vendored warn background."""
        html = _render_sensor_calibration_table(self._CALS)
        # the identity temperature_1 row is not tinted; the pressure row is
        assert "background:var(--warn-bg)" in html
        assert html.count("background:var(--warn-bg)") == 10  # 2 drift rows x 5 cells

    def test_only_the_differing_value_is_bolded(self):
        """The specific slope/offset that departs from default is bolded, not the other."""
        html = _render_sensor_calibration_table(self._CALS)
        # conductivity_1: slope differs (bold), offset is default (not bold)
        assert "<strong>1.00000452</strong>" in html
        assert "<strong>0.00000</strong>" not in html
        # pressure: both differ -> both bold
        assert "<strong>1.00004096</strong>" in html
        assert "<strong>0.27440</strong>" in html
        # identity temperature_1 slope is never bolded
        assert "<strong>1.00000000</strong>" not in html

    def test_provenance_table_includes_calibration(self):
        """The calibration table is embedded in the provenance panel output."""
        html = _render_provenance_table([], {}, [], self._CALS)
        assert html is not None
        assert "Sensor calibration state" in html
        assert "0814" in html


class TestRenderProvenanceTable:
    """_render_provenance_table renders structured corrections into producer/version/params."""

    def _records(self):
        return [
            Correction(
                "align (deck)", "align", "SBE 11plus deck unit", "V 5.2", "c0 +0.073 s"
            ),
            Correction(
                "datcnv", "datcnv", "SBE Data Processing", "7.26.7.129", "skipover=0"
            ),
            Correction(
                "celltm", "celltm", "SBE Data Processing", "7.26.7.129", "alpha=0.03"
            ),
        ]

    _TIME = {
        "time_coordinate_source": "System UTC, first data scan.",
        "time_clock_offset_seconds": 5.0,
    }

    def test_none_without_ledger(self):
        """No records and no time attributes yields no table."""
        assert _render_provenance_table([], {"cruise": "MSM142"}) is None

    def test_columns_and_order(self):
        """Producer and version are their own columns, rows in record order."""
        html = _render_provenance_table(self._records(), {})
        assert "<th>Producer</th><th>Version</th><th>Parameters</th>" in html
        assert "<td>SBE Data Processing</td>" in html
        assert "<td class='mono'>V 5.2</td>" in html
        assert (
            html.index("align (deck)") < html.index(">datcnv<") < html.index(">celltm<")
        )

    def test_advisories_rendered_as_list(self):
        """Structural advisories render as an escaped bullet list under an Advisories heading."""
        html = _render_provenance_table(
            self._records(),
            {},
            ["Already binned to a pressure grid", "Deck-unit advance is asymmetric"],
        )
        assert "<h3 style='margin-bottom:0.25rem'>Advisories</h3>" in html
        assert "<li>Already binned to a pressure grid</li>" in html
        assert "<li>Deck-unit advance is asymmetric</li>" in html

    def test_no_advisories_no_heading(self):
        """With no advisories, no Advisories section is emitted."""
        html = _render_provenance_table(self._records(), {}, [])
        assert "Advisories" not in html

    def test_advisories_only_still_renders(self):
        """A cast with only advisories (no records, no time attrs) still renders the note."""
        html = _render_provenance_table(
            [], {}, ["Time coordinate is on the system clock"]
        )
        assert html is not None
        assert "Advisories" in html
        assert "Time coordinate is on the system clock" in html

    def test_time_coordinate_rendered(self):
        """The time source (SBE phrasing) and the clock offset both appear."""
        html = _render_provenance_table([], self._TIME)
        assert "System UTC, first data scan." in html
        assert "5.0 s" in html

    def test_repeated_module_labelled(self):
        """A suffixed record renders as 'module (2)' in its own row."""
        records = [
            Correction(
                "wildedit", "wildedit", "SBE Data Processing", "7", "pass1_nstd=2.0"
            ),
            Correction(
                "wildedit (2)",
                "wildedit_2",
                "SBE Data Processing",
                "7",
                "pass1_nstd=9.9",
            ),
        ]
        html = _render_provenance_table(records, {})
        assert "pass1_nstd=2.0" in html
        assert "wildedit (2)" in html
        assert "pass1_nstd=9.9" in html


class TestRenderSensorTablePrimarySecondary:
    """_render_sensor_table marks primary/secondary only for duplicated sensor types."""

    def test_dual_sensor_type_marked(self):
        """Two temperature sensors are marked primary and secondary in channel order."""
        info = [
            {
                "sensor_type": "Temperature",
                "serial_number": "4798",
                "calibration_date": "a",
            },
            {
                "sensor_type": "Conductivity",
                "serial_number": "3345",
                "calibration_date": "a",
            },
            {
                "sensor_type": "Temperature",
                "serial_number": "6435",
                "calibration_date": "a",
            },
            {
                "sensor_type": "Conductivity",
                "serial_number": "4922",
                "calibration_date": "a",
            },
        ]
        html = _render_sensor_table(info)
        # first Temperature row is primary, second secondary
        assert html.index("4798") < html.index("6435")
        assert "<td>primary</td>" in html
        assert "<td>secondary</td>" in html
        assert "Primary/secondary" in html  # the column header

    def test_single_sensor_type_has_empty_role(self):
        """A sensor type with one instance leaves the primary/secondary cell empty."""
        info = [
            {
                "sensor_type": "Pressure",
                "serial_number": "0814",
                "calibration_date": "a",
            },
        ]
        html = _render_sensor_table(info)
        assert (
            "<td>primary</td>" not in html
        )  # header says "Primary/secondary"; no cell does
        assert "<td>secondary</td>" not in html
        assert "<td></td>" in html  # empty role cell

    def test_empty_info_is_none(self):
        """No sensor info yields no table."""
        assert _render_sensor_table([]) is None
