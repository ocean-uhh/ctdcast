"""Tests for ctdcast.config.cnv_header — the '*' and start_time header parsers.

Real fixtures pin the shapes that occur in the corpus (symmetric/asymmetric deck-unit
advance, the two start-time brackets present, the double-space NMEA timestamp, and a
file with no deck-unit line). Synthetic one-line headers exercise the bracket-mapping
table for the two dialects the fixtures do not contain — these are unit-test inputs for
a text parser, not fabricated instrument data.
"""

import pytest
from conftest import FIXTURES_CNV, FIXTURES_NC

from ctdcast.config.cnv_header import (
    CONFORMANCE_DIFFER,
    CONFORMANCE_MATCH,
    CONFORMANCE_NO_REFERENCE,
    Acquisition,
    Correction,
    ProcessingChain,
    SbeHistoryNote,
    StartTime,
    _channel_kind,
    _conf_close,
    build_correction_ledger,
    conformance_advisories,
    conformance_supported,
    conformance_ticks,
    correction_records,
    detect_instrument,
    header_from_raw_metadata,
    parse_processing_chain,
    parse_star_block,
    parse_start_time,
    provenance_advisories,
    sbe_history_notes,
    sensor_calibrations,
    start_time_clock,
)

# Header-only excerpts of real files live in the tracked cnv_headers/ dir; the raw
# hex/ fixtures are local-only (git-excluded), so tests must not reach into them.
FIXTURES_HEADERS = FIXTURES_CNV.parent / "cnv_headers"
NC_MIXSED_011 = FIXTURES_NC / "mixsed2_011.nc"  # stage-1 nc carrying raw_metadata
CNV_MSM121 = FIXTURES_HEADERS / "MSM121_054_1db.cnv"  # wildedit after loopedit

CNV_MSM_017 = (
    FIXTURES_CNV / "msm_142_1_017_1sec.cnv"
)  # 11plus V 5.1c, +8 s, system/first_scan
CNV_MIXSED_004 = (
    FIXTURES_CNV / "mixsed2_004.cnv"
)  # 11plus V 5.2, -5 s, nmea/header, double-space NMEA
HEX_MSM_021 = (
    FIXTURES_HEADERS / "msm_021_1_168_header.hex.txt"
)  # 11plus V 5.0, asymmetric advance
HEX_PS129 = FIXTURES_HEADERS / "PS129_014_01_header.hex.txt"  # no deck-unit line


def _text(path) -> str:
    """Read a CNV/HEX file as latin-1 (headers are ASCII; data may hold odd bytes)."""
    return path.read_text(encoding="latin-1")


class TestParseStarBlock:
    """parse_star_block recovers the deck-unit config and clock pair."""

    def test_symmetric_advance(self):
        """A V 5.1c unit advances both conductivity channels by 0.073 s."""
        acq = parse_star_block(_text(CNV_MSM_017))
        assert acq.deck_unit.model == "SBE 11plus"
        assert acq.deck_unit.firmware == "V 5.1c"
        assert acq.deck_unit.advance["primary conductivity"] == 0.073
        assert acq.deck_unit.advance["secondary conductivity"] == 0.073
        assert acq.deck_unit.advance["voltage 0"] == 0.000
        assert acq.deck_unit.scans_averaged == 1

    def test_asymmetric_advance_v50(self):
        """The V 5.0 unit advances the two conductivity channels by DIFFERENT amounts.

        This is the case the whole parse exists for: a residual on the secondary the
        primary does not carry.
        """
        acq = parse_star_block(_text(HEX_MSM_021))
        adv = acq.deck_unit.advance
        assert acq.deck_unit.firmware == "V 5.0"
        assert adv["primary conductivity"] == 0.073
        assert adv["secondary conductivity"] == 0.043
        assert adv["primary conductivity"] != adv["secondary conductivity"]

    def test_no_deck_unit_line_is_not_an_error(self):
        """No 'SBE 11plus' line -> no model/firmware/advance, never a raise.

        Scans-averaged is a separate deck-unit line and may still be present, so the
        contract is the absence of the model and advance, not a fully-empty DeckUnit.
        """
        acq = parse_star_block(_text(HEX_PS129))
        assert acq.deck_unit.model is None
        assert acq.deck_unit.firmware is None
        assert acq.deck_unit.advance == {}

    def test_clock_offset_system_slow(self):
        """MSM142: NMEA leads system by 8 s (system clock slow relative to GPS)."""
        acq = parse_star_block(_text(CNV_MSM_017))
        assert acq.clocks.system_utc == "Apr 01 2026 18:02:29"
        assert acq.clocks.nmea_utc == "Apr 01 2026 18:02:37"
        assert acq.clocks.offset_seconds == 8.0

    def test_clock_offset_system_fast_double_space(self):
        """OdB: NMEA lags system by 5 s, and its timestamp has a double space.

        The double space must not defeat parsing (whitespace is collapsed).
        """
        acq = parse_star_block(_text(CNV_MIXSED_004))
        assert (
            acq.clocks.nmea_utc == "Jul 10 2026  08:12:49"
        )  # verbatim, double space kept
        assert acq.clocks.offset_seconds == -5.0

    def test_seasave_version(self):
        """The Seasave software version is captured verbatim."""
        acq = parse_star_block(_text(CNV_MSM_017))
        assert acq.seasave_version == "V 7.26.7.121"

    def test_verbatim_keeps_advance_lines_drops_end(self):
        """verbatim preserves the advance lines and excludes the *END* sentinel."""
        acq = parse_star_block(_text(CNV_MSM_017))
        assert "advance primary conductivity" in acq.verbatim
        assert "*END*" not in acq.verbatim
        assert acq.verbatim.splitlines()[0].startswith("*")

    def test_offset_none_when_a_clock_absent(self):
        """No NMEA UTC line -> offset is None, not a guess."""
        header = "* System UTC = Apr 01 2026 18:02:29\n"
        acq = parse_star_block(header)
        assert acq.clocks.offset_seconds is None

    def test_offset_none_when_a_clock_unparseable(self):
        """An unparseable timestamp -> offset None, and the value is kept verbatim."""
        header = "* System UTC = not a date\n* NMEA UTC (Time) = Apr 01 2026 18:02:37\n"
        acq = parse_star_block(header)
        assert acq.clocks.system_utc == "not a date"
        assert acq.clocks.offset_seconds is None

    def test_user_header_and_end_excluded_from_verbatim(self):
        """'**' user-header and '*END*' lines are excluded from verbatim."""
        header = "* SBE 11plus V 5.2\n**  Station:  004\n*END*\n"
        acq = parse_star_block(header)
        assert "SBE 11plus" in acq.verbatim
        assert "Station" not in acq.verbatim
        assert "*END*" not in acq.verbatim

    def test_returns_acquisition_type(self):
        """parse_star_block returns an Acquisition dataclass."""
        assert isinstance(parse_star_block(""), Acquisition)


