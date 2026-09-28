"""Static metadata for the risk-review rule catalogue (issue #38).

The 12 rules themselves -- their actual gate/matching logic -- are later
Milestone 2 tickets' job (see the Milestone 2 PRD, section 3, step 3, and
the assignment requirements doc's section 8 for the full catalogue this is
transcribed from). All this module holds is each rule's id and a short,
human-readable description, so the (still-stub) pipeline can emit a progress
line like "Running rule O-01: mortgage predates lease..." at the right
stage boundary without needing the real rule implementations to exist yet.

Kept as a flat, ordered tuple (not a dict) because a run's own progress
narration is the ordered list itself: gate rules run first (`GATE_RULES`),
then the remaining rules run in catalogue order (`RULES`) -- the same order
listed in the requirements doc's section 8 tables.
"""

from __future__ import annotations

from typing import NamedTuple


class RuleSummary(NamedTuple):
    rule_id: str
    description: str


GATE_RULES: tuple[RuleSummary, ...] = (
    RuleSummary("G-01", "address and postcode match across all documents"),
    RuleSummary(
        "G-02",
        "building storeys agree, and any floors let in the lease exist in the building",
    ),
    RuleSummary("G-04", "lease landlord is the title's registered owner"),
)

RULES: tuple[RuleSummary, ...] = (
    RuleSummary("O-01", "mortgage predates lease"),
    RuleSummary("L-03", "floors let or storeys exceed a height limit in the title's covenants"),
    RuleSummary("E-01", "pre-lease contamination not covered by the tenant's indemnity"),
    RuleSummary("D-01", "demolition/redevelopment permission with no landlord break"),
    RuleSummary("R-03", "environmental report can't be relied on by the buyer"),
    RuleSummary("R-04", "lease signature blocks are blank"),
    RuleSummary("E-02", "storage tank of unknown status"),
    RuleSummary("D-04", "lease may not be excluded from the 1954 Act"),
    RuleSummary("V-01", "tenant can end the lease early"),
)
