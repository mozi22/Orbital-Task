# Multi-Document Property Risk Review: Requirements (Assignment Scope)

**Version:** 1.0 (assignment scope) · **Date:** 26 September 2026 · **Author:** Muazzam Ali

## 1. Summary

We are building a system that reads three property documents about one deal and returns a single risk report. Every flag in the report points to the exact page and quote it came from.

**Input:** three PDFs for one UK commercial property:

- **Title report:** who owns the land, what debts and restrictions sit on it
- **Lease:** who rents it, for how long, on what terms
- **Environmental report (Phase I):** ground pollution, flood risk, history of the site

**Output:** a risk report containing:

- A short property summary (parties, key dates, rent)
- A list of red flags, each with a severity, a plain-English explanation, a suggested next step, and source quotes
- A clear label on flags that come from comparing two documents ("cross-document")

**The core idea:** most tools read one document at a time. The most serious problems often only appear when two documents contradict each other. For example, the lease names a landlord who isn't the owner on the title. Catching these is what this system does best.

**Guiding rules for the build:**

1. Never state a fact without a source (document, page and exact quote).
2. Check that the documents belong to the same property before running any other check.
3. When unsure, flag it as "needs checking" rather than guessing or staying silent.
4. Write every output in plain English. Explain any legal term the first time it appears.
5. Never give a property valuation or tax advice.

---

## 2. The problem

Property solicitors spend hours on every deal reading documents line by line and writing up what's wrong.

- **It's slow.** One commercial property can mean a 60-page lease, a title with old restrictions, and a technical environmental report.
- **Mistakes are expensive.** Missing a break clause or a contamination risk is a classic reason solicitors get sued.
- **The hardest part is comparison.** Many serious problems don't live in any one document. They only appear when documents are read side by side, and that's where tired people miss things.
- **Existing tools stop at one document.** Summarising a single file is common. Cross-checking is left to the human.

This assignment shows that a narrow system can catch cross-document problems reliably, refuse to review mismatched papers, and back every claim with a source.

---

## 3. User and use case

**User:** a property solicitor reviewing documents for a client buying a tenanted commercial property.

**Use case:**

1. The user uploads a title report, a lease and an environmental report.
2. The system checks the documents describe the same property and parties. If not, it stops and explains why. The user can choose to continue anyway (needed for testing).
3. The system extracts key facts and runs 12 risk checks.
4. The user sees a summary and a list of flags, each linked to the source text.
5. The user marks each flag as accepted or rejected.

---

## 4. Scope

### In scope

- UK commercial property, England and Wales law
- One property per review, one document of each type
- Text-based PDFs only (no scanned documents)
- Fact extraction for the fields in section 7 only
- The identity gate (3 rules)
- 9 further risk rules (section 8), weighted towards cross-document checks
- A risk report shown as a web page or a generated HTML file
- Accept or reject per flag (kept in memory or a local file)
- JSON output of all facts and flags (needed for the evaluation)
- A quote check that confirms every quote exists in the source PDF
- An evaluation script and results (section 10)

### Out of scope

See section 12 for the full list. In short: login and user accounts, security certification, audit logs, Word/PDF export, scanned documents, multiple leases or properties, draft letters to the other side, and the remaining ~20 rules from the full design.

### Assumptions

- Documents are in English and under 50 pages each.
- The title document may be a summary rather than an official copy of the register.
- Plans and schedules referred to in documents are often missing from the files.

---

## 5. Input documents

| Type                 | Typical sections the system must find                                                                                |
| -------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Title report         | Property description, registered owner, charges (mortgages), restrictive covenants, planning and other noted entries |
| Lease                | Parties, premises, term, rent, break clause, environmental indemnity, signature blocks                               |
| Environmental report | Client, site description, historical uses, storage tanks, reliance statement                                         |

**Handling requirements**

- Detect the document type automatically, and let the user correct it if wrong.
- Keep the page number for every piece of extracted text, so references match the PDF.
- Keep clause numbers (for example 8.3.1), because solicitors cite by clause.
- Detect blank signature blocks.

---

## 6. Processing pipeline

The system runs seven stages in order. The gate at stage 3 stops the run if the documents don't describe the same property.

