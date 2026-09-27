from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.db.models import Conversation, Matter

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
    same pattern `services.document.upload_document` uses for its own
    check-then-act cap check) so two concurrent first-time triggers on the
    same conversation can't both observe "no Matter yet" and both attempt to
    insert one -- without the lock, the loser would hit the `matters.
    conversation_id` unique constraint as an unhandled `IntegrityError`
    instead of transparently reusing the winner's row.
    """
    lock_stmt = (
        select(Conversation.id).where(Conversation.id == conversation_id).with_for_update()
    )
    await session.execute(lock_stmt)

    matter = await get_matter_for_conversation(session, conversation_id)
    if matter is not None:
        return matter, False

    matter = Matter(conversation_id=conversation_id, gate_result=PENDING_GATE_RESULT)
    session.add(matter)
    await session.commit()
    await session.refresh(matter)
    return matter, True
