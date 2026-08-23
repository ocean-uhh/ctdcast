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
    Acquisition,
    ProcessingChain,
    StartTime,
    build_correction_ledger,
    header_from_raw_metadata,
    parse_processing_chain,
    parse_star_block,
    parse_start_time,
)

FIXTURES_HEX = FIXTURES_CNV.parent / "hex"
NC_MIXSED_011 = FIXTURES_NC / "mixsed2_011.nc"  # stage-1 nc carrying raw_metadata
CNV_MSM121 = (
    FIXTURES_CNV.parent / "cnv_headers" / "MSM121_054_1db.cnv"
)  # wildedit after loopedit

CNV_MSM_017 = (
    FIXTURES_CNV / "msm_142_1_017_1sec.cnv"
)  # 11plus V 5.1c, +8 s, system/first_scan
CNV_MIXSED_004 = (
    FIXTURES_CNV / "mixsed2_004.cnv"
)  # 11plus V 5.2, -5 s, nmea/header, double-space NMEA
HEX_MSM_021 = (
    FIXTURES_HEX / "msm_021_1_168_short.hex"
)  # 11plus V 5.0, asymmetric advance
HEX_PS129 = FIXTURES_HEX / "PS129_014_01_short.hex"  # no deck-unit line


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
            "SBE 11plus V 5.2 deck unit: "
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
        assert ledger["correction_align"] == "deck unit: primary conductivity +0.073 s"
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