```
Upload → Parse → Extract facts → Gate: same property?
                                    ├─ no  → Stop and show mismatches (user may override)
                                    └─ yes → Run 12 rules → Quote check → Risk report → Accept/reject
```

### Design principle: AI reads, code compares

- Use a large language model (LLM, an AI text model) to **read** documents and pull facts into a fixed structure, always with the exact quote.
- Use ordinary code to **compare** facts wherever possible (names, dates, numbers). Code comparisons are repeatable and easy to test.
- Use the LLM for **judgement checks** only where wording matters (for example, "does this indemnity only cover contamination the tenant causes?"). Each judgement must return quotes from the documents it relied on.

### Stage details

1. **Upload:** accept three PDFs and store them unchanged.
2. **Parse:** extract text page by page. Keep page numbers and clause numbers. Detect document type.
3. **Extract facts:** fill the data model in section 7. Each value comes with its page, its exact quote and a confidence score from 0 to 1. Normalise values so code can compare them: dates as YYYY-MM-DD, money in GBP, and company names with "Ltd" and "Limited" treated as the same.
4. **Gate:** run rules G-01, G-02 and G-04. The result is **pass** or **fail**.
   - On fail: stop and show each mismatch with sources. The user may click "continue anyway" and must type a reason.
5. **Rules:** run the 9 remaining rules in section 8.
6. **Quote check:** search for every quote in the PDF text. Drop any fact or flag whose quote isn't found, and log it. This stops made-up evidence reaching the user.
7. **Report:** sort flags by severity, show the summary and flags, and allow accept or reject per flag.

---

## 7. Data model

### Common structures

**Source** (where a fact came from)

| Field    | Type           | Notes                                            |
| -------- | -------------- | ------------------------------------------------ |
| document | string         | lease, title or environmental                    |
| page     | integer        | 1-based page in the PDF                          |
| clause   | string or null | e.g. "8.3.1" or "Charges Register entry 1"       |
| quote    | string         | Exact text from the document, max 300 characters |

**Fact** (every extracted value)

| Field      | Type       | Notes                            |
| ---------- | ---------- | -------------------------------- |
| key        | string     | Field name from the lists below  |
| value      | any        | Normalised value                 |
| source     | Source     | Where it came from               |
| confidence | number 0–1 | Below 0.7 means "needs checking" |
| status     | string     | found, not_found, needs_checking |

"not_found" is a real answer, not an error. Some risks come from something being absent (for example, no statement excluding the 1954 Act).

### Fields to extract (24 facts)

**Lease (11)**

- landlord (name, company number)
- tenant (name, registration number)
- lease_date
- premises (floors, address, postcode)
- term (start date, end date)
- initial_rent (annual amount)
- breaks (who can break, dates, notice period)
- break_conditions (conditions, premium)
- environmental_indemnity_tenant_caused_only (true or false)
- excluded_from_1954_act (yes, no or not_stated)
- execution_status (signed or unsigned)

**Title report (7)**

- title_number
- property_address (address, postcode)
- building_storeys
- registered_owner (name, company number)
- charges (lender, date)
- height_covenant (maximum storeys)
- planning_permissions (reference, date granted, description)

**Environmental report (6)**

- client_name
- reliance (who may rely on the report)
- site_address (address, postcode)
- building_storeys
- historical_uses (from year, to year, use)
- storage_tanks (location, contents, capacity, status)

### Flag (one risk in the report)

| Field            | Type     | Notes                                      |
| ---------------- | -------- | ------------------------------------------ |
| flag_id          | string   | Unique                                     |
| rule_id          | string   | From section 8                             |
| severity         | string   | critical, high, medium, low                |
| cross_document   | boolean  | True if two or more documents are involved |
| title            | string   | Short headline                             |
| explanation      | string   | Plain English, 1–3 sentences               |
| why_it_matters   | string   | Consequence for the client                 |
| suggested_action | string   | What the solicitor should do next          |
| evidence         | Source[] | At least one per document involved         |
| review_status    | string   | open, accepted, rejected                   |

### Example flag

