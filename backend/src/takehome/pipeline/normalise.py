"""Fact normalisation utilities (Milestone 2, issue #37).

Per the "AI reads, code compares" design principle (docs/Multi-Document
Property Risk Review — Requirements.md, section 6), an LLM extracts raw
values from documents but ordinary, independently-testable code normalises
them into a machine-comparable form so later rules/gates can compare them
reliably. These functions have no LLM dependency and no I/O -- pure string
in, normalised value out (raising a typed error when the input can't be
normalised).

Covers the four fact types called out in the requirements doc's normalisation
bullet (section 6, stage 3) that this ticket is scoped to:
    - dates    -> ISO 8601 (YYYY-MM-DD)
    - money    -> integer pence, GBP
    - company names -> suffix-standardised (e.g. "Ltd" == "Limited")
    - areas    -> square metres, retaining the original value and unit
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

# =============================================================================
# Errors
# =============================================================================


class NormalisationError(ValueError):
    """Base class for all fact-normalisation failures.

    Each subclass carries a distinct `code` so callers (the extraction
    pipeline, ultimately the "needs checking" UX) can tell failure reasons
    apart programmatically instead of pattern-matching on the message,
    mirroring `takehome.services.document.DocumentValidationError`.

    Never raised directly -- only its documented subclasses below are.
    """

    code = "normalisation_error"


class UnparseableDateError(NormalisationError):
    """Raised when a raw date string can't be parsed into a calendar date."""

    code = "unparseable_date"


class UnparseableMoneyError(NormalisationError):
    """Raised when a raw money string isn't a recognisable numeric amount."""

    code = "unparseable_money"


class UnsupportedCurrencyError(NormalisationError):
    """Raised when a raw money string names a currency other than GBP.

    This pipeline only ever compares GBP amounts (per the requirements doc);
    a non-GBP value is a sign the extraction (or the document itself) needs a
    human to look at it, not something to silently coerce.
    """

    code = "unsupported_currency"


class UnparseableAreaError(NormalisationError):
    """Raised when a raw area string has no recognisable number+unit shape."""

    code = "unparseable_area"


class UnsupportedAreaUnitError(NormalisationError):
    """Raised when a raw area string uses a unit this pipeline doesn't know."""

    code = "unsupported_area_unit"


# =============================================================================
# Dates
# =============================================================================

# Full and 3-letter abbreviated month names -> month number, e.g.
# {"january": 1, "jan": 1, ..., "december": 12, "dec": 12}.
_MONTH_NAMES: dict[str, int] = {}
for _i in range(1, 13):
    _MONTH_NAMES[calendar.month_name[_i].lower()] = _i
    _MONTH_NAMES[calendar.month_abbr[_i].lower()] = _i

_ORDINAL_SUFFIX_RE = re.compile(r"(\d)(st|nd|rd|th)\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DAY_MONTHNAME_YEAR_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})$")
_MONTHNAME_DAY_YEAR_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$")
_NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$")