class TestParseStartTime:
    """parse_start_time resolves the bracket to (clock, anchor)."""

    def test_system_first_scan(self):
        """MSM142: [System UTC, first data scan.] -> system / first_scan."""
        st = parse_start_time(_text(CNV_MSM_017))
        assert st == StartTime(
            "Apr 01 2026 18:02:29",
            "system",
            "first_scan",
            "System UTC, first data scan.",
        )

    def test_nmea_header(self):
        """OdB: [NMEA time, header] -> nmea / header."""
        st = parse_start_time(_text(CNV_MIXSED_004))
        assert st.clock == "nmea"
        assert st.anchor == "header"

    # Every bracket variant measured across the 20-file corpus, plus the degenerate
    # cases. SBE is inconsistent with its trailing period (System has one, NMEA does
    # not) and the clock/anchor combine freely, so all combinations must resolve --
    # an exact-string table resolved only 7 of 20 and missed every NMEA-anchored file.
    @pytest.mark.parametrize(
        ("bracket", "expected"),
        [
            ("NMEA time, first data scan", ("nmea", "first_scan")),
            ("System UTC, first data scan.", ("system", "first_scan")),
            ("Instrument's time stamp, header", ("instrument", "header")),
            ("NMEA time, header", ("nmea", "header")),
            ("Instrument's time stamp, first data scan", ("instrument", "first_scan")),
            ("Instrument's time stamp", ("instrument", "unknown")),  # no anchor half
            ("some future basis", ("unknown", "unknown")),  # unrecognised clock
        ],
    )
    def test_bracket_variants(self, bracket, expected):
        """Each measured bracket resolves via split-on-comma, trailing period aside."""
        st = parse_start_time(f"# start_time = Jul 10 2026 08:12:49 [{bracket}]")
        assert (st.clock, st.anchor) == expected

    def test_no_start_time_line(self):
        """A raw HEX carries no '#' block: value None, unknown / unknown."""
        st = parse_start_time(_text(HEX_PS129))
        assert st == StartTime(None, "unknown", "unknown")

    def test_bracketless_start_time_keeps_value(self):
        """A start_time with no provenance bracket still yields its timestamp value."""
        st = parse_start_time("# start_time = Jul 10 2026 08:12:49")
        assert st.value == "Jul 10 2026 08:12:49"
        assert (st.clock, st.anchor, st.source) == ("unknown", "unknown", "")

    def test_source_is_verbatim_bracket(self):
        """source holds SBE's own bracket phrasing, separate from resolved clock/anchor."""
        st = parse_start_time("# start_time = Jul 10 2026 08:12:49 [NMEA time, header]")
        assert st.source == "NMEA time, header"
        assert (st.clock, st.anchor) == ("nmea", "header")

    def test_start_time_clock_classifies_the_bracket(self):
        """start_time_clock resolves a source bracket to its clock; unknown when unparsed."""
        assert start_time_clock("System UTC, first data scan.") == "system"
        assert start_time_clock("NMEA time, header") == "nmea"
        assert start_time_clock("") == "unknown"


class TestHeaderFromRawMetadata:
    """header_from_raw_metadata pulls the verbatim header out of the JSON envelope."""

    def test_extracts_header_from_stage1_file(self):
        """A real stage-1 file's raw_metadata yields the full '*'/'#' header text."""
        import xarray as xr

        ds = xr.open_dataset(NC_MIXSED_011, engine="netcdf4")
        try:
            raw = ds.attrs.get("raw_metadata")
        finally:
            ds.close()
        header = header_from_raw_metadata(raw)
        assert header is not None
        assert header.startswith("* Sea-Bird SBE 9")
        assert "advance primary conductivity" in header

    def test_extracted_header_parses_end_to_end(self):
        """Step 0 -> Step 1: the extracted header parses to the expected deck unit.

        mixsed2_011 is an 11plus V 5.2, symmetric 0.073 s advance, NMEA/header start,
        with the system clock 3 s ahead of NMEA. The header string is LF-normalised
        (not CRLF), proving the parser handles both endings.
        """
        import xarray as xr

        ds = xr.open_dataset(NC_MIXSED_011, engine="netcdf4")
        try:
            header = header_from_raw_metadata(ds.attrs.get("raw_metadata"))
        finally:
            ds.close()
        acq = parse_star_block(header)
        assert acq.deck_unit.firmware == "V 5.2"
        assert acq.deck_unit.advance["primary conductivity"] == 0.073
        assert acq.clocks.offset_seconds == -3.0
        st = parse_start_time(header)
        assert (st.clock, st.anchor) == ("nmea", "header")

    def test_none_when_absent(self):
        """No raw_metadata (None or empty) -> None, not a raise."""
        assert header_from_raw_metadata(None) is None
        assert header_from_raw_metadata("") is None

    def test_none_when_not_json(self):
        """A non-JSON raw_metadata -> None."""
        assert header_from_raw_metadata("not json {") is None

    def test_none_when_shape_differs(self):
        """A JSON envelope without a blocks.header string -> None (shape drift)."""
        assert header_from_raw_metadata('{"schema": "x"}') is None
        assert header_from_raw_metadata('{"blocks": {"other": "None"}}') is None
        assert header_from_raw_metadata('["not", "a", "dict"]') is None

    def test_tolerates_schema_bump(self):
        """A changed schema string still yields the header if the shape is intact."""
        env = '{"schema": "seasenselib/raw-opaque-2.0", "blocks": {"header": "* SBE 11plus V 5.2\\n"}}'
        header = header_from_raw_metadata(env)
        assert header == "* SBE 11plus V 5.2\n"