```json
{
  "flag_id": "f_003",
  "rule_id": "G-04",
  "severity": "critical",
  "cross_document": true,
  "title": "Landlord named in the lease is not the registered owner",
  "explanation": "The lease is granted by Bishopsgate Property Holdings Limited, but the title shows Victoria Park Developments Ltd as owner.",
  "why_it_matters": "Only the owner, or someone holding a lease from the owner, can grant a valid lease. The tenancy may not bind the owner.",
  "suggested_action": "Ask for evidence of the landlord's interest, such as a superior lease or an unregistered transfer.",
  "evidence": [
    {
      "document": "lease",
      "page": 3,
      "clause": "1.1",
      "quote": "\"the Landlord\" means Bishopsgate Property Holdings Limited (Company No. 05198234)"
    },
    {
      "document": "title",
      "page": 1,
      "clause": "Registered Owner",
      "quote": "Victoria Park Developments Ltd (Company No. 08234571)"
    }
  ],
  "review_status": "open"
}
```

---

## 8. Rules (12)

Each rule has an ID, a check, the documents it needs, a method, and a default severity.

**Method:** "Code" means compare extracted facts with fixed logic. "LLM" means an AI model reads the quoted clauses and answers yes, no or unclear, with quotes. "Both" means code narrows it down and the model confirms.

**Severity:** Critical means the deal can't safely continue until resolved. High means it must be resolved or priced before contracts are signed. Medium means raise it with the seller's solicitor.

### Gate rules (run first)

| ID   | Check                                                                         | Documents    | Method | Severity |
| ---- | ----------------------------------------------------------------------------- | ------------ | ------ | -------- |
| G-01 | Address and postcode match across all documents                               | All          | Code   | Critical |
| G-02 | Building storeys agree, and any floors let in the lease exist in the building | All          | Code   | Critical |
| G-04 | Lease landlord is the title's registered owner                                | Lease, title | Both   | Critical |

### Cross-document rules

| ID   | Check                                                                                                                 | Documents            | Method | Severity |
| ---- | --------------------------------------------------------------------------------------------------------------------- | -------------------- | ------ | -------- |
| O-01 | A mortgage on the title predates the lease, and there's no sign the lender agreed to the lease                        | Title, lease         | Code   | High     |
| L-03 | Floors let, or the building's storeys, exceed a height limit in the title's covenants                                 | Title, lease         | Code   | High     |
| E-01 | Contamination from before the lease isn't covered by the tenant's environmental indemnity, so it stays with the owner | Environmental, lease | Both   | High     |
| D-01 | Planning permission to demolish or redevelop, but the lease runs on with no landlord right to end it early            | Title, lease         | Code   | Critical |

### Single-document rules

| ID   | Check                                                                                         | Documents     | Method | Severity |
| ---- | --------------------------------------------------------------------------------------------- | ------------- | ------ | -------- |
| R-03 | Environmental report can only be relied on by someone other than the buyer                    | Environmental | Both   | High     |
| R-04 | Lease signature blocks are blank                                                              | Lease         | Code   | High     |
| E-02 | Storage tank of unknown status                                                                | Environmental | Code   | High     |
| D-04 | Lease doesn't say it is excluded from the 1954 Act, so the tenant may have a right to renew   | Lease         | LLM    | High     |
| V-01 | Tenant can end the lease early; show the first date, the premium and the secure income period | Lease         | Code   | Medium   |

### Rule-writing guardrails

- Never state a legal conclusion as certain. Use "may", "appears" or "check whether" when the documents don't settle it.
- An LLM check that answers "unclear" still creates a flag, one severity lower, marked "needs checking".

---

## 9. Output and user interface

A single page (or generated HTML file) with three parts:

1. **Header:** property, documents reviewed with their dates, and the gate result (pass, fail, or overridden with the reason).
2. **Summary table:** owner, landlord, tenant, lender, lease dates, rent, break dates. Each value shows its source page. Values that differ across documents are highlighted.
3. **Flags:** sorted by severity. Each shows:
   - severity, rule ID, title, and a "cross-document" label where relevant
   - explanation, why it matters, suggested action
   - evidence quotes with document and page. Clicking one opens the PDF at that page. Showing the quote alone is acceptable if PDF linking isn't built.
   - Accept and Reject buttons

**Writing style:** short sentences, plain English, legal terms explained in brackets, and names and dates exactly as the documents give them.

