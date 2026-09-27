from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from takehome.db.models import Conversation


async def create_conversation(session: AsyncSession) -> Conversation:
    """Create a new conversation with default title."""
    conversation = Conversation()
    session.add(conversation)
    await session.commit()
    # Postgres's implicit RETURNING on the INSERT already populates
    # `created_at`/`updated_at` in memory on commit, so no refresh is needed
    # for those. A brand-new conversation always has zero documents, and
    # that relationship was never loaded on this instance, so set it
    # directly via `set_committed_value` instead of issuing a query for it.
    set_committed_value(conversation, "documents", [])
    return conversation


async def list_conversations(session: AsyncSession) -> list[Conversation]:
    """List all conversations ordered by most recently updated."""
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.documents))
        .order_by(Conversation.updated_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_conversation(session: AsyncSession, conversation_id: str) -> Conversation | None:
    """Get a single conversation with its documents eagerly loaded."""
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.documents))
        .where(Conversation.id == conversation_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_conversation(
    session: AsyncSession, conversation_id: str, title: str
) -> Conversation | None:
    """Update the title of a conversation."""
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        return None
    conversation.title = title
    documents = conversation.documents
    await session.commit()
    # `updated_at` is bumped by the DB via `onupdate`, so refresh it here.
    # This scoped `attribute_names=[...]` refresh only expires the named
    # attributes, not `documents`, so the collection eagerly loaded by
    # `get_conversation` above isn't actually at risk here. Restoring it via
    # `set_committed_value` below is defensive belt-and-suspenders — cheap
    # insurance against that behavior changing, not a fix for a live crash.
    await session.refresh(conversation, attribute_names=["title", "updated_at"])
    set_committed_value(conversation, "documents", documents)
    return conversation


async def delete_conversation(session: AsyncSession, conversation_id: str) -> bool:
    """Delete a conversation. Returns True if it existed and was deleted."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    result = await session.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is None:
        return False
    await session.delete(conversation)
    await session.commit()
    return True
