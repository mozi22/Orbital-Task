from __future__ import annotations

import pytest

from takehome.pipeline.normalise import (
    NormalisedArea,
    UnparseableAreaError,
    UnparseableDateError,
    UnparseableMoneyError,
    UnsupportedAreaUnitError,
    UnsupportedCurrencyError,
    normalise_area,
    normalise_company_name,
    normalise_date,
    normalise_money,
)

# =============================================================================
# Dates
# =============================================================================


class TestNormaliseDate:
    def test_passes_through_an_already_iso_date(self) -> None:
        assert normalise_date("2024-01-01") == "2024-01-01"

    def test_parses_day_month_name_year(self) -> None:
        assert normalise_date("22 November 2023") == "2023-11-22"

    def test_parses_day_month_name_year_with_ordinal_suffix(self) -> None:
        assert normalise_date("1st March 2024") == "2024-03-01"
        assert normalise_date("3rd June 2024") == "2024-06-03"

    def test_parses_month_name_day_year_with_comma(self) -> None:
        assert normalise_date("November 22, 2023") == "2023-11-22"

    def test_parses_month_name_day_year_without_comma(self) -> None:
        assert normalise_date("November 22 2023") == "2023-11-22"

    def test_parses_abbreviated_month_name(self) -> None:
        assert normalise_date("22 Nov 2023") == "2023-11-22"

    def test_parses_unambiguous_numeric_date_where_first_component_exceeds_12(
        self,
    ) -> None:
        # 14 can't be a month, so this can only be 14 March 2019 (day-first).
        assert normalise_date("14/03/2019") == "2019-03-14"
        assert normalise_date("14-03-2019") == "2019-03-14"
        assert normalise_date("14.03.2019") == "2019-03-14"

    def test_parses_unambiguous_numeric_date_where_second_component_exceeds_12(
        self,
    ) -> None:
        # 25 can't be a month, so this can only be month-first: 3 June 2019.
        assert normalise_date("06/25/2019") == "2019-06-25"

    def test_resolves_genuinely_ambiguous_numeric_dates_using_uk_day_first_convention(
        self,
    ) -> None:
        # Both 03 and 04 are valid as day or month. These are UK legal
        # documents, so DD/MM/YYYY is the correct convention -- not a guess.
        assert normalise_date("03/04/2024") == "2024-04-03"
        assert normalise_date("01/02/2024") == "2024-02-01"

    def test_rejects_dates_where_neither_numeric_component_can_be_a_month(
        self,
    ) -> None:
        with pytest.raises(UnparseableDateError):
            normalise_date("13/45/2019")

    def test_rejects_invalid_calendar_dates(self) -> None:
        with pytest.raises(UnparseableDateError):
            normalise_date("31/02/2024")  # 31 February does not exist

    def test_rejects_unparseable_garbage(self) -> None:
        with pytest.raises(UnparseableDateError):
            normalise_date("some time last year")

    def test_rejects_unrecognised_month_name(self) -> None:
        with pytest.raises(UnparseableDateError):
            normalise_date("22 Smarch 2023")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(UnparseableDateError):
            normalise_date("")


# =============================================================================
# Money
# =============================================================================


class TestNormaliseMoney:
    def test_parses_pound_sign_with_commas(self) -> None:
        assert normalise_money("£4,250,000") == 425_000_000

    def test_parses_pound_sign_with_pence(self) -> None:
        assert normalise_money("£4,250,000.50") == 425_000_050

    def test_parses_gbp_prefix(self) -> None:
        assert normalise_money("GBP 1,234.56") == 123_456

    def test_parses_gbp_suffix(self) -> None:
        assert normalise_money("1,234.56 GBP") == 123_456

    def test_parses_bare_number_as_gbp(self) -> None:
        assert normalise_money("1234.5") == 123_450

    def test_parses_bare_integer_pounds(self) -> None:
        assert normalise_money("100") == 10_000

    def test_pads_single_decimal_digit_to_full_pence(self) -> None:
        assert normalise_money("£4.5") == 450

    def test_rejects_dollar_amounts(self) -> None:
        with pytest.raises(UnsupportedCurrencyError):
            normalise_money("$100")

    def test_rejects_euro_amounts(self) -> None:
        with pytest.raises(UnsupportedCurrencyError):
            normalise_money("€100")

    def test_rejects_usd_currency_code(self) -> None:
        with pytest.raises(UnsupportedCurrencyError):
            normalise_money("USD 100")

    def test_rejects_more_than_two_decimal_places(self) -> None:
        with pytest.raises(UnparseableMoneyError):
            normalise_money("£12.999")

    def test_rejects_non_numeric_garbage(self) -> None:
        with pytest.raises(UnparseableMoneyError):
            normalise_money("a lot of money")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(UnparseableMoneyError):
            normalise_money("£")

    def test_parses_gbp_suffix_with_no_separating_space(self) -> None:
        # A digit and a letter are both "word" characters, so a `\b`-anchored
        # currency marker regex doesn't match at their boundary -- this used
        # to raise UnparseableMoneyError instead of parsing.
        assert normalise_money("1234.56GBP") == 123_456