The system also saves the full output (facts, gate result, flags) as JSON, for the evaluation.

---

## 10. Evaluation

The three sample documents describe three different properties. That makes them a good test: the gate must fail on them, and with an override every rule can be tested as if they were one property.

| File                                    | Property named                                 |
| --------------------------------------- | ---------------------------------------------- |
| commercial-lease-100-bishopsgate.pdf    | Floors 8–10, 100 Bishopsgate, London EC2M 1GT  |
| environmental-assessment-manchester.pdf | 15–21 Deansgate, Manchester M3 4FN             |
| title-report-lot-7.pdf                  | Lot 7, 42–48 Victoria Park Road, London E9 7HD |

**Setup:** review date fixed at 2026-09-26. **Run 1:** no override. **Run 2:** override with the reason "Test run: treat as one property".

### Gate tests (Run 1)

| ID    | Pass criteria                                                                                                                           |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------- |
| GT-01 | Gate result is "fail". No other flags are produced. Continuing requires a typed reason.                                                 |
| GT-02 | Names all three postcodes (EC2M 1GT, M3 4FN, E9 7HD) and says they are different properties                                             |
| GT-03 | Lease lets floors 8–10 (lease p.3); title describes a 2-storey building (title p.1); environmental report a 4-storey building (env p.2) |
| GT-04 | Landlord Bishopsgate Property Holdings Limited (05198234) is not the owner Victoria Park Developments Ltd (08234571)                    |

### Extraction tests (Run 1): 24 facts

A fact passes if the value is correct after normalising and the page is right (±1). "Not stated" facts pass only if the system returns not_found or not_stated rather than inventing a value.

| ID    | Document      | Field                                      | Expected value                                                                                | Page |
| ----- | ------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------- | ---- |
| EX-01 | Lease         | Landlord                                   | Bishopsgate Property Holdings Limited, 05198234                                               | 3    |
| EX-02 | Lease         | Tenant                                     | Meridian Consulting Group LLP, OC412987                                                       | 3    |
| EX-03 | Lease         | Lease date                                 | 2024-01-01                                                                                    | 1    |
| EX-04 | Lease         | Premises                                   | Floors 8, 9 and 10, 100 Bishopsgate, London EC2M 1GT                                          | 3    |
| EX-05 | Lease         | Term                                       | 2024-01-01 to 2038-12-31 (15 years)                                                           | 4    |
| EX-06 | Lease         | Initial rent                               | £850,000 a year, excluding VAT                                                                | 4    |
| EX-07 | Lease         | Breaks                                     | Tenant only; 2029-01-01 and 2034-01-01; at least 12 months' notice                            | 7    |
| EX-08 | Lease         | Break conditions                           | No unremedied material breach; vacant possession; 6 months' rent premium                      | 7    |
| EX-09 | Lease         | Environmental indemnity tenant-caused only | True                                                                                          | 8    |
| EX-10 | Lease         | Excluded from 1954 Act                     | Not stated                                                                                    | none |
| EX-11 | Lease         | Execution status                           | Unsigned (all signature lines blank)                                                          | 9    |
| EX-12 | Title         | Title number                               | LN782451                                                                                      | 1    |
| EX-13 | Title         | Address                                    | Lot 7, Victoria Park Estate, 42–48 Victoria Park Road, London E9 7HD                          | 1    |
| EX-14 | Title         | Building storeys                           | 2                                                                                             | 1    |
| EX-15 | Title         | Registered owner                           | Victoria Park Developments Ltd, 08234571                                                      | 1    |
| EX-16 | Title         | Charge                                     | Barclays Bank PLC, dated 2019-03-15                                                           | 1    |
| EX-17 | Title         | Height covenant                            | Maximum 4 storeys                                                                             | 2    |
| EX-18 | Title         | Planning permission                        | B/2023/4521, granted 2023-09-08, demolition and 48 homes in blocks of 3 and 4 storeys         | 2    |
| EX-19 | Environmental | Client                                     | Manchester Property Holdings Ltd                                                              | 1    |
| EX-20 | Environmental | Reliance                                   | Sole use of the client; no liability to third parties                                         | 6    |
| EX-21 | Environmental | Site address                               | 15–21 Deansgate, Manchester M3 4FN                                                            | 1    |
| EX-22 | Environmental | Building storeys                           | 4                                                                                             | 2    |
| EX-23 | Environmental | Historical uses                            | 1920–1975 textile warehouse; 1975–2002 printing works; 2002–2019 offices; 2019 onwards vacant | 2    |
| EX-24 | Environmental | Storage tank                               | Underground heating oil tank, rear yard, about 5,000 litres, status unknown                   | 4–5  |

