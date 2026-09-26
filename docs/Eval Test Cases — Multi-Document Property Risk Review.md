# Eval Test Cases — Multi-Document Property Risk Review

Sep 26, 2026 · @Muazzam

## 1. How to use this eval set

This document is the answer key. Run the application on the three sample documents, then compare its output against the expected results here, test by test. It pairs with the [requirements doc](https://claude.ai/code/artifact/b7ebfa02-90fb-41b2-8271-4b36dbbf4859), which defines the rules and data model.

### What gets tested

| Group | Tests | What it checks |
| --- | --- | --- |
| Classification (CL) | 3 | Each file is recognised as the right document type |
| Extraction (EX) | 55 | Key facts are pulled out correctly, with the right page |
| Gate (GT) | 5 | The system spots that the documents don't match and stops |
| Flags (FL) | 31 | Every expected red flag is raised, with the right severity and evidence |
| Negative (NG) | 6 | Things that look risky but aren't are NOT flagged |
| Question-answer (QA) | 8 | Answers to the questions asked in the original review conversation |
| Report quality (RQ) | 10 | Output is traceable, plain English and stays within limits |

### How a result is matched to a test

Your application may use different rule names or wording. A flag counts as a match when all of these are true:

1. It describes the **same underlying issue** (judged by meaning, not exact words).
2. It **mentions every "must mention" item** listed for that test.
3. It **cites the required documents**, with page numbers that match (± 1 page is allowed for the printed vs PDF page difference).
4. Its severity is within the allowed range.

One application flag can match only one test. If the app splits one issue into two flags, match the better one and count the other as a duplicate (it doesn't fail the test, but is counted in the duplicate rate).

### Who judges

- **Code checks** for exact values: dates, amounts, company numbers, page numbers, severity, counts.
- **An AI judge** (another language model) for meaning: "does this flag describe the same issue?" and "is this answer correct?". The judge prompt is in section 11.
- **A human spot check** of any test where the AI judge scores "partial", and of 10% of passes chosen at random.

## 2. Test setup

Every test uses the same three files, the same fixed review date, and runs in two passes: once without override (the gate must stop it), once with override (all rules run as if the documents were one property).

| File | Pages | Document type | Property named |
| --- | --- | --- | --- |
| commercial-lease-100-bishopsgate.pdf | 9 | Lease | Floors 8–10, 100 Bishopsgate, London EC2M 1GT |
| environmental-assessment-manchester.pdf | 7 | Phase I environmental report | 15–21 Deansgate, Manchester M3 4FN |
| title-report-lot-7.pdf | 3 | Title report | Lot 7, Victoria Park Estate, 42–48 Victoria Park Road, London E9 7HD |

**Fixed settings for every run**

- Review date: 2026-09-26. Date-based rules (report age, planning expiry, title age) depend on this, so the app must accept it as a setting rather than using today's date.
- Transaction type: purchase of a tenanted property, acting for the buyer.
- Run 1: no override. Used for classification, extraction and gate tests.
- Run 2: gate override with the reason "Test run: treat as one property". Used for flag, negative and report quality tests.
- Run each pass 3 times to measure repeatability (same result each time).

**Page numbering used in this document**

Page numbers are the PDF page (1 = first page of the file). In these three files the printed page labels match the PDF pages, so either may be used.

**Record for each run:** model name and version, prompt version, rule version, run time, and the full JSON output.

## 3. Classification tests

All three files must be classified correctly with at least 80% confidence, without asking the user to confirm.

| ID | File | Expected type | Pass criteria |
| --- | --- | --- | --- |
| CL-01 | commercial-lease-100-bishopsgate.pdf | Lease | Type = lease; confidence ≥ 0.8; 9 pages detected |
| CL-02 | environmental-assessment-manchester.pdf | Environmental report (Phase I) | Type = environmental; confidence ≥ 0.8; 7 pages detected |
| CL-03 | title-report-lot-7.pdf | Title report | Type = title; confidence ≥ 0.8; 3 pages detected; marked as a summary, not an official copy (see EX-T20) |

## 4. Extraction tests

55 facts must be extracted with the right value and the right page: 20 from the lease, 20 from the title report, 15 from the environmental report.

**How to score each fact**

- **Pass:** value matches after normalising (dates as YYYY-MM-DD, money in GBP, "Ltd" = "Limited", spacing and case ignored) and the page is correct (± 1).
- **Partial:** value correct but page wrong or missing, or a list with some items missing.
- **Fail:** wrong value, or marked not found when it is there.
- **Not-found tests** (marked ∅) pass only if the app explicitly returns "not found" or "not stated". Inventing a value is a fail.
- Every extracted fact must carry a quote that exists word for word in the document (tested in RQ-01).

### Lease (commercial-lease-100-bishopsgate.pdf)

| ID | Field | Expected value | Page |
| --- | --- | --- | --- |
| EX-L01 | Landlord | Bishopsgate Property Holdings Limited, Company No. 05198234 | 3 (cl. 1.1) |
| EX-L02 | Tenant | Meridian Consulting Group LLP, Registration No. OC412987 | 3 (cl. 1.1) |
| EX-L03 | Lease date | 2024-01-01 | 1 |
| EX-L04 | Premises | Floors 8, 9 and 10, 100 Bishopsgate, London EC2M 1GT | 3 (cl. 1.1) |
| EX-L05 | Net internal area | About 32,500 sq ft (3,019 m²) | 4 (cl. 2.2) |
| EX-L06 | Term length | 15 years | 3–4 (cl. 1.1, 2.3) |
| EX-L07 | Term start and end | Start 2024-01-01; end 2038-12-31 | 4 (cl. 2.3) |
| EX-L08 | Initial rent | £850,000 a year, excluding VAT, paid quarterly in advance on the usual quarter days | 4 (cl. 3.1) |
| EX-L09 | Schedules and plans referenced but not attached | Schedules 1, 2, 3 and 4 and the annexed plans; none present | 3–5 |
| EX-L10 | Rent review dates | 2029-01-01 and 2034-01-01 | 3 (cl. 1.1) |
| EX-L11 | Rent review basis | Open market rent; upward only | 4–5 (cl. 3.2.1, 3.2.5) |
| EX-L12 | Permitted use | Offices, Class E(g)(i) | 6 (cl. 6.1) |
| EX-L13 | Tenant's service charge share | 18.7% | 5 (cl. 4.2.3) |
| EX-L14 | Insurance | Landlord insures; loss of rent cover at least 3 years; tenant pays 18.7% of the premium | 6 (cl. 5.1, 5.3) |
| EX-L15 | Transfer and subletting | Assignment with landlord's consent (may require an authorised guarantee agreement); sublet of whole with consent; sublet of part not allowed | 6–7 (cl. 7.1–7.3) |
| EX-L16 | Break dates and notice | Tenant only; 2029-01-01 and 2034-01-01; at least 12 months' written notice; notice cannot be withdrawn | 7 (cl. 8.1.1, 8.2.1) |
| EX-L17 | Break conditions | No unremedied material breach; vacant possession; break premium of 6 months' rent in cleared funds | 7 (cl. 8.3.1) |
| EX-L18 | Environmental indemnity scope | Limited to contamination caused by the tenant or people at the premises with its authority = true | 8 (cl. 9.2.1) |
| EX-L19 | Excluded from 1954 Act security of tenure | ∅ not stated | — |
| EX-L20 | Execution status | Unsigned: all four signature lines blank | 9 |

### Title report (title-report-lot-7.pdf)

| ID | Field | Expected value | Page |
| --- | --- | --- | --- |
| EX-T01 | Title number | LN782451 | 1 |
| EX-T02 | Edition date and as-at time | Edition 2023-11-22; register as at 12:00 on 22 November 2023 | 1, 3 |
| EX-T03 | Tenure and class | Freehold, absolute | 1 |
| EX-T04 | Address | Lot 7, Victoria Park Estate, 42–48 Victoria Park Road, London E9 7HD | 1 |
| EX-T05 | Site area | About 0.34 ha (0.84 acres) | 1 |
| EX-T06 | Building | Two-storey detached commercial building, about 1,200 m² gross internal area | 1 |
| EX-T07 | Boundaries | North: Victoria Park Road; east: homes on Cadogan Terrace; south: rear gardens on Wick Road; west: access road | 1 |
| EX-T08 | Registered owner | Victoria Park Developments Ltd, Company No. 08234571, 17 Hackney Road, London E2 7NX | 1 |
| EX-T09 | Registered since | 2019-03-14 | 1 |
| EX-T10 | Price paid | £4,250,000 (transfer dated 2019-03-14) | 1 |
| EX-T11 | Charge | Barclays Bank PLC (01026167), legal charge dated 2019-03-15, secures further advances | 1 |
| EX-T12 | Covenant source | Conveyance dated 1952-06-01, London County Council to Herbert William Marsh | 2 |
| EX-T13 | Use covenant | No industrial, manufacturing or heavy commercial use; no nuisance to neighbours | 2 |
| EX-T14 | Fencing covenant | Keep boundary fencing at least 1.8 m high where the land adjoins homes | 2 |
| EX-T15 | Height covenant | No building over 4 storeys, measured from ground level at the 1952 conveyance date | 2 |
| EX-T16 | Right of way | Benefit of a right of way over the access road "to the north" (coloured brown) to Victoria Park Road | 2 |
| EX-T17 | Drainage easement | Shared sewer crossing north-east to south-west; owner must allow access for maintenance | 2 |
| EX-T18 | Planning permission | B/2023/4521, granted 2023-09-08 by LB Hackney: demolish and build 48 homes (12 one-bed, 24 two-bed, 12 three-bed) in blocks of 3 and 4 storeys, 24 parking spaces | 2 |
| EX-T19 | Section 106 agreement | Dated 2023-10-12 (Hackney, the owner, Barclays): 35% affordable (17 homes), £185,000 highways, £75,000 open space, local employment agreement | 2 |
| EX-T20 | Cautions, restrictions and document status | None registered; document is a summary, not a copy of the register, and can't be relied on under s.67 Land Registration Act 2002 | 3 |

### Environmental report (environmental-assessment-manchester.pdf)

| ID | Field | Expected value | Page |
| --- | --- | --- | --- |
| EX-E01 | Reference and date | GEC/2024/0142; 2024-01-15 | 1 |
| EX-E02 | Consultant and client | Greenfield Environmental Consultants Ltd for Manchester Property Holdings Ltd | 1 |
| EX-E03 | Reliance | Sole use of the client; no liability to any third party | 6 |
| EX-E04 | Site and area | 15–21 Deansgate, Manchester M3 4FN; about 0.28 ha (0.69 acres) | 1–2 |
| EX-E05 | Building | Four-storey brick building from about 1920; about 2,400 m² gross internal area; vacant since 2019 | 2 |
| EX-E06 | Historical uses | 1920–1975 textile warehouse; 1975–2002 printing works; 2002–2019 offices; 2019 onwards vacant | 2 |
| EX-E07 | Ground and groundwater | Glacial till 5–8 m over Sherwood Sandstone; Principal Aquifer | 2–3 |
| EX-E08 | Nearest river | River Irwell, about 180 m north-west | 3 |
| EX-E09 | Flood risk | Flood Zone 2; no flood defences | 3 |
| EX-E10 | Contaminated land register | Not determined as contaminated land; no notices | 3 |
| EX-E11 | Nearby pollution incidents | 1987 diesel spill about 120 m away (closed 1988); 1993 solvent discharge about 200 m away (closed 1997) | 3 |
| EX-E12 | Air quality | Inside the Greater Manchester Air Quality Management Area (nitrogen dioxide, declared 2016) | 3 |
| EX-E13 | Storage tank | Underground heating oil tank in the rear yard, about 5,000 litres, status unknown (from a 1985 survey) | 4–5 |
| EX-E14 | Overall risk and recommendation | Low to moderate; Phase II ground investigation recommended | 2 |
| EX-E15 | Cost estimates | Phase II £15,000–£25,000; remediation £50,000–£200,000; both excluding VAT | 6 |

## 5. Gate tests

In Run 1 (no override) the gate must fail, stop the pipeline, and explain why with four mismatches. This is the single most important behaviour: an app that reviews these papers as one deal without warning has failed.

| ID | Test | Pass criteria |
| --- | --- | --- |
| GT-01 | Gate outcome | Result is "fail" (not pass or warn). No single-document or cross-document flags are produced. The user is offered "replace a document" or "continue anyway", and continuing requires a written reason that is saved in the audit log. |
| GT-02 | Address mismatch | Names all three addresses and postcodes: EC2M 1GT (lease p.1/p.3), M3 4FN (environmental p.1), E9 7HD (title p.1). States they are different properties. |
| GT-03 | Building size mismatch | Lease lets floors 8–10 (p.3) but the title describes a two-storey building (p.1) and the environmental report a four-storey building (p.2). |
| GT-04 | Area mismatch | Lease area 3,019 m² (p.4); title building 1,200 m² and site 0.34 ha (p.1); environmental building 2,400 m² and site 0.28 ha (p.2). Bonus (not required): notes that 3,019 m² at an 18.7% share implies a building of about 16,100 m². |
| GT-05 | Party mismatch | Lease landlord Bishopsgate Property Holdings Limited (05198234) is not the registered owner Victoria Park Developments Ltd (08234571). Mentions the environmental report's client is a third company, Manchester Property Holdings Ltd. |

## 6. Flag tests

In Run 2 (with override) the app must raise these 31 flags: 4 critical, 11 high, 10 medium, 5 low and 1 info. Each flag passes only if it mentions every "must mention" item and cites the listed documents and pages.

**Allowed severity range:** Critical must be critical. High may be high or critical. Medium may be low to high. Low may be info to medium. Info may be info or low.

**Evidence codes:** L = lease, T = title report, E = environmental report, followed by the page.

### Critical

| ID | Rule | Must mention | Evidence |
| --- | --- | --- | --- |
| FL-01 | G-01 | Three different addresses/postcodes; documents may not relate to one property | L p.1–3, T p.1, E p.1 |
| FL-02 | G-02 | Floors 8–10 let; title building 2 storeys; environmental building 4 storeys | L p.3, T p.1, E p.2 |
| FL-03 | G-04 | Landlord is not the registered owner; both company names; can't grant a valid lease without an interest in the land | L p.3, T p.1 |
| FL-04 | D-01 | Permission B/2023/4521 to demolish; lease runs to 31 Dec 2038; no landlord break; tenant blocks redevelopment | T p.2, L p.4, L p.7 |

### High

| ID | Rule | Must mention | Evidence |
| --- | --- | --- | --- |
| FL-05 | G-03 | Floor or site areas don't agree across documents, with at least two of the figures | L p.4, T p.1, E p.2 |
| FL-06 | O-01 | Barclays charge (15 March 2019) predates the lease; lender consent to the lease not shown | T p.1, L p.1 |
| FL-07 | R-01 | Title as at 22 Nov 2023 is older than the lease and environmental report; fresh search needed | T p.1 or p.3, L p.1, E p.1 |
| FL-08 | R-02 | 15-year lease (over 7 years) must be registered and noted on the title; not shown | L p.4, T p.1–3 |
| FL-09 | R-03 | Report is for the sole use of Manchester Property Holdings Ltd; buyer or lender can't rely on it; reliance letter or new report | E p.6 |
| FL-10 | R-04 | Lease signature blocks are blank (unsigned) | L p.9 |
| FL-11 | L-03 | Title limits buildings to 4 storeys; lease covers floors 8–10 | T p.2, L p.3 |
| FL-12 | E-01 | Printing works and/or oil tank predate the lease; tenant indemnity covers only tenant-caused contamination; cost stays with owner | E p.2 or p.4–5, L p.8 |
| FL-13 | E-02 | Underground heating oil tank, about 5,000 litres, status unknown | E p.4–5 |
| FL-14 | E-05 | Planning for 48 homes on a site with possible contamination; homes need stricter clean-up standards | T p.2, E p.2 or p.5 |
| FL-15 | D-04 | Lease doesn't show it is excluded from the 1954 Act; tenant may have a right to renew | L (any; absence) |

### Medium

| ID | Rule | Must mention | Evidence |
| --- | --- | --- | --- |
| FL-16 | R-05 | Lease schedules and plans referenced but not attached (at least one named). Title plan missing is a bonus. | L p.3–5 |
| FL-17 | R-06 | Title document is not a copy of the register and can't be relied on under s.67 | T p.3 |
| FL-18 | L-04 | Boundaries put the access road on the west; right of way describes it "to the north"; check the title plan | T p.1, T p.2 |
| FL-19 | L-05 | Shared sewer easement crosses the site; affects boreholes, tank removal or building works | T p.2, E p.5 or p.6 |
| FL-20 | E-03 | Phase II recommended at £15,000–£25,000; remediation £50,000–£200,000; excluding VAT | E p.6 |
| FL-21 | E-04 | Flood Zone 2 with no defences; insurance impact; tenant's 18.7% premium share is a bonus | E p.3 (L p.6 bonus) |
| FL-22 | E-06 | Principal Aquifer beneath the site | E p.3 |
| FL-23 | D-02 | Permission granted 8 Sep 2023; may lapse about 8 Sep 2026 unless work has started | T p.2 |
| FL-24 | D-03 | Section 106 binds the buyer; £185,000 + £75,000 (or £260,000 total); 17 affordable homes | T p.2 |
| FL-25 | V-01 | Tenant can break on 1 Jan 2029 (and 2034); six months' rent premium (£425,000); secure income shorter than 15 years | L p.7 |

### Low and info

| ID | Rule | Severity | Must mention | Evidence |
| --- | --- | --- | --- | --- |
| FL-26 | R-07 | Low | Environmental report dated 15 Jan 2024 is more than 12 months old | E p.1 |
| FL-27 | L-02 | Low | Past printing works use appears to breach the 1952 covenant against industrial use; probably historic | E p.2, T p.2 |
| FL-28 | L-06 | Low | 1.8 m fencing duty on the owner; lease leaves exterior with the landlord | T p.2, L p.5 |
| FL-29 | V-03 | Low | £850,000 rent vs £4,250,000 price looks inconsistent; refer to a valuer; must NOT state a value | T p.1, L p.4 |
| FL-30 | V-04 | Low | No guarantor or rent deposit | L (absence) |
| FL-31 | V-02 | Info | Upward-only open market reviews on 1 Jan 2029 and 1 Jan 2034 | L p.3–5 |

## 7. Negative tests

These six items look risky at a glance but aren't red flags. A good app leaves them out or keeps them at info level. Flagging them higher counts as a false alarm.

| ID | Must NOT flag | Why it's not a risk | Pass criteria |
| --- | --- | --- | --- |
| NG-01 | A restriction or caution on the title | The title says none are registered (T p.3) | No flag claiming a registered restriction or caution |
| NG-02 | Office use breaching the industrial-use covenant | Offices (Class E(g)(i)) are not industrial, manufacturing or heavy commercial use (L p.6, T p.2) | No flag, or info only |
| NG-03 | The planned 3- and 4-storey blocks breaching the height covenant | 4 storeys is the limit, so they are within it (T p.2) | No flag saying the planning permission breaches the covenant |
| NG-04 | The site being registered as contaminated land | The council register says it has not been determined as contaminated (E p.3) | No flag stating the site is on the contaminated land register |
| NG-05 | The 1987 and 1993 nearby pollution incidents | Both off-site and closed with no further action (E p.3) | No flag above low |
| NG-06 | The air quality management area | It covers most of Manchester city centre; it is not specific to this site (E p.3) | No flag above info |

## 8. Question-answer tests

If the app lets users ask questions about the documents, it must answer these eight the way the original review did. Each answer is judged on its key points, not its wording.

| ID | Question to ask the app | Must include | Must not |
| --- | --- | --- | --- |
| QA-01 | Are these three documents related? | Not directly: three different properties (London EC2, Manchester, Hackney E9) with different owners and parties. Common ground: all UK commercial property documents of the kind used in due diligence, all dated Nov 2023–Jan 2024. | Treat them as one deal; claim a link through Barclays or the shared environmental law reference |
| QA-02 | When are a title report, a lease and an environmental report all used in one transaction? | Buying, lending on or developing a tenanted commercial property. Used together at due diligence and by the lender; the value comes from cross-checking them. | Say only one of them is needed |
| QA-03 | Treating them as one property, what are the most serious problems? | At least 4 of: landlord isn't the owner; floors 8–10 vs 2 or 4 storeys and a 4-storey limit; demolition permission vs 15-year lease; old contamination not covered by the tenant; lender consent missing; unsigned lease | Present these as certain legal conclusions without caveats |
| QA-04 | Which of these problems only exist because we assumed one property? | Splits into cross-document issues (identity, landlord vs owner, lender consent, lease vs demolition, contamination vs indemnity, height vs floors) and standalone issues (Section 106 costs, access road wording, unsigned lease, tenant break in 2029) | Say all issues depend on the assumption |
| QA-05 | Group the risks by type | Uses types equivalent to: identity, ownership and authority, document reliability, land restrictions and rights, environmental, development and planning, income and value. Identity checks come first. | Mix identity mismatches in with ordinary risks without saying they block the review |
| QA-06 | Who pays to clean up the old printing works contamination? | The owner (landlord), not the tenant: the tenant's indemnity only covers contamination the tenant causes (L p.8, cl. 9.2.1). Mentions the £15,000–£25,000 Phase II and £50,000–£200,000 remediation estimates. | Say the tenant pays |
| QA-07 | Can the tenant leave early, and what would it cost? | Yes, on 1 Jan 2029 or 1 Jan 2034 with at least 12 months' notice, if there's no material breach and it gives vacant possession, plus six months' rent (£425,000 at the current rent; more if rent has gone up) (L p.7) | Say the tenant is locked in for 15 years |
| QA-08 | Can the owner build the 48 homes that have planning permission? | Not without dealing with: the lease to 2038 with no landlord break; possible renewal rights under the 1954 Act; contamination clean-up to a residential standard; the sewer easement; Section 106 costs; the permission may lapse about Sept 2026. Notes the 3–4 storey scheme is within the height covenant. | Say it can go ahead straight away |

## 9. Report quality tests

These ten tests check the whole Run 2 report, not individual flags. RQ-01 and RQ-05 are hard gates: failing either fails the eval regardless of other scores.

| ID | Test | Pass criteria | How checked |
| --- | --- | --- | --- |
| RQ-01 | Quotes are real | 100% of evidence quotes appear word for word in the cited document (ignoring line breaks and extra spaces) | Code |
| RQ-02 | Pages are right | At least 95% of evidence page numbers correct (± 1) | Code |
| RQ-03 | Every flag is complete | Every flag has an explanation, why it matters, and a suggested next step | Code |
| RQ-04 | Plain English | Average sentence under 25 words; terms such as easement, indemnity, covenant and the 1954 Act explained at first use | AI judge |
| RQ-05 | Stays in its lane | No property valuation, no tax advice, no statement of what the buyer should pay | AI judge + human |
| RQ-06 | Careful wording | Uncertain points use "may", "appears" or "check whether". For example, it must not state as fact that the lease is void. | AI judge |
| RQ-07 | Cross-document flags labelled | Every flag involving two or more documents is marked as cross-document and cites each document | Code |
| RQ-08 | Few duplicates | No more than 3 duplicate flags (the same issue raised twice) | AI judge |
| RQ-09 | Draft enquiries | Draft questions to the seller's solicitor exist for at least FL-03 (landlord's interest), FL-06 (lender consent), FL-09 (reliance), FL-16 (missing schedules) and FL-18 (access), each linked to its flag | AI judge |
| RQ-10 | Missing information section | Lists the missing lease schedules and plans, the missing title plan, the blank signatures, and facts not found (1954 Act exclusion, guarantor) | Code + AI judge |

## 10. Scoring and pass thresholds

The eval passes only if every hard gate passes and the weighted score is at least 85%. Each test scores 1 (pass), 0.5 (partial) or 0 (fail).

### Hard gates (any failure = eval fails)

- GT-01: the gate fails and stops Run 1.
- All 4 critical flags (FL-01 to FL-04) found.
- RQ-01: every quote is real.
- RQ-05: no valuation or tax advice.

### Group thresholds and weights

| Group | Tests | Minimum to pass the group | Weight in overall score |
| --- | --- | --- | --- |
| Flags: critical and high | 15 | At least 14 passes, and no fails among critical | 30% |
| Flags: medium, low and info | 16 | At least 12 passes | 10% |
| Gate | 5 | 5 of 5 (partial allowed on GT-04) | 15% |
| Extraction | 55 | At least 50 passes; all ∅ not-found tests pass | 15% |
| Report quality | 10 | At least 8 passes | 15% |
| Question-answer | 8 | At least 7 passes; QA-01 and QA-06 must pass | 10% |
| Negative | 6 | At least 5 passes | 5% |
| Classification | 3 | 3 of 3 | Required, not weighted |

### Extra flags (not in this answer key)

This answer key may itself have gaps. Every extra flag the app raises is reviewed by a person and labelled:

- **Valid:** a real issue this key missed. Not penalised; add it to the key as a new test.
- **Duplicate:** counted under RQ-08.
- **False alarm:** wrong or not a risk. False alarms must be no more than 20% of all flags raised.

### Repeatability

Across 3 identical runs, at least 95% of flags must be the same (same issue and severity). Report any flag that appears in only some runs; these usually point to unstable prompts.

### What to report after each eval run

- Overall weighted score and pass or fail
- Score per group, and which hard gates passed
- List of failed and partial tests, with the app's actual output next to the expected output
- False alarm rate, duplicate count and repeatability rate
- Model, prompt and rule versions used

## 11. Judge prompt and machine-readable test file

Use the prompt below for every test marked "AI judge". Store all tests in one JSON file using the format shown, so the eval can run automatically on every code change.

### AI judge prompt

```
You are checking the output of a property document review tool against an answer key.

TEST ID: {test_id}
EXPECTED: {expected}
MUST MENTION: {must_mention_list}
MUST NOT: {must_not_list}
ALLOWED SEVERITY: {allowed_severity}
REQUIRED EVIDENCE: {required_evidence}

APP OUTPUT:
{app_output}

Instructions:
1. Decide if the app output describes the same issue or answer as EXPECTED. Judge meaning, not wording.
2. Check each MUST MENTION item. An item counts only if it is clearly stated.
3. Check each MUST NOT item. Any match means FAIL.
4. Check the severity is inside ALLOWED SEVERITY (skip if not given).
5. Check the cited documents and pages match REQUIRED EVIDENCE (a difference of 1 page is fine).
6. Do not reward extra detail. Do not penalise different wording.

Return only JSON:
{"test_id": "...", "verdict": "pass" | "partial" | "fail",
 "missing_items": [...], "must_not_hits": [...],
 "severity_ok": true | false | null, "evidence_ok": true | false,
 "reason": "one sentence"}

Use "partial" when the issue matches but one MUST MENTION item or the evidence is missing.
Use "fail" when the issue doesn't match, two or more items are missing, or a MUST NOT is hit.
```

### Test file format

One JSON object per test, with the same IDs as this document. Four examples, one of each main kind:

```
[
  {
    "id": "EX-L07",
    "group": "extraction",
    "document": "commercial-lease-100-bishopsgate.pdf",
    "field": "lease.term",
    "expected": {"start_date": "2024-01-01", "end_date": "2038-12-31"},
    "page": 4,
    "check": "code"
  },
  {
    "id": "EX-L19",
    "group": "extraction",
    "document": "commercial-lease-100-bishopsgate.pdf",
    "field": "lease.security_of_tenure.contracted_out_of_1954_act",
    "expected": "not_stated",
    "page": null,
    "check": "code"
  },
  {
    "id": "FL-03",
    "group": "flag",
    "run": 2,
    "rule": "G-04",
    "allowed_severity": ["critical"],
    "must_mention": [
      "landlord is not the registered owner",
      "Bishopsgate Property Holdings Limited",
      "Victoria Park Developments Ltd",
      "a lease needs an interest in the land to be valid"
    ],
    "must_not": ["states as fact that the lease is void"],
    "required_evidence": [{"document": "lease", "page": 3}, {"document": "title", "page": 1}],
    "check": "ai_judge"
  },
  {
    "id": "NG-03",
    "group": "negative",
    "run": 2,
    "must_not_flag": "planning permission breaches the 4-storey height covenant",
    "max_allowed_severity": null,
    "check": "ai_judge"
  }
]
```

Convert every table row in sections 3–9 into this format; the tables are the source of truth. When a new valid issue is found (section 10), add it here and to the matching table.

### Next fixtures to add

- **Matched set:** title, lease and environmental report for one property with consistent facts. The gate must pass and no identity flags should appear.
- **Planted-issue set:** the matched set with one known problem inserted at a time, to test each rule alone.
- **Real anonymised sets** from pilot firms, with the answer key written or checked by a practising property solicitor.
