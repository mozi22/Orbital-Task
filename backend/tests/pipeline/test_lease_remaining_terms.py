"""Tests for the pure lease remaining-terms extraction schema and
normalisation (issue #42). No LLM, no DB -- see
`takehome.pipeline.lease_remaining_terms`."""

from __future__ import annotations

from takehome.pipeline.lease_remaining_terms import (
    FACT_KEYS,
    Break,
    LeaseRemainingTermsExtraction,
    normalise_lease_remaining_terms_value,
)


def test_fact_keys_cover_exactly_the_remaining_terms_fields() -> None:
    """This ticket's scope, no more, no less -- parties/premises/term/rent/
    rent_review belong to #40, not here."""
    assert FACT_KEYS == {
        "breaks": "lease.breaks",
        "permitted_use": "lease.permitted_use",
        "alienation": "lease.alienation",
        "repair": "lease.repair",
        "service_charge": "lease.service_charge",
        "insurance": "lease.insurance",
        "indemnities": "lease.indemnities",
        "security_of_tenure": "lease.security_of_tenure",
        "dispute_resolution": "lease.dispute_resolution",
        "schedules": "lease.schedules",
    }


def test_fact_keys_has_exactly_one_entry_per_extraction_field() -> None:
    """Regression guard for the mapping being keyed by field name (not
    position): every field `LeaseRemainingTermsExtraction` declares must
    have a `FACT_KEYS` entry, and vice versa -- so an added/renamed field
    that forgets to update `FACT_KEYS` (or a stale leftover entry) is
    caught immediately, regardless of either's declaration order."""
    assert set(FACT_KEYS) == set(LeaseRemainingTermsExtraction.model_fields)


def test_fact_keys_lookup_is_immune_to_field_declaration_order() -> None:
    """Regression test for the `zip(FACT_KEYS, model_fields, strict=True)`
    bug this mapping replaces: that positional pairing only ever checked
    equal *length*, so silently reordering either list would persist a
    field's value under a completely different field's key with nothing
    catching it. Walking the fields in a deliberately different order
    (reversed) confirms each field's key is resolved by looking its name
    up in `FACT_KEYS`, not by matching its position in the list."""
    field_names = list(LeaseRemainingTermsExtraction.model_fields)
    assert len(field_names) > 1  # otherwise reversal wouldn't change anything

    for field_name in reversed(field_names):
        assert FACT_KEYS[field_name] == f"lease.{field_name}"


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
    for key in FACT_KEYS.values():
        if key == "lease.breaks":
            continue
        result = normalise_lease_remaining_terms_value(key, {"anything": "goes"})
        assert result.normalised_value is None
        assert result.ok is True