### Flag tests (Run 2): 12 flags

A flag passes if it describes the same issue, mentions every "must mention" item, cites the listed documents and pages (±1), and has an allowed severity. Critical must be critical; high may be high or critical; medium may be low to high.

| ID    | Rule | Severity | Must mention                                                                                                                      | Evidence                        |
| ----- | ---- | -------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| FL-01 | G-01 | Critical | Three different addresses/postcodes                                                                                               | Lease p.1–3, title p.1, env p.1 |
| FL-02 | G-02 | Critical | Floors 8–10 let; title building 2 storeys; env building 4 storeys                                                                 | Lease p.3, title p.1, env p.2   |
| FL-03 | G-04 | Critical | Landlord isn't the registered owner; both company names; why a lease needs an interest in the land                                | Lease p.3, title p.1            |
| FL-04 | D-01 | Critical | Permission B/2023/4521 to demolish; lease runs to 31 Dec 2038; no landlord break                                                  | Title p.2, lease p.4, lease p.7 |
| FL-05 | O-01 | High     | Barclays charge (15 Mar 2019) predates the lease; no lender consent shown                                                         | Title p.1, lease p.1            |
| FL-06 | L-03 | High     | 4-storey limit in the title; lease covers floors 8–10                                                                             | Title p.2, lease p.3            |
| FL-07 | E-01 | High     | Printing works or oil tank predate the lease; tenant indemnity covers only tenant-caused contamination; cost stays with the owner | Env p.2 or p.4–5, lease p.8     |
| FL-08 | R-03 | High     | Report is for the sole use of Manchester Property Holdings Ltd; the buyer can't rely on it                                        | Env p.6                         |
| FL-09 | R-04 | High     | Lease signature blocks are blank                                                                                                  | Lease p.9                       |
| FL-10 | E-02 | High     | Underground heating oil tank, about 5,000 litres, status unknown                                                                  | Env p.4–5                       |
| FL-11 | D-04 | High     | No statement excluding the 1954 Act; the tenant may have a right to renew                                                         | Lease (absence)                 |
| FL-12 | V-01 | Medium   | Breaks on 1 Jan 2029 and 1 Jan 2034; premium of six months' rent (£425,000); secure income shorter than 15 years                  | Lease p.7                       |

### Negative tests (Run 2): must NOT be flagged

| ID    | Must not flag                                                 | Why                                                       |
| ----- | ------------------------------------------------------------- | --------------------------------------------------------- |
| NG-01 | Office use breaching the covenant against industrial use      | Offices aren't industrial use                             |
| NG-02 | The planned 3- and 4-storey blocks breaching the height limit | 4 storeys is within the limit                             |
| NG-03 | The site being on the contaminated land register              | The report says it hasn't been determined as contaminated |

### Report quality tests (Run 2)

| ID    | Pass criteria                                                         |
| ----- | --------------------------------------------------------------------- |
| RQ-01 | 100% of quotes appear word for word in the cited PDF                  |
| RQ-02 | At least 95% of page numbers correct (±1)                             |
| RQ-03 | Every flag has an explanation, why it matters, and a suggested action |
| RQ-04 | No property valuation or tax advice anywhere                          |

### How the evaluation runs

1. An eval script runs the system on the three PDFs, once without override and once with.
2. **Code** checks exact answers: gate result, extracted values and pages, severities, and quotes found in the PDF text.
3. **An AI judge** (a separate LLM call) checks meaning: does each app flag describe the same issue as the expected flag and mention every required item? It returns pass, partial or fail with a reason.
4. Any app flag that matches no expected flag is listed for a human to label as valid (a real issue the key missed), duplicate, or false alarm.
5. The script prints a score per group and a side-by-side view of each failed test: expected answer next to the app's answer.

