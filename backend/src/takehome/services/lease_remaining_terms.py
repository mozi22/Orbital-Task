"""LLM extraction + persistence for the lease's "remaining terms" (issue
#42): breaks, permitted use, alienation, repair, service charge, insurance,
indemnities, security of tenure, dispute resolution, schedules
referenced/present.

Scoped strictly to these fields -- see
`takehome.pipeline.lease_remaining_terms`'s module docstring for why parties/
premises/term/rent/rent_review are deliberately untouched here.

Pairs with `takehome.pipeline.lease_remaining_terms` for the "AI reads, code
compares" split (requirements doc, section 6): this module is the "AI
reads" half (the LLM call) plus persistence into the shared `facts` table;
`pipeline.lease_remaining_terms` is the "code compares" half (pure
normalisation).
"""

from __future__ import annotations

import structlog
from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.config import settings  # noqa: F401 — triggers ANTHROPIC_API_KEY export
from takehome.db.models import Fact, FactStatus
from takehome.pipeline.lease_remaining_terms import (
    FACT_KEYS,
    ExtractedFact,
    LeaseRemainingTermsExtraction,
    normalise_lease_remaining_terms_value,
)

logger = structlog.get_logger()

# Sonnet, not Haiku: per the Milestone 2 PRD (section 2), misreading a
# remaining-terms clause here produces a wrong severity flag a solicitor
# relies on downstream, not just an awkward chat reply.
lease_remaining_terms_agent = Agent(
    "anthropic:claude-sonnet-4-5-20250929",
    output_type=LeaseRemainingTermsExtraction,
    system_prompt=(
        "You extract specific fields from a commercial lease's text for a "
        "law firm's risk-review pipeline. Given the lease's full extracted "
        "text (with '--- Page N ---' markers), extract exactly these "
        "fields -- nothing else (parties, premises, term, rent and rent "
        "review are handled elsewhere; do not extract them):\n\n"
        "- breaks: every break right in the lease -- who can exercise it "
        "(tenant, landlord, or either), its date(s), required notice "
        "period in months, any conditions attached to it, and any break "
        "premium payable.\n"
        "- permitted_use: the permitted use clause's text and its use "
        "class (e.g. 'Class E(g)(i)') if stated.\n"
        "- alienation: whether assignment of the whole is allowed and on "
        "what terms, whether subletting of the whole is allowed, and "
        "whether subletting of part is allowed.\n"
        "- repair: the tenant's repairing obligations, the landlord's "
        "repairing obligations, and whether a schedule of condition is "
        "referenced.\n"
        "- service_charge: the tenant's proportion (as a percentage) and "
        "any schedule reference.\n"
        "- insurance: who insures the building, what risks are covered, "
        "how many years of loss-of-rent cover apply, and the tenant's "
        "share of the premium (as a percentage).\n"
        "- indemnities: the general scope of the tenant's indemnity, the "
        "scope of any environmental indemnity, and whether that "
        "environmental indemnity is limited to contamination caused by the "
        "tenant (or those at the premises with its authority).\n"
        "- security_of_tenure: whether the lease is contracted out of "
        "security of tenure under the Landlord and Tenant Act 1954 -- "
        "'yes', 'no', or 'not_stated' if the lease never addresses it.\n"
        "- dispute_resolution: the sequence of steps required before "
        "litigation (e.g. mediation, arbitration, expert determination) "
        "and the seat/jurisdiction, if stated.\n"
        "- schedules: every schedule number/name the lease's clauses refer "
        "to (schedules_referenced), and which of those are actually "
        "attached/present in the document text you were given "
        "(schedules_present).\n\n"
        "For every field: set found=false (and leave value unset) if the "
        "lease genuinely never addresses it -- 'not_found' is a real, "
        "useful answer, never guess or invent a value. Every field you do "
        "find must include at least one source (the PDF page index, the "
        "clause reference if there is one, and an exact quote copied from "
        "the document, max 500 characters) and a confidence score from 0 "
        "to 1 reflecting how directly the text supports the value."
    ),
)


async def extract_lease_remaining_terms(text: str) -> LeaseRemainingTermsExtraction:
    """Run the lease remaining-terms extraction call against a document's
    full extracted text."""
    result = await lease_remaining_terms_agent.run(
        f"Extract the remaining terms from the following lease:\n\n{text}"
    )
    return result.output


# Confidence below this threshold is marked "needs checking" for solicitor
# review, per the requirements doc's Fact wrapper (section 7).
CONFIDENCE_NEEDS_CHECKING_THRESHOLD = 0.7


def _status_for(extracted: ExtractedFact[object], normalisation_ok: bool) -> FactStatus:
    """`not_found` is a real answer (per the requirements doc), so it's
    reported before -- and regardless of -- confidence. Otherwise, either a
    below-threshold confidence or a normalisation failure (e.g. an
    unparseable break date) demotes the fact to `needs_checking`, since
    both are equally a reason a solicitor should double-check the value."""
    if not extracted.found:
        return FactStatus.NOT_FOUND
    if extracted.confidence < CONFIDENCE_NEEDS_CHECKING_THRESHOLD or not normalisation_ok:
        return FactStatus.NEEDS_CHECKING
    return FactStatus.EXTRACTED


def build_lease_remaining_terms_facts(
    *, matter_id: str, document_id: str, extraction: LeaseRemainingTermsExtraction
) -> list[Fact]:
    """Turn one extraction result into the `Fact` rows it persists as --
    one row per field (see `FACT_KEYS`, keyed by field name -- never by
    position), each carrying its raw value, normalised value (where
    normalisation applies), sources (with `document_id` filled in, since
    the LLM call itself never sees it), a confidence score and a status.
    Doesn't touch the database itself -- see
    `extract_and_save_lease_remaining_terms` for that."""
    facts: list[Fact] = []
    for field_name, key in FACT_KEYS.items():
        extracted: ExtractedFact[object] = getattr(extraction, field_name)
        dumped = extracted.model_dump(mode="json")
        sources = [{**source, "document_id": document_id} for source in dumped["sources"]]
        normalised = normalise_lease_remaining_terms_value(key, extracted.value)

        facts.append(
            Fact(
                matter_id=matter_id,
                key=key,
                value=dumped["value"],
                normalised_value=normalised.normalised_value,
                unit=None,
                sources=sources,
                confidence=dumped["confidence"],
                status=_status_for(extracted, normalised.ok),
            )
        )
    return facts


async def extract_and_save_lease_remaining_terms(
    session: AsyncSession, *, matter_id: str, document_id: str, text: str
) -> list[Fact]:
    """Extract the lease's remaining terms from `text` and persist them as
    `Fact` rows against `matter_id`, attributed to `document_id`."""
    extraction = await extract_lease_remaining_terms(text)
    facts = build_lease_remaining_terms_facts(
        matter_id=matter_id, document_id=document_id, extraction=extraction
    )
    session.add_all(facts)
    await session.commit()
    for fact in facts:
        await session.refresh(fact)

    logger.info(
        "Extracted and saved lease remaining-terms facts",
        matter_id=matter_id,
        document_id=document_id,
        fact_count=len(facts),
    )
    return facts
