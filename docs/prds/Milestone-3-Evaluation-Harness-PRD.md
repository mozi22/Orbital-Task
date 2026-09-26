# Milestone 3 — Evaluation Harness

Sep 26, 2026 · @Muazzam

## 1. Summary

Milestone 2 builds the risk-review pipeline. Milestone 3 proves it works: an automated eval script drives the real application end-to-end against the three sample fixtures (`sample-docs/`), scores the output against a checked-in answer key, and reports pass/fail per test group with an overall weighted score.

The answer key is a **filtered subset** of [`docs/Eval Test Cases — Multi-Document Property Risk Review.md`](../Eval%20Test%20Cases%20—%20Multi-Document%20Property%20Risk%20Review.md), which is itself a superset covering the full ~35-rule design. Milestone 3 only tests what Milestone 2 actually implements — the 12-rule catalogue and 24-fact model from [`docs/property-risk-review-assignment-requirements.md`](../property-risk-review-assignment-requirements.md).

## 2. What's in scope from the eval superset

| Group | Included | Excluded (out of Milestone 2's scope) |
| --- | --- | --- |
| Classification | CL-01 to CL-03 (all) | — |
| Gate | GT-01, GT-02, GT-03, GT-05 | GT-04 (tests rule G-03, not one of our 3 gate rules) |
| Extraction | 24 of 55 fields — the ones matching the assignment's 24-fact model (e.g. EX-L01/02/03/04/07/08/16/17/18/19/20; EX-T01/04/06/08/11/15/18; EX-E02/03/04/05/06/13) | The other 31 fields (net internal area, rent review, service charge, planning history detail, etc.) |
| Flags | FL-01, 02, 03, 04, 06, 09, 10, 11, 12, 13, 15, 25 — exactly the 12 rules Milestone 2 implements | FL-05, 07, 08, 14, 16–24, 26–31 (19 tests for rules G-03, R-01, R-02, E-05, R-05, R-06, L-04, L-05, E-03, E-04, E-06, D-02, D-03, R-07, L-02, L-06, V-02, V-03, V-04 — none in scope) |
| Negative | NG-02, NG-03 (relevant to L-03, which is in scope) | NG-01, NG-04, NG-05, NG-06 (test facts/rules not extracted or implemented) |
| Report quality | RQ-01 to RQ-08 | RQ-09 (draft enquiries), RQ-10 (missing-information section) — both explicitly out of Milestone 2 |
| Question-answer | none | QA-01 to QA-08 — tests chat Q&A quality, which no milestone committed to as a graded target |

## 3. Scope

### In scope

- `docs/eval/answer_key.json` — adopts the source doc's own JSON test format (section 11) as-is, containing only the filtered subset above.
- An eval script that, per pass:
  1. Creates a conversation via the real API.
  2. Uploads the three sample PDFs (`sample-docs/`).
  3. Triggers a risk-review run via `POST .../risk-review`.
  4. Consumes the real SSE progress stream to detect completion (not polling) — this exercises the actual mechanism Milestone 2 ships, not a separate, weaker path.
  5. Fetches the JSON export and scores it against the answer key.
- **Two passes per eval invocation**: Run 1 (no override, scored against classification/gate/extraction tests) and Run 2 (override reason "Test run: treat as one property", scored against flag/negative/report-quality tests) — matching the source doc's own test setup.
- **Grading**: code-based checks (exact values, page ± 1 tolerance, quote verification, severity ranges, hard gates, weighted scoring) wherever the answer is structural; an **isolated Opus call** as the AI judge for semantic matching (does a produced flag describe the same issue as expected; report-quality judgments), kept separate from the Sonnet calls Milestone 2's pipeline itself uses, per Anthropic's documented best practice of using a different model to grade than the one being evaluated.
- **Repeatability**: each pass runs 3 times; at least 95% of flags must match across runs (same issue, same severity) — matches the source doc's own repeatability check.
- **Reporting**: both a CLI printout (score per group, hard-gate pass/fail, failed/partial tests with expected-vs-actual side by side) and a saved artifact — a JSON results file plus a human-readable Markdown summary — written per run, so results are diffable across runs and durable beyond the terminal scrollback.
- **Unmatched flags**: any produced flag matching no expected test is listed in the saved report for manual labeling (valid miss / duplicate / false alarm), per the source doc's own process — never silently discarded, never auto-penalized as a hard failure.
- Invoked via a **`just eval`** recipe, alongside this repo's existing `justfile` targets — a first-class, discoverable command, not a one-off script.
- **Tests for the eval harness itself**: unit tests for the pure-code scoring logic (quote-matching, page-tolerance comparison, weighted-score aggregation, hard-gate logic, group-threshold pass/fail), and a mocked-response contract test verifying the script correctly parses/handles the AI judge's JSON output. No requirement to "test whether Opus judges correctly" — that would be circular.

### Out of scope

- Testing/scoring any rule, fact field, or feature outside Milestone 2's 12-rule / 24-fact scope (the excluded rows in the table above).
- The Question-Answer test group (QA-01 to QA-08) — no milestone scoped chat Q&A as a graded target.
- Building out the "next fixtures" the source doc mentions (a matched clean set, a planted-issue set, real anonymised sets) — this milestone only scores against the existing mismatched fixture.
- CI integration (running `just eval` automatically on every push) — not ruled out for later, but not part of this milestone's acceptance criteria.

## 4. How grading works

- **Code-based** (fast, deterministic): gate outcome, extracted values after normalisation, page numbers (± 1), quote-verification (word-for-word substring match, ignoring line breaks/extra spaces), severity-in-range checks, weighted-score arithmetic, hard-gate enforcement.
- **AI judge** (Opus, isolated call, no shared context with the pipeline's own Sonnet calls): semantic flag matching ("does this describe the same issue, does it mention every must-mention item, does it avoid every must-not item"), and the subjective report-quality checks (plain English, careful wording, duplicate detection).
- **Human** (manual, out of the script itself but supported by its output): spot-checking any "partial" judge verdict, and reviewing any unmatched flag for valid/duplicate/false-alarm labeling.

## 5. Acceptance criteria

- [ ] `docs/eval/answer_key.json` exists, contains exactly the filtered subset of tests described in section 2, in the source doc's own JSON format.
- [ ] `just eval` runs both passes (no-override, override) end-to-end against the real API, using the real SSE stream to detect completion.
- [ ] Each pass runs 3 times; the script reports the repeatability rate (% of flags matching across runs).
- [ ] Code-based checks and the Opus-based AI judge are both implemented and used for the appropriate test types (per section 4).
- [ ] Hard gates (GT-01, all in-scope critical flags, quote-verification, no-valuation/tax-advice) fail the whole eval run if any one of them fails, regardless of other scores.
- [ ] Output includes: overall weighted score, per-group scores, a list of failed/partial tests with expected-vs-actual shown side by side, false-alarm rate, duplicate count, repeatability rate — both printed to the CLI and saved as a JSON + Markdown artifact.
- [ ] Any produced flag matching no expected test appears in the saved report for manual labeling, not silently dropped.
- [ ] Unit tests exist for the scoring logic; a mocked contract test exists for the AI-judge integration.
- [ ] The Question-Answer test group and all rules/facts outside Milestone 2's 12-rule scope are absent from the answer key entirely — not present-but-skipped, not partially implemented.