### Pass thresholds

| Group                           | To pass                                            |
| ------------------------------- | -------------------------------------------------- |
| Gate                            | 4 of 4                                             |
| Critical flags (FL-01 to FL-04) | 4 of 4                                             |
| Other flags (FL-05 to FL-12)    | At least 7 of 8                                    |
| Extraction                      | At least 20 of 24, and EX-10 must pass             |
| Negative                        | 3 of 3                                             |
| Report quality                  | RQ-01 and RQ-04 must pass; at least 3 of 4 overall |
| False alarms                    | No more than 20% of all flags raised               |

---

## 11. Suggested build

### Technology

| Part       | Suggestion                                                            |
| ---------- | --------------------------------------------------------------------- |
| Language   | Python                                                                |
| PDF text   | PyMuPDF (keeps page numbers)                                          |
| AI model   | Any leading LLM with JSON output                                      |
| Rules      | Python functions, one per rule, in a single module                    |
| Storage    | Local JSON files (no database needed)                                 |
| Interface  | A simple web page (FastAPI or Streamlit), or a generated HTML report  |
| Evaluation | A separate Python script plus a JSON answer key built from section 10 |

### Suggested folder layout

```
/app
  parse.py        # PDF text by page, type detection
  extract.py      # LLM extraction into the section 7 schema
  normalise.py    # dates, money, company names
  gate.py         # G-01, G-02, G-04
  rules.py        # the 9 other rules
  verify.py       # quote check
  report.py       # builds the HTML report
  main.py         # runs the pipeline; web page or CLI
/eval
  answer_key.json # tests from section 10
  run_eval.py     # runs the app, scores, prints results
/samples          # the three PDFs
README.md
```

### Build order

1. Parse the PDFs and extract the 24 facts, with pages and quotes.
2. Add the quote check.
3. Add the gate and confirm it fails on the samples.
4. Add the 9 rules, cross-document ones first.
5. Build the report page with accept and reject.
6. Build the eval script and record the results.

If time is short, cut to 6 rules: G-01, G-04, D-01, E-01, O-01 and R-04. That keeps the gate, the strongest cross-document checks, and one single-document check.

### Deliverables

- Working code and a README explaining how to run it
- The report produced for the three sample documents
- Evaluation results (scores and failed tests)
- A short write-up: the problem, design choices (especially "AI reads, code compares"), results, limits, and future work

---

## 12. Out of scope (future work)

These are in the full product design but deliberately left out of the assignment:

- **Remaining rules:** about 20 more checks, including area mismatches, out-of-date title searches, missing schedules, access and drainage rights, flood risk, planning expiry, Section 106 costs, and rent reviews
- **Document handling:** scanned PDFs (OCR), Word files, very long documents, multiple leases or properties per review
- **Outputs:** Word and PDF export, draft questions for the seller's solicitor, a missing-information section, a formal report on title
- **Review workflow:** editing flags, adding manual flags, approval sign-off, keeping decisions across re-runs
- **Production needs:** user accounts and login, roles, separation between law firms, encryption and UK hosting commitments, audit logs, security certification, uptime targets
- **Wider evaluation:** a matched document set, planted-issue sets, real anonymised documents, repeatability testing, live usage metrics

---

## 13. Glossary

| Term                 | Meaning                                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------------------- |
| 1954 Act             | Landlord and Tenant Act 1954; gives many business tenants a right to renew unless the lease excludes it |
| Break clause         | A right to end a lease early on set dates                                                               |
| Charge               | A mortgage or loan secured on the property, registered on the title                                     |
| Covenant             | A binding promise, for example not to build above a certain height                                      |
| Cross-document check | A check that compares facts from two or more documents                                                  |
| Gate                 | The first check, confirming the documents are about the same property                                   |
| Indemnity            | A promise to cover another party's losses                                                               |
| LLM                  | Large language model: an AI system that reads and writes text                                           |
| Phase I report       | A desk study of possible ground contamination                                                           |
| Reliance             | Who is legally allowed to rely on a report's findings                                                   |
| Title                | The legal record of ownership, kept by HM Land Registry                                                 |
| Vacant possession    | Handing over a property empty, with no one occupying it                                                 |
