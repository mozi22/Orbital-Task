"""Milestone 2 risk-review pipeline stages.

Each stage (parse, extract, normalise, gate, rules, verify, report) lives in
its own module here so it can be tested in isolation, per the "AI reads, code
compares" design principle in docs/Multi-Document Property Risk Review —
Requirements.md (section 6). `normalise` is the first stage implemented:
pure, LLM-free functions that turn raw extracted text into machine-comparable
values (ISO dates, pence, standardised company names, square metres).
"""

from __future__ import annotations