def _stage1_header() -> str:
    """The verbatim header of the mixsed2_011 stage-1 fixture, via raw_metadata."""
    import xarray as xr

    ds = xr.open_dataset(NC_MIXSED_011, engine="netcdf4")
    try:
        return header_from_raw_metadata(ds.attrs.get("raw_metadata"))
    finally:
        ds.close()


class TestParseProcessingChain:
    """parse_processing_chain reads the '#' SBE Data Processing module chain."""

    def test_module_order(self):
        """Modules come back in file order, one step per module, repeats aside."""
        chain = parse_processing_chain(_stage1_header())
        assert [s.module for s in chain.steps] == [
            "datcnv",
            "wildedit",
            "wfilter",
            "filter",
            "celltm",
            "Derive",
            "binavg",
        ]

    def test_date_line_keeps_bracket_verbatim(self):
        """datcnv_date value keeps its trailing [datcnv_vars = N], split on first '='."""
        chain = parse_processing_chain(_stage1_header())
        datcnv = next(s for s in chain.steps if s.module == "datcnv")
        assert "[datcnv_vars = 15]" in datcnv.params["date"]

    def test_comma_collection_kept_in_one_value(self):
        """binavg_surface_bin keeps its internal '=' and commas as one verbatim value."""
        chain = parse_processing_chain(_stage1_header())
        binavg = next(s for s in chain.steps if s.module == "binavg")
        assert (
            binavg.params["surface_bin"]
            == "no, min = 0.000, max = 0.000, value = 0.000"
        )
        assert binavg.params["bintype"] == "decibars"

    def test_per_variable_wfilter_keys(self):
        """wfilter_action <var> lines become distinct per-variable params."""
        chain = parse_processing_chain(_stage1_header())
        wfilter = next(s for s in chain.steps if s.module == "wfilter")
        assert wfilter.params["action prDM"] == "median, 10"
        assert wfilter.params["action t090C"] == "median, 10"

    def test_wildedit_after_loopedit_real(self):
        """MSM121 runs wildedit after loopedit and celltm — order is read, not assumed."""
        chain = parse_processing_chain(CNV_MSM121.read_text(encoding="latin-1"))
        order = [s.module for s in chain.steps]
        assert order == [
            "datcnv",
            "filter",
            "alignctd",
            "celltm",
            "loopedit",
            "wildedit",
            "binavg",
        ]
        assert order.index("wildedit") > order.index("loopedit")

    def test_repeats_preserved_when_separated(self):
        """A module that runs twice with another module between yields two steps."""
        header = (
            "# bad_flag = -9.990e-29\n"
            "# wildedit_pass1_nstd = 2.0\n"
            "# celltm_alpha = 0.0300\n"
            "# wildedit_pass1_nstd = 5.0\n"
            "# file_type = ascii\n"
        )
        chain = parse_processing_chain(header)
        assert [s.module for s in chain.steps] == ["wildedit", "celltm", "wildedit"]
        assert chain.steps[0].params["pass1_nstd"] == "2.0"
        assert chain.steps[2].params["pass1_nstd"] == "5.0"

    def test_repeats_preserved_when_adjacent(self):
        """Two adjacent runs of one module (the realistic SBE case) split into two steps.

        The module name never changes between the blocks, so the boundary is the repeat
        of a field (``wildedit_date``); without it the first run's parameters would be
        silently overwritten.
        """
        header = (
            "# bad_flag = -9.990e-29\n"
            "# wildedit_date = Aug 01 2026 22:05:00, 7.26.7.129\n"
            "# wildedit_pass1_nstd = 2.0\n"
            "# wildedit_npoint = 100\n"
            "# wildedit_date = Aug 01 2026 22:09:00, 7.26.7.129\n"
            "# wildedit_pass1_nstd = 9.9\n"
            "# wildedit_npoint = 500\n"
            "# file_type = ascii\n"
        )
        chain = parse_processing_chain(header)
        assert [s.module for s in chain.steps] == ["wildedit", "wildedit"]
        assert chain.steps[0].params["pass1_nstd"] == "2.0"
        assert chain.steps[0].params["npoint"] == "100"
        assert chain.steps[1].params["pass1_nstd"] == "9.9"
        assert chain.steps[1].params["npoint"] == "500"

    def test_unrecognised_line_inside_chain_kept_in_verbatim(self):
        """A non key=value line inside the chain is kept in verbatim but adds no step."""
        header = (
            "# bad_flag = -9.990e-29\n"
            "# datcnv_date = X, 7.26.7.129\n"  # first module line enters the chain
            "# a note with no equals inside the chain\n"  # unrecognised -> verbatim only
            "a stray non-hash line\n"  # non-'#' -> skipped
            "# file_type = ascii\n"
        )
        chain = parse_processing_chain(header)
        assert [s.module for s in chain.steps] == ["datcnv"]
        assert "a note with no equals" in chain.verbatim
        assert "stray non-hash line" not in chain.verbatim  # non-'#' lines are skipped

    def test_data_table_metadata_before_bad_flag_ignored(self):
        """Lines before bad_flag (name/span) must not read as spurious modules."""
        header = (
            "# name 0 = prDM: Pressure\n"
            "# span 0 = 1, 100\n"
            "# bad_flag = -9.990e-29\n"
            "# datcnv_date = Jul 18 2026\n"
            "# file_type = ascii\n"
        )
        chain = parse_processing_chain(header)
        assert [s.module for s in chain.steps] == ["datcnv"]

    def test_empty_when_no_hash_block(self):
        """A raw HEX (no '#' block) yields an empty chain and empty verbatim."""
        chain = parse_processing_chain(_text(HEX_PS129))
        assert isinstance(chain, ProcessingChain)
        assert chain.steps == []
        assert chain.verbatim == ""

    def test_chain_captured_without_bad_flag(self):
        """A chain with no '# bad_flag' delimiter is still parsed; verbatim never vanishes.

        The chain is found by its first module line, so an SBE dialect that omits
        bad_flag keeps both the structured steps and the archival verbatim block, rather
        than reading as "nothing was done to this file".
        """
        header = (
            "# nquan = 3\n"  # data-table preamble, no bad_flag at all
            "# name 0 = prDM: Pressure\n"
            "# datcnv_date = Jul 18 2026, 7.26.7.129\n"
            "# celltm_alpha = 0.0300\n"
            "# file_type = ascii\n"
        )
        chain = parse_processing_chain(header)
        assert [s.module for s in chain.steps] == ["datcnv", "celltm"]
        assert "# datcnv_date" in chain.verbatim  # verbatim block present, not empty


