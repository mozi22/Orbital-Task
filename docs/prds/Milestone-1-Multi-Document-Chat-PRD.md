# Milestone 1 — Multi-Document Chat Upload

Sep 26, 2026 · @Muazzam

## 1. Summary

Today, a chat (conversation) in the Document Q&A tool accepts exactly one PDF, enforced by a single guard in the upload service. This milestone removes that limit so a chat can hold **up to 5 PDF documents**, lets the solicitor **rename** each document's display label after upload, and updates the Q&A prompt so the assistant can read and cite across however many documents are attached.

This milestone is a deliberate **stepping stone toward Milestone 2** (Multi-Document Property Risk Review): it proves out multi-document upload, storage, viewing and citation in the existing chat product, without building any of Milestone 2's document-typing, extraction pipeline, or cross-document rules engine. Those stay entirely out of scope here.

## 2. Why this is a stepping stone, not the finish line

The eventual product (Milestone 2) needs a title report, a lease and an environmental report all in one matter, read and cross-checked together. Before any of that rules/comparison logic can exist, the underlying chat product needs to support more than one document at all — today it structurally can't. Milestone 1 closes that gap in the smallest way that's real:

- No document type/classification (title, lease, environmental) — every document is generic.
- No cross-document comparison logic or rules — the assistant may incidentally reference multiple documents if the user asks, but there's no designed "compare these" behavior.
- No S3/cloud storage, job queue, or new services — this stays inside the existing FastAPI monolith and local disk storage.

## 3. Current state (facts, not decisions)

- DB model: `Conversation.documents` is already a `list[Document]` relationship (`db/models.py`) — the one-document limit is application logic, not a schema constraint.
- The limit is enforced in `services/document.py`'s `upload_document`, which raises on a second upload; the router maps that to HTTP 409.
- `services/llm.py`'s `chat_with_document` takes a single `document_text: str | None` — the whole document is pasted into the prompt as one `<document>` block (no chunking, no embeddings, no vector store).
- `ConversationDetail.document` (API contract) and the frontend's `useDocument` hook, `DocumentViewer`, and `DocumentUpload` are all built around exactly one document.
- No test files exist anywhere in the backend or frontend today.

## 4. Scope

### In scope

- Remove the one-document guard; enforce a **cap of 5 documents per conversation** instead (still PDF-only, still same 25 MB per-file limit as today).
- **Batch upload**: the upload widget accepts multiple dropped/selected files at once.
  - Implemented as a **client-side loop over the existing single-file upload endpoint**, fired with limited concurrency (e.g. 2–3 in flight at a time) — no new batched server endpoint.
  - **Partial accept**: files that fit under the cap and pass validation succeed; files that don't (cap exceeded, wrong type, oversized) fail independently with a clear per-file error message. One bad file never blocks the rest of the batch.
- **`display_name` field** on `Document`: defaults to the original filename at upload time (no separate naming step during upload). Editable afterward via a pencil icon next to the document's label.
- **Document viewer becomes an accordion**: one section per document, labeled with its current `display_name`, **single-expand** (opening one collapses whichever was open). A pencil icon next to each label opens inline rename editing.
- **LLM/prompt layer**: `chat_with_document` (or its replacement) accepts a list of documents, each wrapped with its `display_name` for attribution (e.g. `<document name="Lease">...</document>`). Citations in assistant responses reference the `display_name`, falling back to the original filename if never renamed.
  - **No change to the system prompt's instructions** — no added guidance encouraging cross-document comparison. Multi-document awareness is structural (the assistant *can* see multiple documents and cite them by name) but not behaviorally engineered this milestone.
- **API contract update**: `ConversationDetail.document` (singular) becomes `ConversationDetail.documents` (list). No backward-compatibility shim — this is a pre-launch project, the old singular field is removed outright.
- **Testing is a hard requirement**: unit tests (cap enforcement, partial-accept batch logic, prompt construction with N documents, rename/display_name logic), integration tests (upload → list → chat flow against a real/test DB), and end-to-end tests (drag-drop multiple files, rename via pencil, accordion expand/collapse, chat citing the right document) must all be written as part of this milestone, not deferred.

### Out of scope (explicitly deferred to Milestone 2 or later)

- Document type / classification (title, lease, environmental, unknown).
- Deleting or replacing an already-uploaded document.
- Chunking, embeddings, vector search, or any change to the "paste full text into prompt" retrieval approach.
- OCR, scanned-PDF handling changes.
- Cross-document rules, flags, severity, identity/authority gating.
- S3 or any cloud storage/job queue infrastructure — stays on local disk, in-request processing, as today.
- Word (.docx) upload support.

## 5. Data model changes

- `Document` gains `display_name: str` (not null, defaults to the uploaded filename at creation time; independently editable afterward). `filename` (the original upload name) is retained unchanged as the underlying file's real name for storage/audit purposes — `display_name` is the only thing citations and the UI show.
- No new tables. `Conversation.documents` relationship is unchanged (already a list) — only the application-layer guard changes from "reject if any document exists" to "reject if 5 documents already exist."
- New Alembic migration to add the `display_name` column, backfilled from `filename` for any existing rows.

## 6. API changes

- `POST /api/conversations/{id}/documents` — same endpoint, same single-file-per-call contract. Guard changes from "409 if any document exists" to "409 if 5 documents already exist."
- New: `PATCH /api/documents/{id}` (or similar) to update `display_name`.
- `GET /api/conversations/{id}` (and wherever `ConversationDetail` is returned) — `document` (singular, optional) replaced with `documents` (list).
- Chat/message endpoint — internally passes the full list of the conversation's documents (each with `display_name` and `extracted_text`) into the prompt-building step, instead of a single optional document.

## 7. Frontend changes

- `DocumentUpload.tsx` — accept multiple files per drop/select; upload them via a concurrency-limited client-side loop; surface per-file success/failure.
- `use-document.ts` — becomes `use-documents.ts` (or equivalent), managing a list instead of a single nullable document; exposes a rename action.
- `DocumentViewer.tsx` — restructured into an accordion (one item per document, `display_name` as the header with an inline pencil-edit affordance), single-expand behavior, each expanded item rendering the existing `react-pdf` view for that document.
- `App.tsx` and any component reading `hasDocument`/`document` singular — updated to work off the documents list (e.g. `documents.length > 0`, upload control disabled/hidden once 5 documents are attached with a "5/5 documents attached" message).

## 8. Acceptance criteria

- [ ] A conversation can hold up to 5 documents; the 6th upload attempt is rejected with a clear error, existing 5 remain untouched.
- [ ] Dropping multiple files at once uploads all that fit under the cap; files that don't fit or fail validation are reported individually without blocking the others.
- [ ] Every uploaded document defaults its `display_name` to its filename; the pencil icon lets the user rename it, and the new name persists.
- [ ] The document viewer renders as an accordion, filename-labeled by `display_name`, one section expanded at a time.
- [ ] Chat responses correctly cite the `display_name` of whichever document(s) the answer is grounded in.
- [ ] Renaming a document changes future citations to use the new name.
- [ ] Unit, integration and end-to-end tests exist and pass for all of the above.
- [ ] No document-type, deletion, cross-document rules, or cloud-storage functionality is introduced.

## 9. Open items carried to Milestone 2 discussion

- Whether/how `display_name` or document identity concepts here get reused once document typing (title/lease/environmental) is introduced.
- Milestone 2 will be scoped to a **local-only setup** (no S3, no managed job queue) given this is an interview take-home, not a production system — to be detailed in the Milestone 2 PRD.
