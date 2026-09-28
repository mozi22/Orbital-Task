"""Extraction schema + pure normalisation for the lease's "remaining terms"
(issue #42): breaks, permitted use, alienation, repair, service charge,
insurance, indemnities, security of tenure, dispute resolution, and
schedules referenced/present.

Scoped strictly to these fields -- parties, premises, term, rent and rent
review (the lease's "core terms") belong to a separate ticket (#40) and are
never read or written here, even though both extract from the same
`lease`-typed document into the same shared `facts` table.

Per the requirements doc's "AI reads, code compares" design principle
(section 6): the LLM (see `services.lease_remaining_terms`) reads the
document and returns `LeaseRemainingTermsExtraction`, a fixed structure with
a quoted source for every value. This module is the "code compares" half --
pure, LLM-free, DB-free functions that normalise the handful of raw values
in that structure that have a machine-comparable form (currently: the dates
inside `breaks[].dates`), via `takehome.pipeline.normalise`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from takehome.pipeline.normalise import NormalisationError, normalise_date

# =============================================================================
# Common building blocks
# =============================================================================


class ExtractedSourceSpan(BaseModel):
    """Where one extracted value came from, mirroring the requirements
    doc's SourceSpan (section 7) -- minus `document_id` (filled in by the
    caller, who already knows which document it extracted from) and
    `char_start`/`char_end` (only needed for PDF text-highlighting, which
    the Milestone 2 PRD explicitly puts out of scope)."""

    pdf_page_index: int = Field(description="1-based page in the PDF file")
    printed_page_label: str | None = Field(
        default=None, description='The page number printed on the page, e.g. "Page 4"'
    )
    clause_ref: str | None = Field(default=None, description='e.g. "8.3.1"')
    quote: str = Field(description="Exact text copied from the document, max 500 characters")


class ExtractedFact[T](BaseModel):
    """One field's extraction result: whether it was found at all, its raw
    value (as written in the document, `None` if not found -- "not_found"
    is a real answer, not an error), its sources, and a confidence score."""

    found: bool
    value: T | None = None
    # pyright can't fully resolve a pydantic `Field(default_factory=...)`
    # default's type inside a PEP 695 generic model; the runtime type is
    # correct (checked via the repo's own tests) and this is the only
    # affected field.
    sources: list[ExtractedSourceSpan] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


# =============================================================================
# Per-field value shapes (requirements doc, section 7, "Lease fields")
# =============================================================================


class Break(BaseModel):
    who_can_break: Literal["tenant", "landlord", "either"]
    dates: list[str] = Field(default_factory=list)
    notice_period_months: int | None = None
    conditions: list[str] = Field(default_factory=list)
    break_premium: str | None = None


class PermittedUse(BaseModel):
    text: str
    use_class: str | None = None


class Alienation(BaseModel):
    assignment: str
    sublet_whole: str
    sublet_part: str


class Repair(BaseModel):
    tenant_scope: str
    landlord_scope: str
    schedule_of_condition_referenced: bool


class ServiceCharge(BaseModel):
    tenant_proportion_percent: float | None = None
    schedule_ref: str | None = None


class Insurance(BaseModel):
    insured_by: str
    insured_risks: list[str] = Field(default_factory=list)
    loss_of_rent_years: float | None = None
    tenant_share_percent: float | None = None


class Indemnities(BaseModel):
    general_scope: str | None = None
    environmental_scope: str | None = None
    environmental_limited_to_tenant_caused: bool | None = None


class SecurityOfTenure(BaseModel):
    contracted_out_of_1954_act: Literal["yes", "no", "not_stated"]


class DisputeResolution(BaseModel):
    steps: list[str] = Field(default_factory=list)
    seat: str | None = None


class Schedules(BaseModel):
    schedules_referenced: list[str] = Field(default_factory=list)
    schedules_present: list[str] = Field(default_factory=list)


class LeaseRemainingTermsExtraction(BaseModel):
    """The full structured-output contract for the lease remaining-terms
    extraction call. One `ExtractedFact` per field this ticket is scoped
    to -- see this module's docstring for what's deliberately excluded."""

    breaks: ExtractedFact[list[Break]]
    permitted_use: ExtractedFact[PermittedUse]
    alienation: ExtractedFact[Alienation]
    repair: ExtractedFact[Repair]
    service_charge: ExtractedFact[ServiceCharge]
    insurance: ExtractedFact[Insurance]
    indemnities: ExtractedFact[Indemnities]
    security_of_tenure: ExtractedFact[SecurityOfTenure]
    dispute_resolution: ExtractedFact[DisputeResolution]
    schedules: ExtractedFact[Schedules]


# The `Fact.key` this extraction persists each field under (see
# `services.lease_remaining_terms`), keyed by the extraction model's field
# name -- an explicit mapping, not a positional list, so persistence can
# never silently mismatch a field to the wrong key if either this mapping
# or `LeaseRemainingTermsExtraction`'s field order ever changes.
FACT_KEYS: dict[str, str] = {
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


# =============================================================================
# Normalisation ("code compares")
# =============================================================================


@dataclass(frozen=True)
class NormalisedValue:
    """The result of normalising one field's raw value: the normalised
    form (`None` if nothing needed/could be normalised), and whether
    normalisation succeeded outright (`True` when there was nothing to
    normalise in the first place -- an absent or partial failure is what
    downgrades a fact to "needs checking", not a merely-unnormalised one).

    Typed as `object` rather than a narrower union: different fields
    normalise to different shapes (currently only `lease.breaks`, to a
    `list[dict[str, object]]`), and callers only ever store this
    JSON-serialised, never inspect its shape directly.
    """

    normalised_value: object | None
    ok: bool


def _normalise_break(break_: Break) -> tuple[dict[str, object], bool]:
    """Normalise one break's `dates` to ISO 8601, per the requirements
    doc's "AI reads, code compares" principle. Leaves any date that fails
    to parse as originally written (rather than dropping it) but reports
    `ok=False` so the caller can mark the fact "needs checking"."""
    normalised_dates: list[str] = []
    ok = True
    for raw_date in break_.dates:
        try:
            normalised_dates.append(normalise_date(raw_date))
        except NormalisationError:
            normalised_dates.append(raw_date)
            ok = False
    return (
        {
            "who_can_break": break_.who_can_break,
            "dates": normalised_dates,
            "notice_period_months": break_.notice_period_months,
            "conditions": break_.conditions,
            "break_premium": break_.break_premium,
        },
        ok,
    )


def normalise_lease_remaining_terms_value(key: str, value: object) -> NormalisedValue:
    """Normalise one extracted field's raw value to a machine-comparable
    form, where this ticket's fields have one.

    Only `lease.breaks` (via its `dates[]`) has a normalisable sub-value
    among this ticket's fields -- the rest (permitted use, alienation,
    repair, service charge, insurance, indemnities, security of tenure,
    dispute resolution, schedules) are already structured/categorical data
    with nothing further code can normalise, so their `normalised_value`
    is `None` and `ok` is unconditionally `True`.
    """
    if key == "lease.breaks" and isinstance(value, list):
        normalised_breaks: list[dict[str, object]] = []
        ok = True
        for item in value:  # pyright: ignore[reportUnknownVariableType]
            break_ = item if isinstance(item, Break) else Break.model_validate(item)
            normalised, break_ok = _normalise_break(break_)
            normalised_breaks.append(normalised)
            ok = ok and break_ok
        return NormalisedValue(normalised_value=normalised_breaks, ok=ok)

    return NormalisedValue(normalised_value=None, ok=True)
