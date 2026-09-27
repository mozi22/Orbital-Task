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
    # `created_at`/`updated_at` are populated by the DB via server defaults,
    # so this instance's in-memory copies are still unset until refreshed.
    # `session.refresh` expires *all* attributes on the instance before
    # reloading the ones named, which would leave `documents` expired and
    # force an un-awaitable lazy load on first access. A brand-new
    # conversation always has zero documents, so restore that in-memory
    # value directly via `set_committed_value` instead of re-fetching it.
    await session.refresh(conversation, attribute_names=["created_at", "updated_at"])
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
    # `session.refresh` expires *all* attributes first, which would otherwise
    # drop the `documents` collection eagerly loaded by `get_conversation`
    # above and force an un-awaitable lazy load on next access — so restore
    # it in-memory via `set_committed_value` rather than re-fetching it.
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