class TestBuildCorrectionLedger:
    """build_correction_ledger summarises what SBE did, over the verbatim blocks."""

    def test_full_ledger_on_real_header(self):
        """mixsed2_011: order, deck align, curated corrections, time source and offset."""
        ledger = build_correction_ledger(_stage1_header())
        assert ledger["sbe_processing_order"] == (
            "align(deck) datcnv wildedit wfilter filter celltm Derive binavg"
        )
        assert ledger["correction_align"] == (
            "SBE 11plus deck unit V 5.2: "
            "primary conductivity +0.073 s, secondary conductivity +0.073 s"
        )
        assert ledger["correction_celltm"] == (
            "SBE Data Processing 7.26.7.129: alpha=0.0300, 0.0300 tau=7.0000, 7.0000"
        )
        assert ledger["correction_binavg"] == (
            "SBE Data Processing 7.26.7.129: bintype=decibars binsize=1"
        )
        assert ledger["time_coordinate_source"] == "NMEA time, header"
        assert ledger["time_clock_offset_seconds"] == -3.0
        assert ledger["sbe_acquisition"].startswith("* Sea-Bird SBE 9")
        assert "# datcnv_date" in ledger["sbe_processing"]

    def test_every_module_gets_a_correction_attr(self):
        """Every module in the chain gets a correction_ attr -- no allowlist to predict."""
        ledger = build_correction_ledger(_stage1_header())
        for module in (
            "datcnv",
            "wildedit",
            "wfilter",
            "filter",
            "celltm",
            "Derive",
            "binavg",
        ):
            assert f"correction_{module}" in ledger, module
        # a module with no salient map falls back to its own parameters
        assert ledger["correction_wfilter"].startswith(
            "SBE Data Processing 7.26.7.129: "
        )
        # Derive has only housekeeping params -> producer-only value
        assert ledger["correction_Derive"] == "SBE Data Processing 7.26.7.129"

    def test_zero_advance_records_align_but_not_in_order(self):
        """An all-zero deck advance records correction_align but no align(deck) order token.

        "Deck present, set to zero" must not read as an alignment, or a later stage would
        conclude conductivity was aligned when it was not.
        """
        header = (
            "* SBE 11plus V 5.2\n"
            "* advance primary conductivity  0.000 seconds\n"
            "* advance secondary conductivity  0.000 seconds\n"
            "# bad_flag = -9.990e-29\n"
            "# datcnv_date = Jul 18 2026, 7.26.7.129\n"
            "# file_type = ascii\n"
        )
        ledger = build_correction_ledger(header)
        assert "correction_align" in ledger  # the zero-set unit is still recorded
        assert ledger["sbe_processing_order"] == "datcnv"  # no align(deck) token
        assert "align(deck)" not in ledger["sbe_processing_order"]

    def test_adjacent_repeat_keeps_both_runs_in_ledger(self):
        """Two adjacent runs of a module become correction_<m> and correction_<m>_2.

        This is the realistic SBE case (no module between the two blocks); the first
        run's parameters must not be overwritten before the ledger suffixes them.
        """
        header = (
            "# bad_flag = -9.990e-29\n"
            "# wildedit_date = A, 7.26.7.129\n"
            "# wildedit_pass1_nstd = 2.0\n"
            "# wildedit_date = B, 7.26.7.129\n"
            "# wildedit_pass1_nstd = 5.0\n"
            "# file_type = ascii\n"
        )
        ledger = build_correction_ledger(header)
        assert "pass1_nstd=2.0" in ledger["correction_wildedit"]
        assert "pass1_nstd=5.0" in ledger["correction_wildedit_2"]
        assert ledger["sbe_processing_order"] == "wildedit wildedit"

    def test_flat_attr_matches_structured_record(self):
        """The correction_<key> flat string is the record's producer/version/params joined."""
        recs = correction_records(_stage1_header())
        ledger = build_correction_ledger(_stage1_header())
        rec = next(r for r in recs if r.key == "celltm")
        assert isinstance(rec, Correction)
        assert (
            ledger["correction_celltm"]
            == f"{rec.producer} {rec.version}: {rec.parameters}"
        )

    def test_correction_records_empty_header(self):
        """correction_records('') returns [] (no header, no corrections)."""
        assert correction_records("") == []

    def test_long_lists_summarised_not_dumped(self):
        """wildedit shows only its thresholds and wfilter collapses its repeated actions.

        The channels each step touched are named in the Variables column, so the parameter
        string no longer carries a variable count.
        """
        recs = {r.key: r for r in correction_records(_stage1_header())}
        assert recs["wildedit"].parameters == (
            "pass1_nstd=2.0 pass2_nstd=20.0 npoint=100"
        )
        assert recs["wfilter"].parameters == "excl_bad_scans=yes median, 10"
        # deck-unit record: producer/version split, not one blob
        assert recs["align"].producer == "SBE 11plus deck unit"
        assert recs["align"].version == "V 5.2"

    def test_hex_header_has_acquisition_and_offset_but_no_processing(self):
        """A raw HEX: deck/clock come from '*'; no '#' chain, so no correction_ or order."""
        ledger = build_correction_ledger(_text(HEX_PS129))
        assert "sbe_acquisition" in ledger
        assert "time_clock_offset_seconds" in ledger  # System + NMEA UTC both present
        assert "sbe_processing" not in ledger
        assert "sbe_processing_order" not in ledger
        assert not any(k.startswith("correction_") for k in ledger)
        assert "time_coordinate_source" not in ledger  # no '# start_time' line

    def test_empty_header_is_empty_ledger(self):
        """No header text -> empty ledger, so the caller can update unconditionally."""
        assert build_correction_ledger("") == {}

    def test_advance_without_deck_line_labels_bare(self):
        """An advance line with no 'SBE 11plus' model still records, label omitted."""
        ledger = build_correction_ledger(
            "* advance primary conductivity  0.073 seconds\n"
        )
        assert (
            ledger["correction_align"] == "SBE deck unit: primary conductivity +0.073 s"
        )
        assert ledger["sbe_processing_order"] == "align(deck)"

    def test_correction_value_without_version_or_body(self):
        """A correction module with only housekeeping params yields producer-only text."""
        header = (
            "# bad_flag = -9.990e-29\n"
            "# loopedit_in = C:/x.cnv\n"  # no date (no version), no salient params
            "# file_type = ascii\n"
        )
        ledger = build_correction_ledger(header)
        assert ledger["correction_loopedit"] == "SBE Data Processing"

    def test_none_header_is_empty_ledger(self):
        """build_correction_ledger(None) returns {} as documented, without raising."""
        assert build_correction_ledger(None) == {}

    def test_version_strips_bracket_before_splitting_on_comma(self):
        """A comma inside a date's [..._vars = a, b] bracket must not corrupt the version."""
        header = (
            "# bad_flag = -9.990e-29\n"
            "# celltm_date = Jul 18 2026 15:40:38, 7.26.7.129 [celltm_vars = 1, 2]\n"
            "# celltm_alpha = 0.0300\n"
            "# file_type = ascii\n"
        )
        ledger = build_correction_ledger(header)
        assert (
            ledger["correction_celltm"]
            == "SBE Data Processing 7.26.7.129: alpha=0.0300"
        )


