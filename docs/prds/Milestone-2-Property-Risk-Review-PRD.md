# Milestone 2 — Multi-Document Property Risk Review

Sep 26, 2026 · @Muazzam

## 1. Summary

Milestone 2 adds a **risk review** capability on top of Milestone 1's multi-document chat: a solicitor uploads a title report, a lease and an environmental report (or any subset — it isn't gated on exactly three) into a conversation, clicks **Run Risk Review**, and watches a live, per-step progress feed as the system classifies documents, extracts facts, checks the documents describe the same property, and runs the risk rule catalogue. The result renders inline in the chat as a rich, interactive report card — property summary, gate result, and a ranked list of red flags the solicitor can accept or reject — with buttons to download it as PDF or JSON.

This PRD reconciles the assignment-scoped requirements doc ([docs/property-risk-review-assignment-requirements.md](../property-risk-review-assignment-requirements.md)) — which assumed a standalone app with local JSON storage — with this project's actual codebase, so Milestone 2 is built as an extension of the existing FastAPI/SQLAlchemy/React/Postgres app rather than a parallel system. That requirements doc remains the source of truth for the **rule catalogue** (section 8), the **24-fact data model** (section 7), and the **evaluation fixtures/answer key** (section 10) — this PRD only changes *how* those get built, not *what* they are.

**Evaluation (the answer-key-based scoring script, section 10) is explicitly out of scope for this milestone — it is Milestone 3.** Milestone 2 delivers a working pipeline; Milestone 3 proves it against the graded fixtures.

## 2. Relationship to Milestone 1

