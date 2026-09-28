"""Functional check: real extraction against the real sample lease PDF
(issue #40's acceptance criteria: "functional check against
commercial-lease-100-bishopsgate.pdf for these fields (EX-L01-EX-L11 in the
eval doc)").

Unlike every other test in this suite, this one makes a real call to the
real Anthropic API (no `FunctionModel` stub) -- there is no way to verify
genuine semantic extraction accuracy against a real document without
actually running the real model. That makes it unlike this project's
existing "integration" tests (e.g. `tests/services/test_document.py`'s
upload-classification test), which use real PDF extraction but still stub
the LLM call itself.

To keep the rest of the suite free of network calls/cost/flakiness (the
established convention -- see `conftest.py`'s placeholder
`ANTHROPIC_API_KEY`), this test is skipped unless a real key is present in
the environment. Run it explicitly with a real `ANTHROPIC_API_KEY` set to
verify extraction quality against the fixture; it is not expected to run as
part of the routine `pytest` suite or CI.

EX-L09 (schedules referenced but not attached) is deliberately not checked
here even though it falls inside the EX-L01-EX-L11 range the ticket names --
`schedules_referenced`/`schedules_present` belongs to the lease's remaining-
fields group (requirements doc section 7's last bullet), out of this
ticket's explicit scope (parties, premises, term, rent, rent_review) and
left to #42.
"""

from __future__ import annotations

import os

import fitz  # PyMuPDF
import pytest

from takehome.pipeline.extract_lease_core_terms import extract_lease_core_terms

from ..conftest import SAMPLE_LEASE_PDF_PATH as LEASE_PDF_PATH

_PLACEHOLDER_KEYS = {"", "test-placeholder-key"}

pytestmark = pytest.mark.skipif(
    os.environ.get("ANTHROPIC_API_KEY", "") in _PLACEHOLDER_KEYS,
    reason=(
        "Requires a real ANTHROPIC_API_KEY -- this test makes a real, "
        "billed LLM call and is not part of the routine test suite."
    ),
)


def _extract_page_tagged_text(pdf_path: str) -> str:
    """Extract text the same way `services.document.upload_document` does:
    each page's text prefixed with a `--- Page N ---` marker, joined with
    blank lines between pages."""
    doc = fitz.open(pdf_path)
    try:
        pages = []
        for page_num in range(len(doc)):
            text = doc[page_num].get_text()  # type: ignore[union-attr]
            if text.strip():
                pages.append(f"--- Page {page_num + 1} ---\n{text}")
        return "\n\n".join(pages)
    finally:
        doc.close()


async def test_real_extraction_against_bishopsgate_lease_matches_eval_fixture() -> None:
    text = _extract_page_tagged_text(LEASE_PDF_PATH)
    facts = await extract_lease_core_terms(text, document_id="functional-test-doc")
    by_key = {f.key: f for f in facts}

    # EX-L01: Landlord
    assert "bishopsgate property holdings" in by_key["lease.landlord.name"].value.lower()

    # EX-L02: Tenant
    assert "meridian consulting group" in by_key["lease.tenant.name"].value.lower()

    # EX-L03: Lease date
    assert by_key["lease.lease_date"].normalised_value == "2024-01-01"

    # EX-L04: Premises
    premises_text = " ".join(
        str(by_key[k].value or "")
        for k in (
            "lease.premises.description",
            "lease.premises.building_name",
            "lease.premises.building_address",
        )
    ).lower()
    assert "100 bishopsgate" in premises_text
    assert "ec2m 1gt" in premises_text.replace(" ", "").lower() or "ec2m 1gt" in premises_text

    # EX-L06: Term length
    assert by_key["lease.term.length_years"].normalised_value == 15

    # EX-L07: Term start and end
    assert by_key["lease.term.start_date"].normalised_value == "2024-01-01"
    assert by_key["lease.term.end_date"].normalised_value == "2038-12-31"

    # EX-L08: Initial rent (£850,000/year -> 85,000,000 pence)
    assert by_key["lease.rent.initial_annual_amount"].normalised_value == 85_000_000

    # EX-L10: Rent review dates
    assert by_key["lease.rent_review.dates"].normalised_value == ["2029-01-01", "2034-01-01"]

    # EX-L11: Rent review basis (open market; upward only)
    assert "open market" in by_key["lease.rent_review.basis"].value.lower()
    assert by_key["lease.rent_review.upward_only"].normalised_value is True

    # V-04's premise (no guarantor named) -- a legitimate not_found case.
    assert by_key["lease.guarantor.name"].status.value == "not_found"
