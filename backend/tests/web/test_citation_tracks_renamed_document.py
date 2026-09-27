from __future__ import annotations

import re
from collections.abc import AsyncIterator

from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from takehome.services.llm import agent
from tests.conftest import read_sample_pdf_bytes

_DOCUMENT_NAME_RE = re.compile(r'<document name="([^"]*)">')


async def _stub_echo_document_name(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str]:
    """Simulate the LLM by reflecting back whatever `display_name` the
    `<document name="...">` tag it was actually given in the prompt carries.

    This lets the test assert on the real prompt-building plumbing (the
    document's *current* `display_name` at the moment a question is asked,
    per issue #22) rather than depending on a real, non-deterministic LLM
    call.
    """
    prompt_text = ""
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                prompt_text = part.content
    match = _DOCUMENT_NAME_RE.search(prompt_text)
    name = match.group(1) if match else "UNKNOWN"
    yield f"Per {name}, the answer is on file."


async def test_citation_uses_renamed_display_name_after_rename(
    client: AsyncClient,
) -> None:
    """Issue #22 acceptance criterion: after renaming a document (via 3.1),
    asking a new question in the same conversation produces a citation using
    the new name, not the old name/filename."""
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    upload_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[("file", ("lease.pdf", read_sample_pdf_bytes(), "application/pdf"))],
    )
    assert upload_resp.status_code == 201, upload_resp.text
    document_id = upload_resp.json()["id"]
    assert upload_resp.json()["display_name"] == "lease.pdf"

    # Ask a question before renaming -- the prompt/citation should use the
    # original filename-derived display_name.
    with agent.override(model=FunctionModel(stream_function=_stub_echo_document_name)):
        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "What is the rent?"},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    messages_before = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assistant_message_before = next(m for m in messages_before if m["role"] == "assistant")
    assert "Per lease.pdf" in assistant_message_before["content"]

    # Rename the document (3.1's endpoint).
    patch_resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "Lease Agreement (Final)"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    # Ask a *new* question in the same conversation -- the citation must now
    # reflect the renamed display_name, not the old filename.
    with agent.override(model=FunctionModel(stream_function=_stub_echo_document_name)):
        async with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "What is the security deposit?"},
        ) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    messages_after = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assistant_messages_after = [m for m in messages_after if m["role"] == "assistant"]
    assert len(assistant_messages_after) == 2
    latest_assistant_message = assistant_messages_after[-1]

    assert "Per Lease Agreement (Final)" in latest_assistant_message["content"]
    assert "lease.pdf" not in latest_assistant_message["content"]
