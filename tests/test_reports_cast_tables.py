"""Tests for the cast-page table renderers: processing provenance and sensor roles.

These exercise the HTML builders over their display inputs (an attribute mapping, a
sensor-info list) — the rendering logic, not instrument data.
"""

from ctdcast.config.cnv_header import Correction
from ctdcast.reports._cast import _render_provenance_table, _render_sensor_table


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
