from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.db.models import Matter
from takehome.services.conversation import lock_conversation_for_update

# Sentinel written to `gate_result` when a Matter is first created, before
# the real identity-gate logic (a later Milestone 2 ticket, see the gate
# rule tickets under M2-4) has actually run. `gate_result` is documented to
# eventually hold one of `pass`/`fail`/`overridden` -- this value is
# deliberately distinct from all three so a Matter that hasn't had a gate
# check run yet is unambiguous in the database, rather than defaulting to
# something that could be misread as a real result.
PENDING_GATE_RESULT = "pending"


async def get_matter_for_conversation(
    session: AsyncSession, conversation_id: str
) -> Matter | None:
    """Get the Matter for a conversation, if a risk review has ever run."""
    stmt = select(Matter).where(Matter.conversation_id == conversation_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_matter_by_id(session: AsyncSession, matter_id: str) -> Matter | None:
    """Get a Matter by its own id (== the trigger endpoint's `run_id`, see
    `RiskReviewTriggerResponse`). Used by the progress-events endpoint
    (issue #38) to 404 on an unknown/never-triggered run before subscribing
    it to the progress broker."""
    stmt = select(Matter).where(Matter.id == matter_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_matter(
    session: AsyncSession, conversation_id: str
) -> tuple[Matter, bool]:
    """Get the Matter for a conversation, creating it if this is the first
    risk-review run against it (see the Milestone 2 PRD: a Matter is a 1:1
    extension of a Conversation, created the first time risk review runs).

    Returns `(matter, created)` -- `created` is True only when a new row was
    inserted, so callers (the trigger endpoint) can log/report creation vs.
    re-run without a second query.

    Locks the conversation row for the duration of this check-then-act (the
    same `lock_conversation_for_update` helper `services.document.
    upload_document` uses for its own check-then-act cap check) so two
    concurrent first-time triggers on the same conversation can't both
    observe "no Matter yet" and both attempt to insert one -- without the
    lock, the loser would hit the `matters.conversation_id` unique
    constraint as an unhandled `IntegrityError` instead of transparently
    reusing the winner's row.

    Commits its own transaction on the create path (consistent with every
    other write in this codebase's service layer -- `create_conversation`,
    `update_conversation`, `upload_document`, `rename_document` all do the
    same), so the caller never needs to call `session.commit()` itself.
    That is a real constraint on composition, not just an implementation
    detail: it means a future ticket cannot fold an additional write (e.g. a
    separate per-run record) into the *same* atomic transaction as Matter
    creation without either (a) accepting two separate commits (the Matter
    row becomes visible before the second write happens, so a crash between
    them leaves a Matter with no corresponding second row), or (b) reshaping
    this function to stop committing internally and let the caller control
    the transaction boundary instead. Given every other service function
    here already commits internally and no caller today needs cross-write
    atomicity with Matter creation, that reshape is deliberately deferred
    until a ticket actually needs it, rather than done speculatively now.
    """
    await lock_conversation_for_update(session, conversation_id)

    matter = await get_matter_for_conversation(session, conversation_id)
    if matter is not None:
        return matter, False

    matter = Matter(conversation_id=conversation_id, gate_result=PENDING_GATE_RESULT)
    session.add(matter)
    await session.commit()
    await session.refresh(matter)
    return matter, True