class TestSbeHistoryNotes:
    """sbe_history_notes yields one note per timestamped SBE module, attributed to SBE."""

    def test_one_note_per_timestamped_module(self):
        """Every module in the real chain has a date, so each yields a note in file order."""
        notes = sbe_history_notes(_stage1_header())
        assert [n.stage for n in notes] == [
            "datcnv",
            "wildedit",
            "wfilter",
            "filter",
            "celltm",
            "Derive",
            "binavg",
        ]
        celltm = next(n for n in notes if n.stage == "celltm")
        assert isinstance(celltm, SbeHistoryNote)
        assert celltm.version == "7.26.7.129"
        assert celltm.note == "alpha=0.0300, 0.0300 tau=7.0000, 7.0000"
        # timestamp is the verbatim SBE stamp — no ISO 'Z'
        assert "Z" not in celltm.timestamp
        assert celltm.timestamp and celltm.timestamp[0].isalpha()

    def test_module_without_date_is_skipped(self):
        """A module with no _date line yields no note (a history line needs a stamp)."""
        header = (
            "# bad_flag = -9.990e-29\n"
            "# celltm_date = Jul 18 2026 15:40:38, 7.26.7.129\n"
            "# celltm_alpha = 0.0300\n"
            "# loopedit_in = C:/x.cnv\n"  # loopedit present but has no _date
            "# file_type = ascii\n"
        )
        assert [n.stage for n in sbe_history_notes(header)] == ["celltm"]

    def test_empty_header(self):
        """No header -> no notes."""
        assert sbe_history_notes("") == []


class TestProvenanceAdvisories:
    """provenance_advisories reports the structural implications of the ledger."""

    def test_pressure_gridded(self):
        """OdB binned to decibars -> the terminal-product advisory, and only that."""
        adv = provenance_advisories(_stage1_header())
        assert any("pressure grid" in a and "time-domain" in a for a in adv)
        assert not any("non-default" in a for a in adv)  # both channels at the default
        assert not any("system clock" in a for a in adv)  # nmea/header, not system

    def test_nondefault_advance_flagged_without_claiming_residual(self):
        """The V 5.0 deck's non-default secondary advance is flagged; primary (default) is not.

        The message must not assert a residual — a non-default advance may be intentional
        plumbing — so it hedges and points to the salinity-spike test.
        """
        adv = provenance_advisories(_text(HEX_MSM_021))
        a = next(x for x in adv if "non-default" in x)
        assert "secondary conductivity +0.043 s" in a
        assert "+0.073 s" in a  # names the factory default
        assert "primary conductivity +0.073" not in a  # primary is default, not flagged
        assert "may be deliberate or may leave a residual" in a  # hedged, not asserted

    def test_system_clock(self):
        """MSM142's system-clock start_time (with NMEA present) -> the system-clock advisory."""
        adv = provenance_advisories(_text(CNV_MSM_017))
        assert any("system clock" in a for a in adv)
        assert not any(
            "pressure grid" in a for a in adv
        )  # binavg seconds, not decibars

    def test_clean_cast_no_advisories(self):
        """A symmetric deck, seconds bin, NMEA clock -> nothing to advise."""
        header = (
            "* SBE 11plus V 5.2\n"
            "* advance primary conductivity  0.073 seconds\n"
            "* advance secondary conductivity  0.073 seconds\n"
            "# start_time = Jul 10 2026 08:12:49 [NMEA time, header]\n"
            "# bad_flag = -9.990e-29\n"
            "# binavg_bintype = seconds\n"
            "# file_type = ascii\n"
        )
        assert provenance_advisories(header) == []

    def test_empty_header(self):
        """No header -> no advisories."""
        assert provenance_advisories("") == []

    def test_offset_none_suppresses_system_clock_advisory(self):
        """A system-clock start_time with no parseable System UTC -> no offset -> no advisory.

        Guards against printing 'differed by None s' when the offset cannot be computed.
        """
        header = (
            "* NMEA UTC (Time) = Apr 01 2026 18:02:37\n"  # NMEA present, no System UTC line
            "# start_time = Apr 01 2026 18:02:37 [System UTC, first data scan.]\n"
        )
        assert not any("system clock" in a for a in provenance_advisories(header))

    def test_advance_that_rounds_to_default_not_flagged(self):
        """An advance that displays as the default (0.0731 -> 0.073) is not called non-default."""
        header = (
            "* SBE 11plus V 5.2\n"
            "* advance primary conductivity  0.0731 seconds\n"
            "* advance secondary conductivity  0.073 seconds\n"
        )
        assert not any("non-default" in a for a in provenance_advisories(header))