def normalise_date(raw: str) -> str:
    """Normalise a raw extracted date string to ISO 8601 (`YYYY-MM-DD`).

    Handles the formats these UK commercial-property documents actually use:
    already-ISO dates, "22 November 2023"/"22nd November 2023", "November 22,
    2023", abbreviated month names ("22 Nov 2023"), and numeric dates with
    `/`, `-` or `.` separators.

    Numeric dates are UK convention (day first, DD/MM/YYYY). When a numeric
    date is genuinely ambiguous (both components are valid as either a day or
    a month, e.g. "03/04/2024"), it is resolved day-first -- not guessed, but
    a deliberate convention, since these are UK legal documents. When only
    one interpretation is calendrically possible (e.g. "14/03/2019", where 14
    can't be a month), that interpretation is used regardless of position.

    Raises UnparseableDateError if the string doesn't match a known date
    shape, names an unrecognised month, or describes a calendar date that
    doesn't exist (e.g. 31 February).
    """
    s = raw.strip()
    s = _ORDINAL_SUFFIX_RE.sub(r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()

    if not s:
        raise UnparseableDateError(f"Could not parse date: {raw!r}")

    match = _ISO_DATE_RE.match(s)
    if match:
        year, month, day = (int(g) for g in match.groups())
        return _build_iso_date(year, month, day, raw)

    match = _DAY_MONTHNAME_YEAR_RE.match(s)
    if match:
        day_str, month_name, year_str = match.groups()
        month = _MONTH_NAMES.get(month_name.lower())
        if month is not None:
            return _build_iso_date(int(year_str), month, int(day_str), raw)

    match = _MONTHNAME_DAY_YEAR_RE.match(s)
    if match:
        month_name, day_str, year_str = match.groups()
        month = _MONTH_NAMES.get(month_name.lower())
        if month is not None:
            return _build_iso_date(int(year_str), month, int(day_str), raw)

    match = _NUMERIC_DATE_RE.match(s)
    if match:
        a, b, year = (int(g) for g in match.groups())
        day, month = _resolve_numeric_day_month(a, b, raw)
        return _build_iso_date(year, month, day, raw)

    raise UnparseableDateError(f"Could not parse date: {raw!r}")


def _resolve_numeric_day_month(a: int, b: int, raw: str) -> tuple[int, int]:
    """Decide which of two numeric date components is the day vs. the month.

    UK day-first convention, falling back to whichever ordering is
    calendrically possible when only one is. Raises UnparseableDateError if
    neither component could plausibly be a month.
    """
    a_could_be_month = 1 <= a <= 12
    b_could_be_month = 1 <= b <= 12

    if not a_could_be_month and b_could_be_month:
        # `a` can't be a month, so it must be the day (unambiguous).
        return a, b
    if not b_could_be_month and a_could_be_month:
        # `b` can't be a month, so `a` must be the month (unambiguous).
        return b, a
    if a_could_be_month and b_could_be_month:
        # Genuinely ambiguous -- resolve using the UK day-first convention.
        return a, b
    raise UnparseableDateError(f"Could not resolve day/month from: {raw!r}")


def _build_iso_date(year: int, month: int, day: int, raw: str) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError as exc:
        raise UnparseableDateError(f"Could not parse date: {raw!r} ({exc})") from exc


# =============================================================================
# Money
# =============================================================================

_UNSUPPORTED_CURRENCY_RE = re.compile(r"(\$|€|USD|EUR|US\$)", re.IGNORECASE)
_GBP_MARKER_RE = re.compile(r"\bGBP\b", re.IGNORECASE)
_MONEY_AMOUNT_RE = re.compile(r"^-?\d+(\.\d{1,2})?$")


def normalise_money(raw: str) -> int:
    """Normalise a raw extracted money string to integer pence, GBP.

    Accepts "£4,250,000", "£4,250,000.50", "GBP 1,234.56", "1,234.56 GBP" and
    bare numbers (assumed GBP, since this pipeline's documents are all UK
    commercial property paperwork). A single decimal digit is padded to full
    pence (e.g. "£4.5" -> 450 pence).

    Raises UnsupportedCurrencyError if a non-GBP currency symbol or code
    (`$`, `€`, `USD`, `EUR`) is present -- this pipeline never guesses an
    exchange rate. Raises UnparseableMoneyError if what's left isn't a plain
    decimal amount, or if it has more than two decimal places (more precision
    than pence can represent, so rounding would be a guess).
    """
    s = raw.strip()

    if _UNSUPPORTED_CURRENCY_RE.search(s):
        raise UnsupportedCurrencyError(f"Unsupported currency in money value: {raw!r}")

    s = s.replace("£", "")
    s = _GBP_MARKER_RE.sub("", s)
    s = s.replace(",", "").strip()

    if not s or _MONEY_AMOUNT_RE.match(s) is None:
        raise UnparseableMoneyError(f"Could not parse money value: {raw!r}")

    negative = s.startswith("-")
    if negative:
        s = s[1:]

    if "." in s:
        pounds_str, pence_str = s.split(".")
        pence_str = pence_str.ljust(2, "0")
    else:
        pounds_str, pence_str = s, "00"

    pounds = int(pounds_str) if pounds_str else 0
    pence = int(pence_str)
    total_pence = pounds * 100 + pence
    return -total_pence if negative else total_pence


# =============================================================================
# Company names
# =============================================================================

# (pattern matching a trailing suffix token, canonical replacement). Applied
# in order, anchored to the end of the string (optionally preceded by a
# comma), so only the actual corporate suffix is touched -- the rest of the
# name's original casing/spacing is left alone.
_COMPANY_SUFFIX_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r",?\s*\bltd\.?\s*$", re.IGNORECASE), " Limited"),
    (re.compile(r",?\s*\bp\.?\s*l\.?\s*c\.?\s*$", re.IGNORECASE), " PLC"),
    (re.compile(r",?\s*\bllp\.?\s*$", re.IGNORECASE), " LLP"),
]


