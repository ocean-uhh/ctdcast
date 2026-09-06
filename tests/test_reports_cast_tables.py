"""Tests for the cast-page table renderers: processing provenance and sensor roles.

These exercise the HTML builders over their display inputs (an attribute mapping, a
sensor-info list) — the rendering logic, not instrument data.
"""

from ctdcast.config.cnv_header import (
    CONFORMANCE_DIFFER,
    CONFORMANCE_MATCH,
    CONFORMANCE_NO_REFERENCE,
    ConformanceTick,
    Correction,
    SensorCalibration,
)
import xarray as xr
from conftest import FIXTURES_NC

from ctdcast.reports._cast import (
    _has_sensor_catalog,
    _render_provenance_table,
    _render_sensor_calibration_table,
    _render_sensor_catalog_table,
    _render_sensor_table,
    _render_sensors_section,
)


def _fixture_ds() -> xr.Dataset:
    """A catalog-bearing per-cast fixture (dual T/C, pH + transmissometer, applied drift)."""
    return xr.open_dataset(FIXTURES_NC / "mixsed2_011.nc", engine="netcdf4")


class TestRenderSensorCatalogTable:
    """The merged, catalog-driven sensor table (Phase 3): variable→device→calibration."""

    def test_empty_without_catalog(self):
        """A cast with no SENSOR_* catalog yields "" (the caller falls back to the header)."""
        ds = _fixture_ds()
        try:
            stripped = ds.drop_vars(
                [v for v in ds.variables if str(v).startswith("SENSOR_")]
            )
        finally:
            ds.close()
        assert _render_sensor_catalog_table(stripped) == ""
        assert _has_sensor_catalog(stripped) is False

    def test_headers_and_variable_join(self):
        """Eight columns, and each science variable joins to the device that measured it."""
        ds = _fixture_ds()
        try:
            assert _has_sensor_catalog(ds) is True
            html = _render_sensor_catalog_table(ds)
        finally:
            ds.close()
        for col in (
            "Variable",
            "Role",
            "Ch",
            "Device",
            "Model",
            "Cal date",
            "Slope",
            "Offset",
        ):
            assert f"{col}</th>" in html
        # a measured variable is joined to its device serial and model
        assert "ctd_temperature_1" in html and "SN 6435" in html
        assert "conductivity_1" in html and "SN 4922" in html
        assert "pressure" in html and "Digiquartz" in html

    def test_qc_companions_of_catalog_scalars_are_not_rendered_as_sensors(self):
        """A stage-2/3 cast has ``SENSOR_*_qc`` companions; they must not become empty rows."""
        from ctdcast.processors.stage2 import apply_stage2

        ds = _fixture_ds()
        try:
            processed = apply_stage2(ds.load())
        finally:
            ds.close()
        # stage 2 stamps a _qc companion on the SENSOR_* scalars; the table must skip them.
        assert any(
            str(v).startswith("SENSOR_") and str(v).endswith("_qc")
            for v in processed.variables
        )
        html = _render_sensor_catalog_table(processed)
        # one <tr> header + one per real sensor (11), and no blank _qc rows padding it out
        assert html.count("<tr>") == 1 + 11

    def test_variable_less_sensor_listed_with_empty_variable(self):
        """A pH sensor (no stored variable) still lists, with an em-dash Variable cell."""
        ds = _fixture_ds()
        try:
            html = _render_sensor_catalog_table(ds)
        finally:
            ds.close()
        # the pH device is present by role, and no ctdcast variable links to it
        assert ">ph<" in html
        assert "SN 339" in html  # the pH serial from the catalog
        assert "—" in html  # the empty Variable cell for a variable-less sensor

    def test_nonidentity_slope_is_amber_and_bold(self):
        """A frequency sensor with an applied drift is tinted amber and the value bolded."""
        ds = _fixture_ds()
        try:
            html = _render_sensor_catalog_table(ds)
        finally:
            ds.close()
        # the conductivity cells carry genuine drift slopes in this fixture
        assert "background:var(--warn-bg)" in html
        assert (
            "<strong>0.99993682</strong>" in html
            or "<strong>1.00000452</strong>" in html
        )
        # pressure carries both a slope and offset correction
        assert (
            "<strong>1.00004096</strong>" in html and "<strong>0.27440</strong>" in html
        )

    def test_provenance_table_carries_no_sensor_table_only_a_cross_reference(self):
        """The provenance panel holds no sensor table; it points to the Sensors appendix."""
        html = _render_provenance_table(
            [
                Correction(
                    "datcnv", "datcnv", "SBE Data Processing", "7.26", "skipover=0"
                )
            ],
            {},
            sensor_xref="calibration state is in the Sensors appendix",
        )
        assert html is not None
        assert (
            "Sensor calibration state" not in html
        )  # no calibration table in the panel
        assert "Sensors and calibration state" not in html
        assert "Sensors appendix" in html  # the one-line cross-reference