class TestSensorCalibrations:
    """sensor_calibrations reads frequency-sensor drift Slope/Offset from <Sensors>."""

    def test_five_frequency_sensors_in_config_order(self):
        """Temperature/conductivity/pressure are returned in config order, dual suffixed."""
        cals = sensor_calibrations(_text(CNV_MIXSED_004))
        assert [c.label for c in cals] == [
            "temperature_1",
            "conductivity_1",
            "pressure",
            "temperature_2",
            "conductivity_2",
        ]

    def test_voltage_sensors_excluded(self):
        """pH/oxygen/altimeter carry their own Slope/Offset but are not drift knobs."""
        kinds = {c.kind for c in sensor_calibrations(_text(CNV_MIXSED_004))}
        assert kinds == {"temperature", "conductivity", "pressure"}

    def test_applied_conductivity_drift_is_flagged(self):
        """mixsed2_004 carries a real bottle-derived conductivity slope on both cells."""
        cals = {c.label: c for c in sensor_calibrations(_text(CNV_MIXSED_004))}
        assert cals["conductivity_1"].slope == "1.00000452"
        assert cals["conductivity_1"].drift_applied is True
        assert cals["conductivity_2"].slope == "0.99993682"
        assert cals["conductivity_2"].drift_applied is True

    def test_identity_reads_as_no_drift(self):
        """An identity slope/offset (1.0 / 0.0) is not a drift correction."""
        cals = {c.label: c for c in sensor_calibrations(_text(CNV_MSM_017))}
        assert cals["temperature_1"].slope == "1.00000000"
        assert cals["temperature_1"].drift_applied is False
        assert cals["conductivity_1"].drift_applied is False

    def test_pressure_offset_flagged_and_kept_verbatim(self):
        """A pressure offset is flagged; the value is kept verbatim, no precision lost."""
        cals = {c.label: c for c in sensor_calibrations(_text(CNV_MSM_017))}
        assert cals["pressure"].offset == "-0.16438"
        assert cals["pressure"].drift_applied is True

    def test_serial_captured(self):
        """The sensor serial number is captured."""
        cals = {c.label: c for c in sensor_calibrations(_text(CNV_MIXSED_004))}
        assert cals["temperature_1"].serial == "4798"

    def test_reads_through_nc_raw_metadata(self):
        """Production path: the <Sensors> block travels in the nc raw_metadata attribute."""
        import xarray as xr

        ds = xr.open_dataset(NC_MIXSED_011, engine="netcdf4")
        try:
            header = header_from_raw_metadata(ds.attrs.get("raw_metadata"))
        finally:
            ds.close()
        cals = {c.label: c for c in sensor_calibrations(header)}
        assert cals["pressure"].drift_applied is True
        assert cals["temperature_1"].drift_applied is False

    def test_empty_and_missing_block_return_empty(self):
        """An empty header, or one with no <Sensors> block, yields no calibrations."""
        assert sensor_calibrations("") == []
        assert sensor_calibrations("# * System UpLoad Time = x\n# start_time = y") == []

    def test_single_sensor_keeps_bare_label(self):
        """A lone sensor of a kind keeps the bare kind label, no _1 suffix."""
        header = (
            '# <Sensors count="1" >\n'
            '#   <sensor Channel="1" >\n'
            '#     <TemperatureSensor SensorID="55" >\n'
            "#       <SerialNumber>1234</SerialNumber>\n"
            "#       <Slope>1.00000000</Slope>\n"
            "#       <Offset>0.0000</Offset>\n"
            "#     </TemperatureSensor>\n"
            "#   </sensor>\n"
            "# </Sensors>\n"
        )
        assert [c.label for c in sensor_calibrations(header)] == ["temperature"]

    def test_missing_slope_offset_defaults_to_identity(self):
        """A sensor without Slope/Offset elements reads as identity (no drift)."""
        header = (
            '# <Sensors count="1" >\n'
            '#   <sensor Channel="1" >\n'
            "#     <!-- Frequency 2, Pressure -->\n"
            '#     <PressureSensor SensorID="45" >\n'
            "#       <SerialNumber>9</SerialNumber>\n"
            "#     </PressureSensor>\n"
            "#   </sensor>\n"
            "# </Sensors>\n"
        )
        cal = sensor_calibrations(header)[0]
        assert cal.slope == "1.0"
        assert cal.offset == "0.0"
        assert cal.drift_applied is False

    def test_unreadable_slope_is_not_claimed_as_drift(self):
        """A slope that will not parse to a float is treated as identity, not a drift."""
        header = (
            '# <Sensors count="1" >\n'
            '#   <sensor Channel="1" >\n'
            "#     <!-- Frequency 1, Conductivity -->\n"
            '#     <ConductivitySensor SensorID="3" >\n'
            "#       <SerialNumber>9</SerialNumber>\n"
            "#       <Slope>abc</Slope>\n"
            "#       <Offset>0.0</Offset>\n"
            "#     </ConductivitySensor>\n"
            "#   </sensor>\n"
            "# </Sensors>\n"
        )
        assert sensor_calibrations(header)[0].drift_applied is False

    def test_malformed_xml_returns_empty(self):
        """An unparseable <Sensors> block degrades to no calibrations, not a raise."""
        header = "# <Sensors >\n#   <TemperatureSensor>\n# </Sensors>\n"
        assert sensor_calibrations(header) == []

    def test_sibling_tag_does_not_open_a_phantom_block(self):
        """A <SensorsExtra>-style sibling tag must not be read as the sensor config block."""
        header = (
            '# <SensorsExtra count="1" >\n'
            '#   <TemperatureSensor SensorID="55" >\n'
            "#     <SerialNumber>9</SerialNumber>\n"
            "#     <Slope>2.00000000</Slope>\n"
            "#   </TemperatureSensor>\n"
            "# </SensorsExtra>\n"
        )
        assert sensor_calibrations(header) == []


