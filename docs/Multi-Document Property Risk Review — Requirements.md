# Multi-Document Property Risk Review — Requirements

Sep 26, 2026 · @Muazzam

## 1. Summary

We are building a system that reads several property documents about one deal and returns a single risk report. Every flag in the report points to the exact page and clause it came from, and a solicitor approves or rejects each one before anything leaves the firm.

The MVP (minimum viable product, meaning the smallest version worth shipping) takes three document types for one UK property:

- **Title report** (who owns the land, what debts and restrictions sit on it)
- **Lease** (who rents it, for how long, on what terms)
- **Environmental report** (ground pollution, flood risk, history of the site)

It produces:

- A one-page property summary (parties, key dates, rent, areas)
- A list of red flags, each with severity, risk type, a plain-English explanation, and source references
- Cross-document clashes, meaning problems that only appear when two documents are compared
- Draft questions to send to the seller's solicitor

The core idea: most tools read one document at a time. Solicitors lose the most time, and face the most liability, when they have to hold three documents in their head and spot where they contradict each other. That comparison is what this system does best.

**Guiding rules for the build agent:**

1. Never state a fact without a source reference (document, page, clause, and the quoted text).
2. Never send anything outside the system. The solicitor decides what goes to a client.
3. When unsure, flag it as "needs checking" rather than guessing or staying silent.
4. Check that the documents belong to the same property before running any other check.
5. Write every output in plain English. Legal terms are allowed only with a short explanation.

## 2. The problem and why it matters

Property solicitors spend a large share of every deal reading documents line by line and writing up what's wrong. The work is repetitive, slow, and high-risk.

**Why it hurts:**

- **It takes hours.** One commercial property can mean a 60-page lease, a title with decades-old restrictions, and a technical environmental report. A portfolio deal repeats this for every property, often against a deadline.
- **Missing something is expensive.** Overlooking a break clause, a building-height restriction or a contamination risk is a classic reason solicitors get sued. So they check everything twice, which doubles the time.
- **The hardest part is comparison.** Many serious problems don't live in any single document. They appear only when one document contradicts another. Examples from our test set:
  - The lease names a landlord who is not the owner on the title.
  - The title bans buildings above four storeys, but the lease covers floors 8 to 10.
  - The lease makes the tenant pay for pollution the tenant causes, but the environmental report shows pollution from 30 years earlier, which falls on the owner.
- **Existing tools stop at one document.** Most tools summarise or extract from a single file. Cross-checking is left to a tired human at the end of the day.

**Why this is worth building first:**

- The same review step sits inside almost every property workflow: buying, selling, refinancing, lending, leasing and development. Build it once and it serves all of them.
- The inputs and outputs are clear and bounded: documents in, list of issues out.
- It's low-risk to adopt because a human reviews every flag. Nothing is sent or filed automatically.
- It extends the existing DayOne residential work (the Day 0 title brief) into commercial property, adding lease and environmental review plus cross-checking.

## 3. Users, use cases and workflows served

### Users

| User                         | What they need                                                                 | How they use the system                                                      |
| ---------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| Property solicitor (primary) | A reliable first-pass review with sources, so they can check fast and sign off | Uploads documents, reviews each flag, accepts or rejects, exports the report |
| Trainee or paralegal         | A structured starting point and a way to learn what matters                    | Runs the review, prepares the draft for a senior solicitor                   |
| Supervising partner          | Confidence that nothing was missed                                             | Reads the final approved report and the audit trail                          |

The client, lender and seller's solicitor never use the system directly. They only receive what the solicitor chooses to send.

### Core use case (MVP)

1. The solicitor creates a matter (one property, one transaction).
2. They upload a title report, a lease and an environmental report as PDFs.
3. The system confirms the documents belong to the same property and parties. If they don't, it stops and says why.
4. The system extracts key facts and runs single-document and cross-document checks.
5. The solicitor sees a summary plus a ranked list of flags, each linked to the exact source text.
6. The solicitor accepts, edits or rejects each flag and adds notes.
7. The solicitor exports the approved flags as a report and a list of questions for the seller.

### Workflows this core step serves

The review engine is the same across all of these. Only the input set and the final output differ.