class TestRenderSensorsSection:
    """The Sensors appendix: the merged catalog table, or the pre-catalog fallback."""

    def test_catalog_cast_renders_merged_table(self):
        """A catalog-bearing cast's Sensors appendix is the merged variable→device table."""
        from types import SimpleNamespace

        ds = _fixture_ds()
        try:
            html = _render_sensors_section(SimpleNamespace(ds=ds, sensor_info=[]))
        finally:
            ds.close()
        assert html is not None
        # The merged table carries no <h3> of its own (it sits under the "Sensors" appendix
        # heading); identify it by its columns and the variable→device join.
        assert "<h3" not in html
        assert "<th>Cal date</th>" in html and "<th>Device</th>" in html
        assert "ctd_temperature_1" in html and "SN 6435" in html

    def test_precatalog_cast_falls_back_to_header_tables(self):
        """A cast with no catalog falls back to the header device list + calibration state."""
        from types import SimpleNamespace

        from ctdcast.readers.metadata import parse_sensor_info

        ds = _fixture_ds()
        try:
            stripped = ds.drop_vars(
                [v for v in ds.variables if str(v).startswith("SENSOR_")]
            )
            html = _render_sensors_section(
                SimpleNamespace(ds=stripped, sensor_info=parse_sensor_info(stripped))
            )
        finally:
            ds.close()
        assert html is not None
        assert "Sensor calibration state" in html  # header-parsed fallback
        assert (
            "Sensors and calibration state" not in html
        )  # not the merged catalog table


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


class TestConformanceColumn:
    """A "Matches reference" column, deck/celltm split and Conformance note when ticks pass."""

    def _records(self):
        return [
            Correction(
                "align (deck)", "align", "SBE 11plus deck unit", "V 5.0", "c0 +0.073 s"
            ),
            Correction("celltm", "celltm", "SBE Data Processing", "7.26", "alpha=0.03"),
        ]

    def _ticks(self):
        return [
            ConformanceTick(
                "align",
                "align",
                CONFORMANCE_MATCH,
                "0.073 s",
                "SBE manual p.85",
                "advance primary conductivity 0.073 s",
                "conductivity_1",
            ),
            ConformanceTick(
                "align",
                "align",
                CONFORMANCE_DIFFER,
                "0.073 s",
                "SBE manual p.85",
                "advance secondary conductivity 0.043 s",
                "conductivity_2",
            ),
            ConformanceTick(
                "celltm",
                "celltm",
                CONFORMANCE_NO_REFERENCE,
                "(α,τ)=(0.03,7)",
                "SBE manual p.92",
                "alpha=0.03 tau=7",
                "conductivity_1",
            ),
        ]

    def test_no_ticks_keeps_four_column_table(self):
        """Without ticks the corrections table has no Matches column (unchanged behaviour)."""
        html = _render_provenance_table(self._records(), {})
        assert "Matches reference" not in html

    def test_ticks_add_matches_column_with_status_pips(self):
        """Ticks add the column and render a coloured pip for match / differ / no-reference."""
        html = _render_provenance_table(self._records(), {}, ticks=self._ticks())
        assert "<th>Matches reference</th>" in html
        assert "conf-match" in html  # green ✓ (matches)
        assert "conf-differ" in html  # red ✗ (differs)
        assert "conf-none" in html  # neutral ringed dash (no reference)

    def test_references_move_to_a_caption(self):
        """Reference values and their sources are listed once in a caption, not per pip."""
        html = _render_provenance_table(self._records(), {}, ticks=self._ticks())
        assert "Reference values" in html
        assert "SBE manual p.85" in html  # source cited in the caption

    def test_deck_row_splits_per_channel(self):
        """The single deck-align record becomes one display row per advanced channel."""
        html = _render_provenance_table(self._records(), {}, ticks=self._ticks())
        assert "advance primary conductivity 0.073 s" in html
        assert "advance secondary conductivity 0.043 s" in html

    def test_variables_column_names_modified_variable(self):
        """The Variables column names the variable each step modified."""
        html = _render_provenance_table(self._records(), {}, ticks=self._ticks())
        assert "<th>Variables</th>" in html
        assert "conductivity_1" in html and "conductivity_2" in html

    def test_split_row_shows_its_own_value_not_the_aggregate(self):
        """Each split row shows its own channel value; the aggregate never lands on row one."""
        html = _render_provenance_table(self._records(), {}, ticks=self._ticks())
        # The secondary row shows its own advance; the record's aggregate "c0 +0.073 s"
        # string is not stuck on the first split row.
        assert "advance secondary conductivity 0.043 s" in html
        assert "c0 +0.073 s" not in html

    def test_differing_row_is_amber(self):
        """A differing (✗) conformance row is tinted with the vendored warn background."""
        html = _render_provenance_table(self._records(), {}, ticks=self._ticks())
        assert "background:var(--warn-bg)" in html

    def test_reference_and_source_are_visible(self):
        """The reference and its source are shown in the match cell, not hidden in a tooltip."""
        html = _render_provenance_table(self._records(), {}, ticks=self._ticks())
        assert "SBE manual p.85" in html
        assert "title=" not in html  # not tucked away in a hover tooltip

    def test_conformance_note_rendered(self):
        """Conformance deviation sentences render under their own heading, not Advisories."""
        html = _render_provenance_table(
            self._records(),
            {},
            ticks=self._ticks(),
            conformance=["celltm alpha 0.05 differs from 0.03 (p.92)"],
        )
        assert "<h3 style='margin-bottom:0.25rem'>Conformance</h3>" in html
        assert "celltm alpha 0.05 differs" in html

    def test_instrument_note_rendered(self):
        """An instrument note (no encoded references) appears under the corrections table."""
        html = _render_provenance_table(
            self._records(),
            {},
            instrument_note="Conformance references are not yet available for SBE 19plus.",
        )
        assert "not yet available for SBE 19plus" in html


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