def normalise_company_name(raw: str) -> str:
    """Standardise a raw extracted company name's corporate suffix.

    Standardises the common suffix synonyms this pipeline's documents use so
    the same company written two ways compares equal: "Ltd"/"Ltd." ->
    "Limited", "plc"/"Plc"/"P.L.C." -> "PLC", "Llp" -> "LLP". "Limited"
    itself is left untouched. Internal whitespace is collapsed and
    surrounding whitespace stripped, but nothing else about the name's
    casing is changed.

    Some extracted "name" values are actually just a bare company/LLP
    registration number (e.g. "05198234", "OC412987", "Company No.
    05198234") with no name text at all -- there's no suffix to standardise,
    so these are returned unchanged rather than mangled.
    """
    s = raw.strip()
    s = re.sub(r"\s+", " ", s)

    for pattern, replacement in _COMPANY_SUFFIX_PATTERNS:
        new_s = pattern.sub(replacement, s)
        if new_s != s:
            return new_s.strip()

    return s


# =============================================================================
# Areas
# =============================================================================


@dataclass(frozen=True)
class NormalisedArea:
    """A normalised area: the machine-comparable m² value, plus the original
    value and unit as written (per the requirements doc: "areas in square
    metres, keep the original unit too")."""

    value_m2: float
    original_value: float
    original_unit: str


# canonical unit token -> (label to report back, conversion factor to m²).
_AREA_UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "m2": ("m2", 1.0),
    "sqm": ("m2", 1.0),
    "sqft": ("sq ft", 0.09290304),
    "ha": ("ha", 10_000.0),
}

_AREA_LEADING_QUALIFIER_RE = re.compile(
    r"^(about|approx\.?|approximately|circa|c\.)\s+", re.IGNORECASE
)
_AREA_VALUE_UNIT_RE = re.compile(r"^([\d,]+(?:\.\d+)?)\s*(.+?)\s*$")


def _canonicalise_area_unit_token(token: str) -> str:
    """Collapse the many ways these documents write a unit down to one of
    the keys in `_AREA_UNIT_FACTORS` (e.g. "sq ft", "square feet", "sqft" all
    become "sqft")."""
    t = token.strip().lower()
    t = t.replace(".", "")
    t = t.replace("²", "2")
    t = re.sub(r"\s+", " ", t)
    t = t.replace("square ", "sq ")
    t = t.replace("metres", "m").replace("meters", "m")
    t = t.replace("metre", "m").replace("meter", "m")
    t = t.replace("feet", "ft").replace("foot", "ft")
    t = t.replace("hectares", "ha").replace("hectare", "ha")
    return t.replace(" ", "")


def normalise_area(raw: str) -> NormalisedArea:
    """Normalise a raw extracted area string to square metres.

    Converts sq ft <-> m² (and hectares, which this pipeline's title/
    environmental reports also use for site areas) while retaining the
    original value and unit exactly as written, per the requirements doc.
    Strips a leading approximation qualifier ("About 32,500 sq ft") since
    that's how these documents phrase most area figures.

    Raises UnparseableAreaError if the string has no leading number.
    Raises UnsupportedAreaUnitError if the unit isn't one this pipeline
    knows how to convert (currently: m², sq ft, hectares).
    """
    s = raw.strip()
    if not s:
        raise UnparseableAreaError(f"Could not parse area: {raw!r}")

    s = _AREA_LEADING_QUALIFIER_RE.sub("", s)

    match = _AREA_VALUE_UNIT_RE.match(s)
    if not match:
        raise UnparseableAreaError(f"Could not parse area: {raw!r}")

    value_str, unit_str = match.groups()
    if not unit_str:
        raise UnparseableAreaError(f"Could not parse area (no unit): {raw!r}")

    try:
        original_value = float(value_str.replace(",", ""))
    except ValueError as exc:
        raise UnparseableAreaError(f"Could not parse area: {raw!r}") from exc

    canonical_unit = _canonicalise_area_unit_token(unit_str)
    factors = _AREA_UNIT_FACTORS.get(canonical_unit)
    if factors is None:
        raise UnsupportedAreaUnitError(f"Unsupported area unit in: {raw!r}")

    label, factor = factors
    value_m2 = round(original_value * factor, 2)
    return NormalisedArea(value_m2=value_m2, original_value=original_value, original_unit=label)
