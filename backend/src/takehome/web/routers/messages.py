from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import StreamingResponse

from takehome.db.models import Message
from takehome.db.session import get_session, get_session_factory
from takehome.services.conversation import get_conversation, update_conversation
from takehome.services.document import get_documents_for_conversation
from takehome.services.llm import (
    DocumentContext,
    chat_with_documents,
    count_sources_cited,
    generate_title,
)
from takehome.web.sse import sse_event, sse_response

logger = structlog.get_logger()

router = APIRouter(tags=["messages"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    sources_cited: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
)
async def list_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    """List all messages in a conversation, ordered by creation time."""
    # Verify the conversation exists
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await session.execute(stmt)
    messages = list(result.scalars().all())

    return [
        MessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            sources_cited=m.sources_cited,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/api/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> StreamingResponse:
    """Send a user message and stream back the AI response via SSE."""
    # Verify the conversation exists
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save the user message
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=body.content,
    )
    session.add(user_message)
    await session.commit()
    await session.refresh(user_message)

    logger.info("User message saved", conversation_id=conversation_id, message_id=user_message.id)

    # Load every document attached to the conversation, wrapped with its
    # display_name for prompt attribution/citation (issue #19). Documents
    # without extracted text (e.g. extraction failed) are skipped rather than
    # handed to the model as an empty block.
    documents = await get_documents_for_conversation(session, conversation_id)
    document_contexts: list[DocumentContext] = [
        DocumentContext(display_name=d.display_name, text=d.extracted_text)
        for d in documents
        if d.extracted_text
    ]

    # Load conversation history (exclude the message we just saved, it will be the user_message param)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.id != user_message.id)
        .order_by(Message.created_at.asc())
    )
    result = await session.execute(stmt)
    history_messages = list(result.scalars().all())

    conversation_history: list[dict[str, str]] = [
        {"role": m.role, "content": m.content} for m in history_messages
    ]

    # Determine if this is the first user message (for title generation)
    user_msg_count = sum(1 for m in history_messages if m.role == "user")
    is_first_message = user_msg_count == 0

    async def event_stream() -> AsyncIterator[str]:
        """Generate SSE events with the streamed LLM response."""
        full_response = ""

        try:
            async for chunk in chat_with_documents(
                user_message=body.content,
                documents=document_contexts,
                conversation_history=conversation_history,
            ):
                full_response += chunk
                yield sse_event({"type": "content", "content": chunk})

        except Exception:
            logger.exception(
                "Error during LLM streaming",
                conversation_id=conversation_id,
            )
            error_msg = "I'm sorry, an error occurred while generating a response. Please try again."
            full_response = error_msg
            yield sse_event({"type": "content", "content": error_msg})

        # Count sources cited in the full response
        sources = count_sources_cited(full_response)

        # Save the assistant message to the database.
        # We need a fresh session since the outer one may have been closed --
        # taken from the `session_factory` dependency (not imported directly)
        # so tests overriding `get_session_factory` reach it too.
        async with session_factory() as save_session:
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_response,
                sources_cited=sources,
            )
            save_session.add(assistant_message)
            await save_session.commit()
            await save_session.refresh(assistant_message)

            # Auto-generate title from first user message
            if is_first_message:
                try:
                    title = await generate_title(body.content)
                    await update_conversation(save_session, conversation_id, title)
                    logger.info(
                        "Auto-generated conversation title",
                        conversation_id=conversation_id,
                        title=title,
                    )
                except Exception:
                    logger.exception(
                        "Failed to generate title",
                        conversation_id=conversation_id,
                    )

            # Send the final message event with the complete assistant message
            yield sse_event(
                {
                    "type": "message",
                    "message": {
                        "id": assistant_message.id,
                        "conversation_id": assistant_message.conversation_id,
                        "role": assistant_message.role,
                        "content": assistant_message.content,
                        "sources_cited": assistant_message.sources_cited,
                        "created_at": assistant_message.created_at.isoformat(),
                    },
                }
            )

            # Send the done signal
            yield sse_event(
                {
                    "type": "done",
                    "sources_cited": sources,
                    "message_id": assistant_message.id,
                }
            )

    return sse_response(event_stream())