- Reuses Milestone 1's multi-document conversation model, its document accordion viewer, and its `display_name`/pencil-rename UI.
- Reuses the existing PDF text-extraction code (`services/document.py`'s PyMuPDF page-by-page extraction) unchanged for the parse step.
- Reuses the existing `pydantic-ai` `Agent` pattern (`services/llm.py`) — chat Q&A stays on Haiku; risk-review extraction, gate checks and judgement-based rules use **Sonnet**, since misreading a clause here produces a wrong severity flag a solicitor relies on, not just an awkward chat reply.
- Reuses the existing SSE streaming mechanism (already used for chat token streaming) to carry pipeline progress instead.
- **Extends** Milestone 1's `Document` model with one new field: `document_type` (`title | lease | environmental | other`), auto-classified by an LLM call at upload time (applies to every upload across the app, not just matters), shown as an editable dropdown next to the existing rename pencil.

## 3. Scope

### In scope

- A `Matter` — a 1:1 extension of a `Conversation` — created when risk review is first run on that conversation.
- Auto-classification of every uploaded document's `document_type`, user-correctable.
- **Run Risk Review** button in the chat, enabled once at least one document is present. Runs against however many documents are attached — not gated on exactly three; a rule only runs when all of *its* required document types are present (per the rule catalogue's own `documents_required` field).
- Background pipeline (not synchronous — the user watches it work):
  1. Extract the 24 facts (section 7) per document type, normalising dates/money/company names in code.
  2. Run the identity gate: G-01, G-02, G-04 (section 8).
     - On fail: pause **in place**, in the same chat response — show each mismatch with sources and an inline "Continue anyway" control requiring a typed reason. No new chat message is created; the same response resumes once a reason is given.
  3. Run the 9 remaining rules (O-01, L-03, E-01, D-01, R-03, R-04, E-02, D-04, V-01), skipping any whose required documents aren't present. **All 12 rules total, no reduced fallback.**
  4. Quote-check: verify every fact/flag quote is an exact substring of the extracted PDF text; drop and log anything that doesn't verify.
  5. Build the final report (sorted by severity, `cross_document` flags labeled), always including the gate result (pass / fail-then-overridden, with reason) in its header.
- **Live progress via SSE**, per-document and per-rule granularity, e.g.:
  - "Classifying uploaded documents..."
  - "Extracting facts from lease.pdf..."
  - "Running gate check G-04: landlord vs registered owner..."
  - "Running rule O-01: mortgage predates lease..."
- **Inline report card** rendered as the assistant's response (artifact-like, not plain text): property summary, gate result, flags list with **Accept**/**Reject** per flag.
- **Evidence is clickable**: clicking a flag's evidence entry (document + page) expands that document's section in the Milestone 1 accordion and scrolls its PDF viewer to the cited page. **Page-jump only — no text highlighting** (the assignment's simplified `Source` model has no character-offset fields, so highlighting the exact quoted phrase on the page isn't buildable from this data; the assignment doc itself treats plain page-linking as sufficient).
- Two download buttons on the finished card:
  - **Download PDF** — HTML-to-PDF via WeasyPrint, reusing the same report layout/content as the inline card (one design, not two).
  - **Download JSON** — the full facts/gate/flags output in the assignment's schema (section 7), feeding Milestone 3's evaluation script.
- Unit tests (per rule function, the gate, the quote-checker, the normalisers), integration tests (the pipeline runs end-to-end against the sample fixtures without erroring and produces sane output — functional correctness, not answer-key scoring), and e2e tests (button → live progress → report card → accept/reject → both downloads).

### Out of scope (this milestone)

- The answer-key evaluation script and its pass/fail scoring against section 10's fixtures — **Milestone 3**.
- The other ~20 rules from the full product design (area mismatches, flood risk, planning expiry, Section 106, rent reviews, etc.) — assignment's own section 12.
- OCR/scanned PDFs, Word file support, documents over 50 pages.
- Draft enquiries to the seller's solicitor, a "missing information" report section, formal sign-off/approval workflow.
- Multiple properties or multiple leases per matter.
- Text-highlighting of the exact quoted phrase within a PDF page (would require extending the fact-extraction schema with character offsets).
- User accounts/login, audit logs, encryption/hosting commitments, security certification — none of this is part of the assignment's scope either.

## 4. Data model

- `Document.document_type`: new nullable enum column (`title`, `lease`, `environmental`, `other`), set automatically at upload via an LLM classification call, editable by the user afterward.
- `matters`: `id`, `conversation_id` (unique FK), `gate_result` (`pass`/`fail`/`overridden`), `gate_override_reason` (nullable), `created_at`.
- `facts`: `id`, `matter_id` FK, `key` (e.g. `lease.landlord`), `value`, `source` (document, page, clause, quote — JSON), `confidence`, `status` (`found`/`not_found`/`needs_checking`).
- `flags`: `id`, `matter_id` FK, `rule_id`, `severity`, `cross_document` (boolean), `title`, `explanation`, `why_it_matters`, `suggested_action`, `evidence` (Source[] — JSON), `review_status` (`open`/`accepted`/`rejected`).
- All new tables introduced via a new Alembic migration, following the existing `alembic/versions/` convention.

## 5. API surface (additions)

- `POST /api/conversations/{id}/risk-review` — trigger a run (creates the `Matter` if it doesn't exist, otherwise re-runs against current documents).
- SSE stream of progress events for an in-flight run (extends the existing chat-streaming mechanism).
- `PATCH /api/flags/{id}` — update `review_status` (accept/reject).
- `GET /api/matters/{id}/export?format=pdf|json` — the two download buttons.

## 6. Frontend (additions)

- **Run Risk Review** button in the chat input area.
- The response renders as a rich card component (not plain markdown) inside the message thread: header (property summary + gate result), flags grouped/sorted by severity, accept/reject controls per flag, and the two download buttons top-right of the card.
- Gate-failure state renders within that same card — mismatches, sources, and an inline "Continue anyway" + reason input. Submitting it resumes the same card through to the full report; no new message is created.
- Clicking a flag's evidence entry sets a shared "jump target" (document id + page) that the Milestone 1 document accordion listens for: it expands the matching document and scrolls its `react-pdf` viewer to that page.

## 7. Acceptance criteria

- [ ] Uploading any document (in or out of a matter context) auto-classifies its `document_type`; the user can correct it via a dropdown next to its rename pencil.
- [ ] Clicking "Run Risk Review" starts a background pipeline; the chat shows live, per-document/per-rule progress lines via SSE as it runs.
- [ ] If the gate fails, the response pauses in place showing mismatches and sources, with an inline override control requiring a typed reason; providing a reason resumes the same response through to a full report.
- [ ] If the gate passes (or is overridden), all 12 rules run (skipping any whose required document types aren't present), and every quote in every fact/flag is verified against the source PDF text before being shown.
- [ ] The finished report renders inline as an interactive card: property summary, gate result, flags sorted by severity with accept/reject controls, `cross_document` flags labeled.
- [ ] Clicking a flag's evidence entry jumps the document viewer to the cited page.
- [ ] "Download PDF" and "Download JSON" both work from the finished card.
- [ ] Unit, integration and e2e tests exist and pass for all of the above.
- [ ] No answer-key scoring, no reduced rule set, no OCR, no multi-property support is introduced this milestone.

## 8. Open items carried to Milestone 3

- The evaluation script itself: driving the real HTTP API end-to-end against the three sample fixtures (`sample-docs/`), fetching the JSON export, and scoring it against section 10's answer key — including the "AI judge" semantic-matching step for flags.
- Whatever reporting/output format that eval script produces (pass/fail per group, side-by-side expected-vs-actual for failures) is Milestone 3's own design decision, not pre-empted here.