| Workflow                              | Documents usually involved                                | Output the solicitor needs                                 |
| ------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| Buying a tenanted investment property | Title, lease(s), environmental                            | Report on title for the buyer, seller enquiries            |
| Refinancing or new loan               | Title, lease(s), environmental                            | Lender sign-off (certificate of title)                     |
| Granting or taking a lease            | Title, draft lease, environmental                         | Advice to landlord or tenant                               |
| Buying a development site             | Title, planning documents, environmental, existing leases | Feasibility risks, demolition and vacant possession issues |
| Selling (seller's pack)               | Title, lease(s), environmental                            | Issues to fix before marketing                             |
| Portfolio acquisition                 | All of the above, for many properties                     | Risk summary across the portfolio                          |

The MVP targets the first two rows. The data model must not assume only these two, so later workflows can be added without a rewrite.

## 4. Scope

The MVP is one matter, one property, three documents, England and Wales law, reviewed by one solicitor.

### In scope (MVP)

- UK commercial property in England and Wales
- One property per matter
- One document of each type: title report (Land Registry official copy or title summary), one lease, one Phase I environmental report
- Text-based PDFs, plus scanned PDFs through OCR (optical character recognition, meaning turning an image of text into real text)
- Fact extraction into a fixed schema (section 7)
- Identity and authority gate (section 6, stage 3)
- Single-document checks and cross-document checks from the rule catalogue (section 8)
- Risk report with source references, severity and plain-English explanations (section 9)
- Draft enquiries (questions) for the seller's solicitor
- A review screen where the solicitor accepts, edits or rejects each flag (section 10)
- Export of the approved report as PDF and Word (.docx)
- A full audit log of who changed what and when

### Out of scope (MVP)

- Sending anything to clients, lenders or other solicitors. The system produces drafts only.
- Filing with HM Land Registry or any other authority
- Valuation advice. The system may show numbers that look inconsistent, but must not say what a property is worth.
- Scotland and Northern Ireland (different property law)
- Residential conveyancing (covered by DayOne)
- Multiple properties or multiple leases per matter (planned for phase 2)
- Other document types: planning decisions, searches, surveys, Section 106 agreements as separate files, management packs
- Negotiating or redrafting documents
- Integrations with practice management systems or email

### Assumptions

- Users are qualified solicitors or supervised staff, and they remain legally responsible for the advice given.
- Documents are in English.
- A title report may be a summary rather than the full official register, so the system must say when it is working from a summary.
- Plans, schedules and annexes are often missing from uploads. The system must detect and flag this rather than assume their content.

## 5. Input documents

The system accepts three document types in the MVP. It must detect the type automatically and let the user correct it.

| Type                           | What it is                                                                            | Typical length  | Typical sections to find                                                                                                                                                                              |
| ------------------------------ | ------------------------------------------------------------------------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Title report                   | Land Registry record or summary of who owns the land and what's registered against it | 2 to 15 pages   | Property description, owner (proprietorship), price paid, charges (mortgages), restrictive covenants, easements, noted entries, cautions and restrictions                                             |
| Lease                          | Contract letting all or part of a property to a tenant                                | 20 to 150 pages | Parties, definitions, premises, term, rent, rent review, repair, insurance, use, alienation (transfers and sublets), break clause, indemnities, dispute resolution, schedules, execution (signatures) |
| Environmental report (Phase I) | Desk-based study of contamination, flood and site history                             | 10 to 80 pages  | Site description, history, geology, water, flood zone, regulatory records, findings, recommendations, cost estimates, reliance statement                                                              |

### Handling requirements

- **Formats:** PDF (text or scanned). Word (.docx) is a nice-to-have.
- **Size:** up to 300 pages and 50 MB per file.
- **Type detection:** classify each file as title, lease, environmental or "unknown" with a confidence score. Below 80% confidence, ask the user to confirm.
- **Page mapping:** keep the original page number for every piece of extracted text, so references match what the solicitor sees in the PDF. Documents often print their own page numbers ("Page 4"). Store both the PDF page index and the printed page label.
- **Structure:** keep clause numbers (for example 8.3.1) and section headings, because solicitors cite by clause.
- **Missing parts:** detect when a document refers to schedules, plans or annexes that aren't in the file. Record each as a missing item, because it may hide a risk.
- **Signatures:** detect whether signature blocks are blank or completed, and whether a date is filled in.
- **Date of document:** record the document date and the "as at" date (for a title report, the time the register was checked).
- **Duplicate or wrong uploads:** warn if two files are the same type, or if a file looks like none of the three types.

## 6. Processing pipeline

Every matter runs through nine stages in order. The gate at stage 4 stops the run if the documents don't describe the same property, so no later check runs on mismatched papers.

&#91;embedded content: review pipeline · 9 stages, 1 gate\]

Cross-document checks (highlighted) are the main differentiator and get the most engineering effort.

### Design principle: AI reads, code compares

- Use a large language model (LLM) to **read** documents and pull out facts into a fixed structure, always with the quoted source text.
- Use ordinary code to **compare** those facts wherever possible (names, dates, numbers, areas). Code comparisons are repeatable and testable.
- Use the LLM for **judgement checks** only where wording matters (for example, "does this covenant forbid the use the lease allows?"). Every judgement must return a quote from each document it relied on.
- A second LLM pass (a "verifier") re-reads each flag against its quoted source and drops or downgrades any flag the source doesn't support.

### Stage details

1. **Upload and create matter**
   - Create a matter record: name, reference, transaction type (purchase or refinance in MVP), client side (buyer or lender).
   - Store the original files unchanged, with a content hash (a fingerprint that detects any change to the file).
2. **Classify and parse**
   - Detect document type (section 5). Run OCR if a page has no text layer.
   - Split into pages and clauses. Keep PDF page index, printed page label, clause number and heading for every text span.
   - Detect missing schedules, plans and annexes, and blank signature blocks.
3. **Extract key facts**
   - Fill the data model in section 7. Every value carries its source (document, page, clause, exact quote) and a confidence score from 0 to 1.
   - Normalise values so code can compare them: dates as YYYY-MM-DD, money in pence (GBP), areas in square metres (keep the original unit too), company names with suffixes standardised ("Ltd" = "Limited"), company numbers as digits only, postcodes in standard format.
   - Values below 0.7 confidence are marked "needs checking" and shown to the solicitor.
4. **Identity and authority gate**
   - Compare property identity across documents: address, postcode, title number, description, site area, number of storeys, floor area.
   - Compare party chain: lease landlord vs title owner, environmental report client vs title owner or buyer.
   - Result is **pass**, **warn** (minor differences such as an abbreviated address), or **fail** (different property or unrelated owner).
   - On fail: stop, show a mismatch report listing each mismatch with sources. The solicitor may override with a written reason, which is logged. Overrides are needed for testing and for genuine cases such as a missing intermediate lease.
5. **Single-document checks**
   - Run every single-document rule in the catalogue (section 8) for the document types present.
6. **Cross-document checks**
   - Run every cross-document rule for each pair of documents present, then any rule needing all three.
7. **Build risk report**
   - Merge duplicate flags (the same underlying issue found by two rules). Keep all sources.
   - Rank by severity, then by risk type order in section 8.
   - Write a plain-English explanation and a suggested next step for each flag.
   - Generate draft enquiries for the seller's solicitor from flags marked as needing seller input.
8. **Solicitor review** (section 10)
9. **Export**
   - Export approved flags only, as PDF and Word. Rejected flags never appear in exports but stay in the audit log.

### Re-runs

- Replacing a document re-runs stages 2 to 7 for the whole matter.
- A solicitor's decision on a flag is kept if the same flag (same rule, same sources) appears again. New or changed flags are marked "new since last run".

## 7. Extracted facts data model

Every fact the system extracts has the same wrapper: a value, a normalised value, its sources, a confidence score and a status. The per-document fields below sit inside that wrapper.

### Common building blocks

**SourceSpan** (where a fact came from)

| Field                | Type           | Notes                                                   |
| -------------------- | -------------- | ------------------------------------------------------- |
| document_id          | string         | Which uploaded file                                     |
| pdf_page_index       | integer        | 1-based page in the PDF file                            |
| printed_page_label   | string or null | The page number printed on the page, e.g. "Page 4"      |
| clause_ref           | string or null | e.g. "8.3.1", "Charges Register entry 1"                |
| quote                | string         | Exact text copied from the document, max 500 characters |
| char_start, char_end | integer        | Position in the page text, for highlighting             |

**Fact** (wrapper for every extracted value)

| Field            | Type           | Notes                                                                |
| ---------------- | -------------- | -------------------------------------------------------------------- |
| key              | string         | Field name from the lists below, e.g. lease.term.end_date            |
| value            | any            | As written in the document                                           |
| normalised_value | any            | Machine-comparable form (ISO date, pence, m², standard company name) |
| unit             | string or null | e.g. GBP, m2, sq ft, years                                           |
| sources          | SourceSpan\[\] | At least one, always                                                 |
| confidence       | number 0–1     | Below 0.7 = needs checking                                           |
| status           | enum           | extracted, needs_checking, not_found, edited_by_user                 |

"not_found" is a real answer, not an error. Many risks come from something being absent (no lender consent, no contracting-out of the 1954 Act).

### Title report fields

- title_number, edition_date, as_at_datetime, is_summary (true if not the full official register)
- tenure (freehold or leasehold), title_class (e.g. absolute)
- property: address, postcode, description, site_area_m2, boundaries (north, east, south, west), buildings (storeys, gross_internal_area_m2, use)
- registered_owner: name, company_number, registered_office, registered_since
- price_paid: amount, date
- charges\[\]: entry_number, date, lender_name, lender_company_number, secures_further_advances
- restrictive_covenants\[\]: date, parties, full_text, category (use, height, boundary, building, other), parsed_limits (e.g. max_storeys: 4, banned_uses: \[industrial, manufacturing, heavy commercial\])
- easements\[\]: type (right_of_way, drainage, light, support, other), benefit_or_burden, route_description, obligations
- noted_entries\[\]: type (planning_permission, s106_agreement, lease, other), reference, date, summary, obligations\[\] (type, amount, units, description)
- cautions_and_restrictions\[\]: text (empty list is meaningful)

### Lease fields

- lease_date, execution_status (signed, unsigned, partly signed), is_dated
- landlord, tenant, guarantor: name, company_or_llp_number, registered_office
- premises: description, floors, net_internal_area (value + unit), building_name, building_address
- term: length_years, start_date, end_date
- rent: initial_annual_amount, vat_exclusive, payment_frequency, payment_dates
- rent_review: dates\[\], basis (open market, index, fixed), upward_only
- breaks\[\]: who_can_break (tenant, landlord, either), dates\[\], notice_period_months, conditions\[\], break_premium
- permitted_use: text, use_class
- alienation: assignment (allowed with consent / not allowed), sublet_whole, sublet_part
- repair: tenant_scope, landlord_scope, schedule_of_condition_referenced
- service_charge: tenant_proportion_percent, schedule_ref
- insurance: insured_by, insured_risks\[\], loss_of_rent_years, tenant_share_percent
- indemnities: general_scope, environmental_scope, environmental_limited_to_tenant_caused (true or false)
- security_of_tenure: contracted_out_of_1954_act (yes, no, not_stated)
- dispute_resolution: steps\[\] (mediation, arbitration, expert), seat
- schedules_referenced\[\] and schedules_present\[\]

### Environmental report fields

- report_reference, report_date, consultant, authors, client_name
- reliance: who_may_rely (named parties), third_party_reliance_allowed (true or false)
- site: address, postcode, area_m2, buildings (storeys, gross_internal_area_m2, construction_year)
- historical_uses\[\]: from_year, to_year, use, potentially_contaminative (true or false)
- geology_summary, aquifer_classification, nearest_watercourse (name, distance_m)
- flood_zone (1, 2, 3), flood_defences (true or false)
- contaminated_land_register_status, pollution_incidents\[\] (year, type, distance_m, status)
- air_quality_management_area (true or false)
- storage_tanks\[\]: location, contents, capacity_litres, status (removed, in situ, unknown)
- overall_risk_rating, recommendations\[\]
- cost_estimates\[\]: item, low_amount, high_amount, vat_exclusive

### Flag (one risk in the report)

| Field            | Type           | Notes                                                                      |
| ---------------- | -------------- | -------------------------------------------------------------------------- |
| flag_id          | string         | Unique                                                                     |
| rule_id          | string         | From section 8, e.g. X-01                                                  |
| risk_type        | enum           | One of the 7 types in section 8                                            |
| severity         | enum           | critical, high, medium, low, info                                          |
| scope            | enum           | single_document or cross_document                                          |
| title            | string         | Short headline, max 90 characters                                          |
| explanation      | string         | Plain English, 1–3 sentences                                               |
| why_it_matters   | string         | Consequence for the client, 1–2 sentences                                  |
| suggested_action | string         | What the solicitor should do next                                          |
| enquiry_text     | string or null | Draft question for the seller's solicitor                                  |
| evidence         | SourceSpan\[\] | At least one per document involved                                         |
| confidence       | number 0–1     | From the verifier pass                                                     |
| review_status    | enum           | open, accepted, edited, rejected                                           |
| solicitor_note   | string or null | Free text                                                                  |
| fingerprint      | string         | rule_id + hashes of evidence quotes, used to keep decisions across re-runs |

### Example flag

```
{
  "flag_id": "f_0012",
  "rule_id": "X-01",
  "risk_type": "ownership_and_authority",
  "severity": "critical",
  "scope": "cross_document",
  "title": "Landlord named in the lease is not the registered owner",
  "explanation": "The lease is granted by Bishopsgate Property Holdings Limited, but the title shows Victoria Park Developments Ltd as owner.",
  "why_it_matters": "Only the owner, or someone holding a lease from the owner, can grant a valid lease. The tenancy and its rent may not bind the owner.",
  "suggested_action": "Ask for evidence of the landlord's interest, such as an intermediate lease or a transfer not yet registered.",
  "enquiry_text": "Please explain how Bishopsgate Property Holdings Limited was entitled to grant the lease dated 1 January 2024 and supply copies of any superior lease.",
  "evidence": [
    {"document_id": "lease", "pdf_page_index": 3, "clause_ref": "1.1", "quote": "\"the Landlord\" means Bishopsgate Property Holdings Limited (Company No. 05198234)"},
    {"document_id": "title", "pdf_page_index": 1, "clause_ref": "Registered Owner", "quote": "Victoria Park Developments Ltd (Company No. 08234571)"}
  ],
  "confidence": 0.97,
  "review_status": "open"
}
```

## 8. Risk taxonomy and rule catalogue

Every flag belongs to one of seven risk types and comes from one rule in this catalogue. Rules are stored as data (for example YAML files), not hard-coded, so new rules can be added and tuned without changing the pipeline.

### Risk types

| Order | Risk type                    | Question it answers                                         | Mostly matters to           |
| ----- | ---------------------------- | ----------------------------------------------------------- | --------------------------- |
| 1     | Identity                     | Are these documents about the same property?                | Everyone; blocks the review |
| 2     | Ownership and authority      | Does the seller or landlord have the right to do this deal? | Buyer, lender               |
| 3     | Document reliability         | Can we trust and rely on these papers?                      | Solicitor (liability)       |
| 4     | Land restrictions and rights | What must the owner do, not do, or allow?                   | Buyer, developer            |
| 5     | Environmental                | Is there a hidden clean-up or flood cost, and who pays?     | Buyer, lender               |
| 6     | Development and planning     | Can the owner carry out their plans?                        | Developer, lender           |
| 7     | Income and value             | Is the income as secure as it looks?                        | Investor, lender            |

### Severity levels

| Severity | Meaning                                                            |
| -------- | ------------------------------------------------------------------ |
| Critical | The deal cannot safely continue until this is resolved             |
| High     | Must be resolved, insured or priced before contracts are exchanged |
| Medium   | Raise a question with the seller's solicitor; report to client     |
| Low      | Mention in the report                                              |
| Info     | Useful context, not a problem on its own                           |

Severity in the catalogue is a default. A rule may raise or lower it based on the facts (for example, a flood zone 3 is higher than zone 2).

### Rule format

Each rule defines: rule_id, name, risk_type, scope (single or cross), documents_required, inputs (fact keys), method (code, llm_judgement, or both), logic description, default severity, and templates for the title, explanation, why it matters, suggested action and enquiry. A rule only runs when all its required documents are present. If an input fact is "not_found", the rule must decide explicitly whether that is itself a flag.

Method meanings: **code** = compare normalised facts with fixed logic; **LLM** = a model reads the quoted clauses and answers a fixed yes/no/unclear question with quotes; **both** = code narrows the candidates, the model confirms.

### 1. Identity (gate rules)

| ID   | Check                                                                                                                             | Documents    | Method | Default severity |
| ---- | --------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------ | ---------------- |
| G-01 | Address, postcode and title number match (fuzzy match; "Ltd"/"Limited", abbreviations and floor prefixes ignored)                 | All          | Code   | Critical         |
| G-02 | Building storeys agree, and any floors let in the lease exist in the building                                                     | All          | Code   | Critical         |
| G-03 | Site and floor areas agree within 10%; lease area ÷ service charge % gives an implied building size that fits the other documents | All          | Code   | High             |
| G-04 | Lease landlord is the title owner, or a link between them is shown                                                                | Lease, title | Both   | Critical         |

### 2. Ownership and authority

| ID   | Check                                                                                                | Documents    | Method | Default severity |
| ---- | ---------------------------------------------------------------------------------------------------- | ------------ | ------ | ---------------- |
| O-01 | A mortgage (charge) on the title predates the lease, and no lender consent to the lease is evidenced | Title, lease | Code   | High             |
| O-02 | Owner's company number and name are consistent wherever they appear                                  | All          | Code   | Medium           |
| O-03 | Title has restrictions or cautions limiting sale or letting                                          | Title        | Code   | High             |

### 3. Document reliability

| ID   | Check                                                                                                                     | Documents               | Method | Default severity |
| ---- | ------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------ | ---------------- |
| R-01 | Title report is older than another document in the set, or more than 30 days older than the review date                   | Title + any             | Code   | High             |
| R-02 | Lease longer than 7 years is dated after the title's "as at" date or is not noted on the title (needs registration check) | Title, lease            | Code   | High             |
| R-03 | Environmental report can only be relied on by a party other than the client or buyer                                      | Environmental (+ title) | Both   | High             |
| R-04 | Lease signature blocks are blank or the lease is undated                                                                  | Lease                   | Code   | High             |
| R-05 | Schedules, plans or annexes are referenced but missing                                                                    | Any                     | Code   | Medium           |
| R-06 | Title document is a summary, not an official copy of the register                                                         | Title                   | Code   | Medium           |
| R-07 | Environmental report is more than 12 months old                                                                           | Environmental           | Code   | Low              |

### 4. Land restrictions and rights

| ID   | Check                                                                               | Documents            | Method | Default severity |
| ---- | ----------------------------------------------------------------------------------- | -------------------- | ------ | ---------------- |
| L-01 | Permitted use in the lease is allowed by the title's use covenants                  | Lease, title         | LLM    | High             |
| L-02 | Past uses in the environmental report would have breached title use covenants       | Environmental, title | LLM    | Low              |
| L-03 | Building height, floors let, or planned storeys exceed a height covenant            | All                  | Code   | High             |
| L-04 | Right-of-way route agrees with the property's boundaries and road frontage          | Title                | LLM    | Medium           |
| L-05 | An easement (e.g. a sewer) crosses areas where works are recommended or planned     | Title, environmental | LLM    | Medium           |
| L-06 | Positive covenants on the title (e.g. fencing) and who carries them under the lease | Title, lease         | LLM    | Low              |

### 5. Environmental

| ID   | Check                                                                                                                    | Documents               | Method | Default severity         |
| ---- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------- | ------ | ------------------------ |
| E-01 | Contamination that predates the lease is not covered by the tenant's environmental indemnity, so it stays with the owner | Environmental, lease    | Both   | High                     |
| E-02 | Underground or above-ground storage tank of unknown status                                                               | Environmental           | Code   | High                     |
| E-03 | Further investigation is recommended; report the cost ranges quoted                                                      | Environmental           | Code   | Medium                   |
| E-04 | Site in flood zone 2 or 3 without defences; show tenant's share of insurance if a lease exists                           | Environmental (+ lease) | Code   | Medium (High for zone 3) |
| E-05 | Planned residential or other sensitive use on a site with contamination risk                                             | Title, environmental    | Both   | High                     |
| E-06 | Principal aquifer below a site with potential contamination                                                              | Environmental           | Code   | Medium                   |

### 6. Development and planning

| ID   | Check                                                                                                            | Documents    | Method | Default severity |
| ---- | ---------------------------------------------------------------------------------------------------------------- | ------------ | ------ | ---------------- |
| D-01 | Planning permission to demolish or redevelop, but a lease runs past the likely start date with no landlord break | Title, lease | Code   | Critical         |
| D-02 | Planning permission may expire; show the date 3 years after grant                                                | Title        | Code   | Medium           |
| D-03 | Section 106 obligations bind the buyer; total the payments and affordable units                                  | Title        | Code   | Medium           |
| D-04 | Lease doesn't state it is excluded from the 1954 Act, so the tenant may have a right to renew                    | Lease        | LLM    | High             |

### 7. Income and value

| ID   | Check                                                                                       | Documents    | Method | Default severity |
| ---- | ------------------------------------------------------------------------------------------- | ------------ | ------ | ---------------- |
| V-01 | Tenant break options: show the first break date, the premium, and the certain income period | Lease        | Code   | Medium           |
| V-02 | Rent review basis and dates (note upward-only)                                              | Lease        | Code   | Info             |
| V-03 | Price paid and rent imply a yield outside 3%–12%; refer to a valuer, never state a value    | Title, lease | Code   | Low              |
| V-04 | No guarantor and no rent deposit                                                            | Lease        | Code   | Low              |

### Rule-writing guardrails

- A rule never states a legal conclusion as certain. It uses "may", "appears" or "check whether" when the documents alone can't settle it.
- A rule never gives a property valuation or tax advice.
- Every LLM rule answers yes, no or unclear. "Unclear" creates a flag with severity lowered by one level and the note "needs checking".

## 9. Risk report output

The report has six parts, always in this order. Each part must be readable on its own by a busy partner.

1. **Header**
   - Matter name and reference, property address, transaction type, review date, reviewer name
   - Documents reviewed: type, file name, document date, page count
   - Gate result (pass, warn, fail, or overridden with the reason)
   - Status line: "Draft: not approved" until the solicitor approves; then "Approved by \[name\] on \[date\]"
2. **Headline**
   - Count of flags by severity (for example: 3 critical, 6 high, 5 medium, 3 low)
   - The top 3 issues in one sentence each
3. **Property summary** (key facts table)
   - Owner, landlord, tenant, lender
   - Tenure, title number, site and floor areas
   - Lease term, start and end dates, rent, review dates, break dates, break premium
   - Covenants and easements in one line each
   - Environmental risk rating, flood zone, recommended investigations and cost ranges
   - Planning permissions and Section 106 obligations
   - Every value shows its source reference as a link, and any value that differs across documents is highlighted
4. **Red flags**, grouped by risk type (section 8 order), sorted by severity within each group. Each flag shows:
   - Severity badge, rule ID, title
   - Explanation and why it matters
   - Evidence: one quote per document with document name, page and clause, each clickable to open the PDF at that spot
   - Suggested action
   - Label "Cross-document" where two or more documents are involved
5. **Missing information**
   - Missing schedules, plans, annexes, signatures
   - Facts the system could not find ("not_found") that matter for a rule
   - Low-confidence facts still marked "needs checking"
6. **Draft enquiries** for the seller's solicitor
   - Numbered, grouped by document, each linked to the flag it came from
   - Written in the formal style used between solicitors

### Writing style for all generated text

- Plain English, short sentences (under 25 words), active voice.
- Explain any legal term the first time it appears, in brackets.
- Name documents, parties and dates exactly as the documents do.
- Never overstate: use "appears to", "may" or "check whether" when the documents don't settle a point.
- No advice on value, tax or anything outside the documents.

### Export formats

- PDF and Word (.docx), approved flags only.
- JSON (machine-readable) with all facts and flags, for testing and future integrations.
- Export includes a footer: "Prepared with the assistance of \[product name\]. Reviewed and approved by \[solicitor\]."

## 10. Solicitor review experience

The review screen is where the product earns trust. The solicitor must be able to check any flag against its source in under 30 seconds.

### Screens

1. **Matter list:** all matters with status (processing, needs review, approved), flag counts by severity, last updated.
2. **Upload screen:** drag and drop, detected document type with confidence, option to correct the type, progress per stage.
3. **Gate result screen** (only on warn or fail): side-by-side table of the mismatched facts with sources. Buttons: "Replace a document" or "Continue anyway" (reason required).
4. **Review screen** (main screen), in three panels:
   - Left: flag list, filterable by severity, risk type, scope (single or cross), and review status.
   - Middle: the selected flag, with explanation, evidence quotes, suggested action and enquiry text, all editable.
   - Right: the PDF viewer, opened at the cited page with the quoted text highlighted. For cross-document flags, show a tab per document or split the panel.
5. **Facts screen:** the property summary as an editable table. Editing a fact re-runs the rules that use it.
6. **Export screen:** preview, approval, then download.

### Actions on each flag

- **Accept:** keep as written.
- **Edit:** change severity, text or enquiry. The original is kept in the audit log.
- **Reject:** remove from the report with a reason from a short list (wrong, not relevant, already resolved, duplicate) plus optional free text. Rejection reasons feed quality metrics (section 14).
- **Add a manual flag:** the solicitor can add an issue the system missed, with their own evidence. These are counted as misses for quality tracking.

### Rules for the review flow

- The report can't be approved while any critical or high flag is still "open".
- Keyboard shortcuts for accept (A), reject (R), next (J), previous (K).
- Approval records the solicitor's name, time and the exact version approved.
- Nothing is sent from the system. Export is the only way content leaves it.

## 11. Non-functional requirements

These are the qualities the system must have regardless of features. Targets are for the MVP and will tighten later.

| Area                              | Requirement                                                                                 | MVP target                                 |
| --------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Traceability                      | Every fact and flag has at least one source quote that exists word for word in the document | 100%, checked automatically before display |
| Accuracy: critical and high flags | Share of real critical/high issues found (recall)                                           | At least 95% on the test set               |
| Accuracy: false alarms            | Share of shown flags the solicitor rejects as wrong                                         | Under 20%                                  |
| Speed                             | Time from upload to review-ready for a 100-page set                                         | Under 5 minutes                            |
| Speed                             | Review screen actions (open flag, jump to PDF)                                              | Under 1 second                             |
| Repeatability                     | Same documents give the same flags on a re-run                                              | At least 95% identical flag set            |
| Availability                      | Service uptime during UK working hours                                                      | 99.5%                                      |

### Security and confidentiality

- Client documents are confidential and may be legally privileged (protected from disclosure). Treat every file as highly sensitive.
- Encrypt data in transit (TLS 1.2 or later) and at rest (AES-256).
- Host all data and processing in the UK or EU.
- Use only AI model providers contractually committed to not training on customer data, with zero or short data retention.
- Each law firm's data is fully separated from every other firm's (tenant isolation).
- Role-based access: solicitor, supervisor, firm admin. Access is limited to matters a user is assigned to.
- Single sign-on (SSO) with Microsoft 365 as a nice-to-have; multi-factor authentication required.
- Audit log of every view, edit, decision, export and override, kept for at least 7 years (in line with typical file-retention periods for solicitors).
- Firms can delete a matter and all its data; deletion is logged.

### Regulatory context

- Solicitors in England and Wales are regulated by the SRA (Solicitors Regulation Authority). The solicitor, not the software, is responsible for the advice. The product must support supervision, not replace it.
- UK GDPR applies to any personal data in documents (for example names of individuals). Keep a data processing agreement template ready.
- Aim for Cyber Essentials Plus in year one; ISO 27001 later. Firms will ask.

### Reliability of AI output

- A quote-check step rejects any fact or flag whose quote is not found in the source text.
- Model name, version, prompt version and rule version are stored with every run, so results can be reproduced and explained.
- If a model call fails or times out, retry up to 3 times, then mark the affected facts "needs checking" rather than dropping them silently.

## 12. Suggested architecture

This is a recommended starting point, not a fixed decision. The build agent may change any component if it explains why in the repo's decision log. The one fixed rule: extraction, rules and reporting must stay separate modules so each can be tested alone.

### Components

| Component       | Suggested choice                                                                                                                                                             | Why                                               |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Web app         | React with TypeScript (e.g. Next.js), PDF.js for the viewer                                                                                                                  | Mature PDF highlighting; fast review UI           |
| API             | Python with FastAPI                                                                                                                                                          | Best libraries for PDF parsing and AI work        |
| Background jobs | A job queue (e.g. Celery, RQ or Temporal)                                                                                                                                    | Pipeline stages take minutes; must retry safely   |
| Database        | PostgreSQL, with facts and flags stored as JSON columns plus key indexed fields                                                                                              | Flexible schema, strong querying, audit tables    |
| File storage    | S3-compatible storage in a UK region                                                                                                                                         | Keeps originals unchanged; UK data residency      |
| PDF parsing     | PyMuPDF for text and layout; OCR for scanned pages (Tesseract, or a cloud OCR service in a UK region)                                                                        | Keeps page numbers and positions for highlighting |
| Language model  | A leading model with structured (JSON) output, via a provider with UK/EU hosting and no training on customer data (e.g. Anthropic's Claude via API or AWS Bedrock in London) | Long documents, reliable structured extraction    |
| Rule engine     | Python module loading rules from YAML files                                                                                                                                  | Rules as data; easy to add and test               |
| Export          | Word via python-docx; PDF via HTML-to-PDF                                                                                                                                    | Matches what firms send today                     |

### Suggested repository layout

```
/apps/web            # review UI
/services/api        # HTTP API, auth, matters, uploads
/services/pipeline   # stages 2–7 as separate modules
    /parse           # classify, OCR, page and clause mapping
    /extract         # LLM extraction per document type, prompts, schemas
    /normalise       # dates, money, areas, names, postcodes
    /gate            # identity and authority checks
    /rules           # rule engine + /rules/catalogue/*.yaml
    /verify          # quote check and verifier pass
    /report          # merge, rank, write explanations and enquiries
/services/export     # PDF, Word, JSON
/tests/fixtures      # test documents and expected outputs (section 13)
/docs/decisions      # decision log
```

### Key API endpoints

- POST /matters — create a matter
- POST /matters/{id}/documents — upload a document
- PATCH /documents/{id} — correct document type
- POST /matters/{id}/runs — start or re-run the pipeline
- GET /runs/{id} — progress per stage
- GET /matters/{id}/facts and PATCH /facts/{id} — view and correct facts
- GET /matters/{id}/flags and PATCH /flags/{id} — view and decide flags
- POST /matters/{id}/gate-override — continue past a failed gate, with reason
- POST /matters/{id}/approve — approve the report
- GET /matters/{id}/export?format=pdf|docx|json

### Extraction approach

- Extract per document type with a dedicated prompt and a strict JSON schema (section 7).
- For long leases, first find the relevant clauses by heading and definitions, then extract from those clauses, rather than sending 150 pages in one request.
- Ask the model to return the exact quote for each value; the quote-check step verifies it.
- Keep prompts in version-controlled files, with a version number stored on each run.

## 13. Test fixtures and acceptance criteria

The first fixture is the three sample documents already in hand. They describe three different properties, so they test both the gate (it must fail) and, with an override, every rule as if they were one property.

### Fixture A: mismatched set ("override test")

| File                                    | Type                                          | Property named                                 |
| --------------------------------------- | --------------------------------------------- | ---------------------------------------------- |
| commercial-lease-100-bishopsgate.pdf    | Lease, dated 1 January 2024, 15 years         | Floors 8–10, 100 Bishopsgate, London EC2M 1GT  |
| environmental-assessment-manchester.pdf | Phase I environmental report, 15 January 2024 | 15–21 Deansgate, Manchester M3 4FN             |
| title-report-lot-7.pdf                  | Title report LN782451, as at 22 November 2023 | Lot 7, 42–48 Victoria Park Road, London E9 7HD |

Review date for this fixture is fixed at 2026-09-26 so date-based rules give stable results.

**Step 1 — without override:** the gate must fail and the pipeline must stop. The mismatch report must list G-01, G-02, G-03 and G-04 with sources, and no other flags.

**Step 2 — with override** (reason: "Test run: treat as one property"): the system must produce the flags below.

| Rule | Severity | Expected finding (evidence to cite)                                                                                                                 |
| ---- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| G-01 | Critical | Three different addresses and postcodes (lease p.1 and cl. 1.1; environmental report p.1; title p.1)                                                |
| G-02 | Critical | Lease lets floors 8–10; title describes a two-storey building; environmental report a four-storey building                                          |
| G-04 | Critical | Landlord Bishopsgate Property Holdings Limited (05198234) vs registered owner Victoria Park Developments Ltd (08234571)                             |
| D-01 | Critical | Planning permission B/2023/4521 (8 Sep 2023) to demolish; lease runs to 31 Dec 2038 with tenant-only breaks (cl. 8.1.1)                             |
| G-03 | High     | Lease area 3,019 m² at 18.7% implies a building of about 16,100 m²; title says 1,200 m²; environmental report 2,400 m²; site 0.34 ha vs 0.28 ha     |
| O-01 | High     | Barclays charge dated 15 March 2019 predates the lease; no lender consent shown                                                                     |
| R-01 | High     | Title as at 22 Nov 2023 is older than the lease and the environmental report, and far more than 30 days old                                         |
| R-02 | High     | 15-year lease dated after the title's as-at date; registration and noting on the title must be checked                                              |
| R-03 | High     | Report is for the sole use of Manchester Property Holdings Ltd; no third-party reliance                                                             |
| R-04 | High     | Lease execution blocks (p.9) are blank                                                                                                              |
| L-03 | High     | Height covenant limits buildings to 4 storeys; lease covers floors 8–10                                                                             |
| E-01 | High     | Printing works (1975–2002) and the oil tank predate the lease; tenant's environmental indemnity (cl. 9.2.1) covers only tenant-caused contamination |
| E-02 | High     | 5,000-litre heating oil tank in the rear yard, status unknown (s.5.3)                                                                               |
| E-05 | High     | Permission for 48 homes on a site with possible solvent and heavy-metal contamination                                                               |
| D-04 | High     | Lease does not state it is excluded from the 1954 Act security of tenure provisions                                                                 |
| R-05 | Medium   | Lease Schedules 1–4 and plans referenced but not attached; title plan referenced (brown and blue markings) but not attached                         |
| R-06 | Medium   | Title report states it is not a copy of the register and cannot be relied on under s.67 Land Registration Act 2002                                  |
| L-04 | Medium   | Boundaries put the access road to the west; the right of way refers to an access road to the north                                                  |
| L-05 | Medium   | Shared sewer easement crosses the site; boreholes, tank removal and demolition are recommended or planned                                           |
| E-03 | Medium   | Phase II investigation £15,000–£25,000; remediation £50,000–£200,000 (both excluding VAT)                                                           |
| E-04 | Medium   | Flood Zone 2, no flood defences; tenant pays 18.7% of the insurance premium (cl. 5.3)                                                               |
| E-06 | Medium   | Sherwood Sandstone Principal Aquifer beneath the site                                                                                               |
| D-02 | Medium   | Permission granted 8 Sep 2023; may have lapsed around 8 Sep 2026 unless work has started                                                            |
| D-03 | Medium   | Section 106: £185,000 highways + £75,000 open space = £260,000; 17 affordable units (35%); local employment agreement                               |
| V-01 | Medium   | Tenant breaks on 1 Jan 2029 and 1 Jan 2034, 12 months' notice, premium of six months' rent (£425,000 at the initial rent)                           |
| R-07 | Low      | Environmental report is more than 12 months old at the review date                                                                                  |
| L-02 | Low      | Printing works use appears to conflict with the 1952 covenant against industrial use                                                                |
| L-06 | Low      | Title requires 1.8 m boundary fencing; lease leaves exterior repair with the landlord                                                               |
| V-03 | Low      | Rent of £850,000 against a 2019 price of £4,250,000 implies about 20%; refer to a valuer                                                            |
| V-04 | Low      | No guarantor or rent deposit                                                                                                                        |
| V-02 | Info     | Upward-only open market reviews on 1 Jan 2029 and 1 Jan 2034                                                                                        |

Expected totals: 4 critical, 11 high, 10 medium, 5 low, 1 info (31 flags).

**Must NOT be flagged** (negative tests, to catch false alarms):

- O-03: the title has no cautions or restrictions registered.
- L-01: office use (Class E(g)(i)) does not breach the covenant against industrial or heavy commercial use.
- L-03 for the planning permission: blocks of 3 and 4 storeys are within the 4-storey limit.

### Fixtures to create next

- **Fixture B, clean matched set:** synthetic title, lease and environmental report for one property with consistent facts. The gate must pass and only genuine risks appear. The build agent should generate this set and its expected output.
- **Fixture C, matched set with planted issues:** Fixture B with 10 known problems inserted, one at a time, to measure recall per rule.
- **Fixture D, real anonymised documents** from partner firms, reviewed by a solicitor to create the expected output.

### Acceptance criteria for the MVP

- [ ] Fixture A step 1: gate fails with G-01 to G-04 only, and the pipeline stops.
- [ ] Fixture A step 2: all 31 expected flags found, with correct severity (± one level allowed for Medium and below).
- [ ] Fixture A: none of the negative tests flagged.
- [ ] Every flag's evidence quotes appear word for word in the source PDF, with correct page numbers.
- [ ] Clicking evidence opens the PDF at the right page with the quote highlighted.
- [ ] Fixture B: gate passes, and there are no critical flags.
- [ ] The report cannot be approved while critical or high flags are open.
- [ ] Export to PDF, Word and JSON works and includes approved flags only.
- [ ] Every decision and override appears in the audit log.
- [ ] Upload to review-ready in under 5 minutes for Fixture A.

## 14. Evaluation and quality metrics

Quality is measured automatically on every code change and continuously from solicitor decisions in live use. Missing a critical issue is worse than raising a false alarm, so recall on serious flags is the headline number.

### Offline evaluation (on every change)

- Run all fixtures and compare output to the expected flags.
- Report, per rule and overall:
  - **Recall:** share of expected flags found. Target 95% for critical and high.
  - **Precision:** share of produced flags that were expected. Target 80%.
  - **Severity match:** share of flags with the expected severity.
  - **Quote accuracy:** share of evidence quotes found word for word, with the right page. Target 100%.
  - **Fact accuracy:** share of extracted facts matching expected values, per field.
- Fail the build if critical/high recall or quote accuracy drops below target.
- Run each fixture 3 times to measure repeatability.

### Live metrics (from the review screen)

- Rejection rate per rule and reason (a rule rejected as "wrong" more than 30% of the time needs fixing).
- Manual flags added by solicitors, grouped by risk type (these show what the system misses).
- Edits to severity and text per rule.
- Time from review-ready to approval per matter, compared with the firm's usual time.
- Facts corrected by solicitors, per field.

### Success measures for the MVP pilot

| Measure                                                                 | Target                    |
| ----------------------------------------------------------------------- | ------------------------- |
| Solicitor time saved on first-pass review                               | At least 50%              |
| Critical or high issues found by the solicitor but missed by the system | Zero across pilot matters |
| Solicitors who say they would use it on their next matter               | At least 4 in 5           |

## 15. Roadmap after the MVP

Each phase reuses the same pipeline and adds document types, rules or outputs. The MVP's data model must not block any of these.

| Phase    | Adds                                                                                                                                | Unlocks workflows                              |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 1 (MVP)  | Title, one lease, environmental report; gate; single and cross checks; review; export                                               | Purchase of a tenanted property; refinancing   |
| 2        | Multiple leases per property; local authority and drainage searches; planning decision notices; Section 106 agreements as documents | Multi-let buildings; development site purchase |
| 3        | Full report on title and lender certificate of title templates                                                                      | Lender work at scale                           |
| 4        | Multiple properties per matter, portfolio dashboard, cross-property risk summary                                                    | Portfolio acquisitions; fund due diligence     |
| 5        | Seller-side pack review; lease drafting checks against a firm's standard positions                                                  | Sales; leasing                                 |
| 6        | Integrations with practice management and document systems (e.g. iManage, NetDocuments), Land Registry data                         | Less manual uploading                          |
| Parallel | Residential version shared with DayOne (freehold and leasehold flats)                                                               | Residential conveyancing                       |

## 16. Open questions and glossary

### Open questions

The build agent should proceed with the stated default for each, and record it in the decision log.

- [ ] Product name and whether it sits inside DayOne or stands alone. Default: working name "Property Risk Review", separate app sharing code with DayOne.
- [ ] Which firms will pilot, and can they supply anonymised document sets? Default: build with Fixtures A–C until real sets arrive.
- [ ] Should the gate allow a missing intermediate lease to count as a link between landlord and owner? Default: flag as critical, allow override.
- [ ] Exact thresholds (area tolerance 10%, yield range 3%–12%, title age 30 days, report age 12 months). Default: as stated, configurable per firm.
- [ ] Preferred language model and hosting region. Default: a provider with UK or EU hosting and a no-training commitment.
- [ ] Enquiry wording: does each firm want its own house style? Default: one standard style in the MVP.
- [ ] A practising property solicitor must review the rule catalogue and the Fixture A expected output before launch.

### Glossary

| Term                    | Meaning                                                                                                              |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 1954 Act                | Landlord and Tenant Act 1954; gives many business tenants a right to renew unless the lease is "contracted out"      |
| Alienation              | A tenant's rights to transfer (assign) or sublet the lease                                                           |
| Assignment              | Transferring a lease to a new tenant                                                                                 |
| Break clause            | A right to end a lease early on set dates                                                                            |
| Charge                  | A mortgage or loan secured on the property, registered on the title                                                  |
| Covenant                | A binding promise; restrictive covenants stop the owner doing things, positive ones require action                   |
| Easement                | A right over someone else's land, such as a right of way or a sewer                                                  |
| Enquiries               | Formal questions sent to the seller's solicitor                                                                      |
| Flood Zone 2            | Medium chance of river flooding: between 1 in 100 and 1 in 1,000 each year                                           |
| GIA / NIA               | Gross internal area (whole inside of a building) / net internal area (usable space only)                             |
| Indemnity               | A promise to cover another party's losses                                                                            |
| Phase I / Phase II      | Desk study of contamination / follow-up ground testing                                                               |
| Principal aquifer       | Rock holding important groundwater supplies; pollution reaching it is serious                                        |
| Report on title         | A solicitor's report to the client on the legal state of the property                                                |
| Section 106 agreement   | A legal agreement with the council attached to a planning permission, often requiring payments or affordable housing |
| Tenure                  | How the land is held: freehold (owned outright) or leasehold (for a fixed term)                                      |
| Title                   | The legal record of ownership, kept by HM Land Registry                                                              |
| Upward-only rent review | Rent can go up or stay the same at review, never down                                                                |
| Vacant possession       | Handing over a property empty, with no one occupying it                                                              |