# Synthetic processing-chain fragments for the conformance branches the real corpus does
# not contain (celltm differ, filter with no pressure, wfilter smoother vs median).  These
# are unit-test inputs for a text parser, not fabricated instrument data.  Each carries the
# SBE 9 model line so conformance (gated to the SBE 9 family) is not short-circuited.
_SBE9 = "* Sea-Bird SBE 9 Data File:\n"
_SYNTH_CELLTM_DIFFER = (
    _SBE9 + "# celltm_alpha = 0.0500, 0.0300\n# celltm_tau = 7.0000, 7.0000\n"
)
_SYNTH_FILTER_NO_P = (
    _SBE9 + "# filter_low_pass_tc_A = 0.030\n# filter_low_pass_A_vars = t090C c0S/m\n"
)
_SYNTH_WFILTER_BOXCAR = _SBE9 + "# wfilter_action t090C = boxcar, 5\n"
_SYNTH_WFILTER_MEDIAN = _SBE9 + "# wfilter_action t090C = median, 5\n"


class TestChannelKind:
    """_channel_kind classifies SBE column names by naming convention, not CNV_ALIASES."""

    @pytest.mark.parametrize(
        ("col", "kind"),
        [
            ("t090C", "temperature"),
            ("tv290C", "temperature"),
            ("c0S/m", "conductivity"),
            ("c0mS/cm", "conductivity"),  # the MSM spelling CNV_ALIASES misses
            ("sbeox0V", "oxygen"),
            ("sbox0Mm/Kg", "oxygen"),
            ("prDM", "pressure"),
            ("sal11", None),  # salinity is not conductivity
            ("flECO-AFL", None),
            ("turbWETntu0", None),
        ],
    )
    def test_classification(self, col, kind):
        """Temperature/conductivity/oxygen/pressure are recognised; others are None."""
        assert _channel_kind(col) == kind


class TestConfClose:
    """_conf_close compares a string value to a reference within a tolerance."""

    def test_close_and_far(self):
        """A value within tol matches; outside tol does not."""
        assert _conf_close("0.152", 0.15, 0.02) is True
        assert _conf_close("0.030", 0.15, 0.02) is False

    def test_non_numeric_is_false(self):
        """An unparseable value is not close (the defensive branch)."""
        assert _conf_close("n/a", 0.15, 0.02) is False


class TestInstrumentGate:
    """detect_instrument reads the model line; conformance is gated to the SBE 9 family."""

    def test_detects_sbe9_from_real_header(self):
        """The mixsed/MSM headers name an SBE 9 on their first line."""
        assert detect_instrument(_text(CNV_MIXSED_004)) == "SBE 9"
        assert detect_instrument(_text(CNV_MSM_017)) == "SBE 9"

    def test_normalises_19plus_spacing(self):
        """``SBE19plus`` (no space) normalises to ``SBE 19plus``."""
        assert detect_instrument("* Sea-Bird SBE19plus  Data File:") == "SBE 19plus"

    def test_none_when_no_model_line(self):
        """A header with no ``* Sea-Bird`` line has no detectable instrument."""
        assert detect_instrument("# start_time = Aug 01 2026 22:05:00\n") is None
        assert detect_instrument("") is None

    def test_supported_only_for_sbe9_family(self):
        """References exist for the SBE 9 family; a 19plus is unsupported."""
        assert conformance_supported(_text(CNV_MIXSED_004)) is True
        assert conformance_supported("* Sea-Bird SBE19plus  Data File:") is False

    def test_unsupported_instrument_yields_no_conformance(self):
        """A 19plus header with a celltm block still produces no ticks or advisories."""
        header = "* Sea-Bird SBE19plus  Data File:\n# celltm_alpha = 0.0500\n"
        assert conformance_ticks(header) == []
        assert conformance_advisories(header) == []


