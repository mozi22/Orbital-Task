from __future__ import annotations

import io
from collections.abc import AsyncIterator

from fastapi import UploadFile
from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from starlette.datastructures import Headers

from takehome.db.models import Message
from takehome.services.document import upload_document
from takehome.services.llm import agent
from tests.conftest import TestSessionLocal, read_sample_pdf_bytes


def _make_upload_file(filename: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(read_sample_pdf_bytes()),
        filename=filename,
        headers=Headers({"content-type": "application/pdf"}),
    )


async def _stub_answer_from_second_document(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str]:
    """Simulate the LLM: if the prompt it was actually given contains the
    second document's marker text, answer using content only found in that
    document. Otherwise, admit it can't find the answer.

    This lets the test assert on real end-to-end plumbing (upload two
    documents with distinct content -> ask a question only the second
    document can answer -> the persisted assistant message reflects that
    document's content) without depending on a real, non-deterministic LLM
    call, per issue #19's acceptance criteria.
    """
    prompt_text = ""
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                prompt_text = part.content
    if "ENVIRONMENTAL-MARKER: no contamination detected" in prompt_text:
        yield "Per the Environmental Report, no contamination was detected."
    else:
        yield "I could not find that information."


async def test_chat_cites_content_only_found_in_the_second_uploaded_document(
    client: AsyncClient,
) -> None:
    """Issue #19 acceptance criterion: with 2 documents of distinct content
    attached, a question answerable only from the second document produces
    an answer drawing on that document's content."""
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    async with TestSessionLocal() as session:
        first = await upload_document(session, conversation_id, _make_upload_file("lease.pdf"))
        second = await upload_document(
            session, conversation_id, _make_upload_file("environmental-report.pdf")
        )

        # Overwrite extracted_text directly so each document has known,
        # distinct content regardless of what the shared sample PDF contains.
        first.extracted_text = "LEASE-MARKER: rent is $500/month."
        second.extracted_text = "ENVIRONMENTAL-MARKER: no contamination detected."
        await session.commit()

    with agent.override(model=FunctionModel(stream_function=_stub_answer_from_second_document)):
        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "Does the environmental report show any contamination?"},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.role == "assistant")
        )
        assistant_message = result.scalars().one()

    assert "no contamination was detected" in assistant_message.content