# =============================================================================
# Company names
# =============================================================================


class TestNormaliseCompanyName:
    def test_standardises_ltd_to_limited(self) -> None:
        assert (
            normalise_company_name("Victoria Park Developments Ltd")
            == "Victoria Park Developments Limited"
        )

    def test_standardises_ltd_with_trailing_period(self) -> None:
        assert (
            normalise_company_name("Victoria Park Developments Ltd.")
            == "Victoria Park Developments Limited"
        )

    def test_leaves_limited_unchanged(self) -> None:
        assert (
            normalise_company_name("Bishopsgate Property Holdings Limited")
            == "Bishopsgate Property Holdings Limited"
        )

    def test_ltd_and_limited_normalise_to_the_same_value(self) -> None:
        assert normalise_company_name("Acme Ltd") == normalise_company_name("Acme Limited")

    def test_standardises_lowercase_plc(self) -> None:
        assert normalise_company_name("Barclays Bank plc") == "Barclays Bank PLC"

    def test_standardises_llp_case(self) -> None:
        assert (
            normalise_company_name("Meridian Consulting Group Llp")
            == "Meridian Consulting Group LLP"
        )

    def test_collapses_internal_whitespace(self) -> None:
        assert normalise_company_name("Acme   Property   Ltd") == "Acme Property Limited"

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalise_company_name("  Acme Ltd  ") == "Acme Limited"

    def test_handles_a_company_number_only_value_unchanged(self) -> None:
        # Some extracted "name" values are just a bare company number, with no
        # actual name text -- there's no suffix to standardise, so it must be
        # returned unchanged rather than raising or mangling it.
        assert normalise_company_name("05198234") == "05198234"
        assert normalise_company_name("Company No. 05198234") == "Company No. 05198234"

    def test_handles_an_llp_registration_number_only_value_unchanged(self) -> None:
        assert normalise_company_name("OC412987") == "OC412987"

    def test_standardises_suffix_before_a_trailing_registration_number(self) -> None:
        # A trailing parenthetical (e.g. a registration number appended after
        # the name) used to break the suffix patterns' end-of-string anchor,
        # so the suffix inside was silently left un-standardised.
        assert (
            normalise_company_name("Acme Ltd (05198234)") == "Acme Limited (05198234)"
        )


# =============================================================================
# Areas
# =============================================================================


class TestNormaliseArea:
    def test_parses_square_metres_symbol(self) -> None:
        result = normalise_area("3,019 m²")
        assert result == NormalisedArea(value_m2=3019.0, original_value=3019.0, canonical_unit="m2")

    def test_parses_plain_m2(self) -> None:
        result = normalise_area("1200 m2")
        assert result.value_m2 == 1200.0
        assert result.canonical_unit == "m2"

    def test_converts_square_feet_to_square_metres(self) -> None:
        result = normalise_area("32,500 sq ft")
        assert result.original_value == 32500.0
        assert result.canonical_unit == "sq ft"
        # 32,500 sq ft ~= 3019.3 m^2
        assert result.value_m2 == pytest.approx(3019.3, abs=0.5)

    def test_converts_square_feet_written_out_in_full(self) -> None:
        result = normalise_area("32,500 square feet")
        # canonical_unit is a canonicalised label, not verbatim source text --
        # "square feet" and "sq ft" both fold to the same reported unit.
        assert result.canonical_unit == "sq ft"
        assert result.value_m2 == pytest.approx(3019.3, abs=0.5)

    def test_round_trips_sq_ft_and_m2_within_tolerance(self) -> None:
        sq_ft_result = normalise_area("32,500 sq ft")
        m2_result = normalise_area("3,019 m²")
        # Both describe (approximately) the same real-world area.
        assert sq_ft_result.value_m2 == pytest.approx(m2_result.value_m2, abs=1.0)

    def test_converts_hectares_to_square_metres(self) -> None:
        result = normalise_area("0.34 ha")
        assert result.original_value == 0.34
        assert result.canonical_unit == "ha"
        assert result.value_m2 == pytest.approx(3400.0)

    def test_strips_leading_approximation_qualifiers(self) -> None:
        result = normalise_area("About 32,500 sq ft")
        assert result.original_value == 32500.0
        assert result.canonical_unit == "sq ft"

    def test_retains_original_value_and_unit_alongside_normalised_value(self) -> None:
        result = normalise_area("1,200 m²")
        assert result.original_value == 1200.0
        assert result.canonical_unit == "m2"
        assert result.value_m2 == 1200.0

    def test_rejects_unrecognised_unit(self) -> None:
        with pytest.raises(UnsupportedAreaUnitError):
            normalise_area("500 furlongs")

    def test_rejects_garbage_with_no_number(self) -> None:
        with pytest.raises(UnparseableAreaError):
            normalise_area("quite large")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(UnparseableAreaError):
            normalise_area("")