class TestConformanceTicks:
    """conformance_ticks compares parsed parameters against documented references."""

    def test_empty_header(self):
        """An empty header yields no ticks."""
        assert conformance_ticks("") == []

    def test_deck_conductivity_matches(self):
        """A 0.073 s conductivity advance matches, and names conductivity_1 as modified."""
        ticks = {
            t.variables: t
            for t in conformance_ticks(_text(CNV_MSM_017))
            if t.label == "align"
        }
        assert ticks["conductivity_1"].state == CONFORMANCE_MATCH

    def test_deck_asymmetric_advance_differs(self):
        """The V 5.0 secondary conductivity advance (0.043 s) differs from 0.073 s."""
        align = [t for t in conformance_ticks(_text(HEX_MSM_021)) if t.label == "align"]
        by_var = {t.variables: t for t in align}
        assert by_var["conductivity_2"].state == CONFORMANCE_DIFFER
        # the voltage advance has no conductivity variable and no reference
        voltage = [t for t in align if not t.variables]
        assert voltage and voltage[0].state == CONFORMANCE_NO_REFERENCE

    def test_celltm_matches_per_cell(self):
        """celltm 0.03/7.0 matches on both cells, naming conductivity_1/_2 as modified."""
        ticks = {
            t.variables: t
            for t in conformance_ticks(_text(CNV_MIXSED_004))
            if t.label == "celltm"
        }
        assert ticks["conductivity_1"].state == CONFORMANCE_MATCH
        assert ticks["conductivity_2"].state == CONFORMANCE_MATCH

    def test_celltm_differs_per_cell_in_order(self):
        """A cell whose alpha departs differs; cells keep file order (cell 1 then cell 2)."""
        cells = [
            t for t in conformance_ticks(_SYNTH_CELLTM_DIFFER) if t.label == "celltm"
        ]
        assert cells[0].state == CONFORMANCE_DIFFER
        assert cells[1].state == CONFORMANCE_MATCH

    def test_filter_splits_and_checks_the_pressure_group(self):
        """Filter splits per low-pass group; the pressure group is checked (OdB ✓, MSM142 ✗)."""
        odb_pressure = next(
            t
            for t in conformance_ticks(_text(CNV_MIXSED_004))
            if t.label == "filter" and t.state != CONFORMANCE_NO_REFERENCE
        )
        msm_pressure = next(
            t
            for t in conformance_ticks(_text(CNV_MSM_017))
            if t.label == "filter" and t.state != CONFORMANCE_NO_REFERENCE
        )
        assert odb_pressure.state == CONFORMANCE_MATCH
        assert "pressure" in odb_pressure.variables  # prDM renamed to canonical
        assert msm_pressure.state == CONFORMANCE_DIFFER

    def test_filter_no_pressure_is_no_reference(self):
        """A filter group that does not touch pressure cannot be checked against 0.15 s."""
        ticks = conformance_ticks(_SYNTH_FILTER_NO_P)
        assert ticks[0].state == CONFORMANCE_NO_REFERENCE

    def test_rename_map_canonicalises_variables_where_aliases_miss(self):
        """The cast's cnv_original_name map renames a channel CNV_ALIASES does not cover."""
        header = (
            _SBE9
            + "# filter_low_pass_tc_A = 0.030\n# filter_low_pass_A_vars = c0mS/cm\n"
        )
        rename_map = {"c0ms/cm": "conductivity_1"}
        without = next(t for t in conformance_ticks(header) if t.label == "filter")
        with_map = next(
            t for t in conformance_ticks(header, rename_map) if t.label == "filter"
        )
        assert without.variables == "c0mS/cm"  # CNV_ALIASES has no mS/cm spelling
        assert with_map.variables == "conductivity_1"  # cast's own rename wins

    def test_filter_with_no_lowpass_channels_is_a_single_dash(self):
        """A filter step listing no low-pass channels yields one no-reference tick."""
        filt = [
            t
            for t in conformance_ticks(_SBE9 + "# filter_low_pass_tc_A = 0.5\n")
            if t.label == "filter"
        ]
        assert len(filt) == 1
        assert filt[0].state == CONFORMANCE_NO_REFERENCE

    def test_module_without_a_channel_list_has_no_variables(self):
        """A step with no per-channel field (loop edit) reports an empty Variables summary."""
        ticks = {t.label: t for t in conformance_ticks(_text(CNV_MSM121))}
        assert ticks["loopedit"].variables == ""

    def test_derive_without_a_count_has_no_variables(self):
        """A Derive step whose header omits the derived-variable count reports no Variables."""
        ticks = {
            t.label: t
            for t in conformance_ticks(
                _SBE9 + "# Derive_date = Jul 30 2026 10:33:27, 7.26.7.129\n"
            )
        }
        assert ticks["Derive"].variables == ""

    def test_wildedit_is_no_reference_with_suggested_defaults(self):
        """Wild Edit has no authoritative reference: a dash, with example defaults shown."""
        real = {t.label: t for t in conformance_ticks(_text(CNV_MIXSED_004))}
        tick = real["wildedit"]
        assert tick.state == CONFORMANCE_NO_REFERENCE
        assert "2/20/100" in tick.reference  # SBE example, shown as a suggestion
        assert "3/10/50" in tick.reference  # GEOMAR example
        assert "pass1 2.0" in tick.detail  # the cast's own values

    def test_unreferenced_module_is_dash(self):
        """A module with no documented reference (datcnv) is no_reference, never differ."""
        ticks = {t.label: t for t in conformance_ticks(_text(CNV_MIXSED_004))}
        assert ticks["datcnv"].state == CONFORMANCE_NO_REFERENCE
        assert ticks["datcnv"].variables == "all channels: raw→physical"

    def test_unparseable_celltm_value_is_no_reference(self):
        """A celltm cell whose alpha will not parse is a dash, not a differ — absent ≠ wrong."""
        cells = [
            t
            for t in conformance_ticks(
                _SBE9 + "# celltm_alpha = abc, 0.0300\n# celltm_tau = 7.0, 7.0\n"
            )
            if t.label == "celltm"
        ]
        assert cells[0].state == CONFORMANCE_NO_REFERENCE
        assert cells[1].state == CONFORMANCE_MATCH

    def test_celltm_missing_tau_is_no_reference(self):
        """A celltm cell with alpha but no tau cannot be checked: a dash, never a differ."""
        cells = [
            t
            for t in conformance_ticks(_SBE9 + "# celltm_alpha = 0.0300\n")
            if t.label == "celltm"
        ]
        assert cells[0].state == CONFORMANCE_NO_REFERENCE


class TestConformanceAdvisories:
    """conformance_advisories reports deviations as hedged, source-citing prose."""

    def test_empty_header(self):
        """An empty header yields no advisories."""
        assert conformance_advisories("") == []

    def test_odb_flags_oxygen_and_loopedit_but_not_tc_smoothing(self):
        """OdB: oxygen not aligned + no loop edit fire; wfilter median is NOT a T/C smooth."""
        adv = " ".join(conformance_advisories(_text(CNV_MIXSED_004)))
        assert "oxygen" in adv.lower()
        assert "Loop Edit" in adv
        assert "smoothed" not in adv  # median despiking must not read as smoothing

    def test_msm142_flags_tc_smoothing(self):
        """MSM142's low-pass filter on t090C/c0mS/cm is a real T/C smoothing flag."""
        adv = " ".join(conformance_advisories(_text(CNV_MSM_017)))
        assert "smoothed" in adv
        assert "pressure only" in adv

    def test_msm121_oxygen_aligned_and_loopedit_present(self):
        """MSM121 aligns oxygen and runs loop edit, so neither advisory fires."""
        adv = " ".join(conformance_advisories(_text(CNV_MSM121)))
        assert "oxygen" not in adv.lower()
        assert "Loop Edit" not in adv

    def test_wfilter_smoother_flags_tc(self):
        """A wfilter boxcar (a smoother) on temperature does trip the T/C-smoothing flag."""
        adv = conformance_advisories(_SYNTH_WFILTER_BOXCAR)
        assert any("smoothed" in a for a in adv)

    def test_wfilter_median_does_not_flag(self):
        """A wfilter median (spike removal) on temperature does not trip the flag."""
        assert conformance_advisories(_SYNTH_WFILTER_MEDIAN) == []

    def test_differing_tick_becomes_prose(self):
        """A differing parameter tick is surfaced as a hedged sentence citing its source."""
        adv = conformance_advisories(_text(CNV_MSM_017))
        assert any("confirm against this cast's configuration" in a for a in adv)
