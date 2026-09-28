"""Tests for the pure lease remaining-terms extraction schema and
normalisation (issue #42). No LLM, no DB -- see
`takehome.pipeline.lease_remaining_terms`."""

from __future__ import annotations

from takehome.pipeline.lease_remaining_terms import (
    FACT_KEYS,
    Break,
    normalise_lease_remaining_terms_value,
)


def test_fact_keys_cover_exactly_the_remaining_terms_fields() -> None:
    """This ticket's scope, no more, no less -- parties/premises/term/rent/
    rent_review belong to #40, not here."""
    assert FACT_KEYS == (
        "lease.breaks",
        "lease.permitted_use",
        "lease.alienation",
        "lease.repair",
        "lease.service_charge",
        "lease.insurance",
        "lease.indemnities",
        "lease.security_of_tenure",
        "lease.dispute_resolution",
        "lease.schedules",
    )


def test_normalise_breaks_converts_dates_to_iso() -> None:
    breaks = [
        Break(
            who_can_break="tenant",
            dates=["1 January 2029", "1 January 2034"],
            notice_period_months=12,
            conditions=["No unremedied material breach", "Vacant possession"],
            break_premium="6 months' rent in cleared funds",
        )
    ]

    result = normalise_lease_remaining_terms_value("lease.breaks", breaks)

    assert result.ok is True
    assert result.normalised_value == [
        {
            "who_can_break": "tenant",
            "dates": ["2029-01-01", "2034-01-01"],
            "notice_period_months": 12,
            "conditions": ["No unremedied material breach", "Vacant possession"],
            "break_premium": "6 months' rent in cleared funds",
        }
    ]


def test_normalise_breaks_keeps_unparseable_dates_and_flags_not_ok() -> None:
    breaks = [Break(who_can_break="landlord", dates=["not a date"])]

    result = normalise_lease_remaining_terms_value("lease.breaks", breaks)

    assert result.ok is False
    assert result.normalised_value == [
        {
            "who_can_break": "landlord",
            "dates": ["not a date"],
            "notice_period_months": None,
            "conditions": [],
            "break_premium": None,
        }
    ]


def test_normalise_breaks_handles_empty_list() -> None:
    result = normalise_lease_remaining_terms_value("lease.breaks", [])

    assert result.ok is True
    assert result.normalised_value == []


def test_normalise_non_breaks_fields_is_a_no_op() -> None:
    for key in FACT_KEYS:
        if key == "lease.breaks":
            continue
        result = normalise_lease_remaining_terms_value(key, {"anything": "goes"})
        assert result.normalised_value is None
        assert result.ok is True
