"""First-pass PHI/PII detection and redaction.

Deterministic pattern scanner that runs *before* evaluation so identifiers
never reach claim storage, the audit log, or the reviewer queue in the clear.

This is a baseline, not a certified de-identification pipeline: pattern
matching cannot catch names, rare identifiers, or quasi-identifier
combinations. Production deployments handling real PHI must replace or
augment this with Presidio/Philter (see GitHub issue) and run their own
re-identification-risk assessment. Only finding *kinds* and counts are ever
stored — never the matched text itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PHIFinding:
    kind: str          # e.g. "ssn", "phone", "email" — never the matched value
    start: int
    end: int


_PATTERNS: dict[str, re.Pattern] = {
    # US Social Security number
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # US phone numbers (various formats); requires 10 digits so doses/dates don't match
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # Medical record numbers and chart numbers
    "mrn": re.compile(r"\b(?:MRN|medical record|chart|account)[\s#:]*\d{5,12}\b", re.IGNORECASE),
    # Dates of birth written with an explicit label
    "dob": re.compile(
        r"\b(?:DOB|date of birth|born)[\s:]*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.IGNORECASE
    ),
    # Credit/debit card numbers
    "payment_card": re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
    # US street addresses (number + street + suffix) — coarse but useful
    "street_address": re.compile(
        r"\b\d{1,5}\s+[A-Za-z0-9.'-]+\s+(?:street|st|avenue|ave|road|rd|boulevard|blvd|"
        r"lane|ln|drive|dr|court|ct|place|pl|way)\b",
        re.IGNORECASE,
    ),
}


def scan_phi(text: str) -> list[PHIFinding]:
    """Return PHI/PII findings for *text*. Findings carry no matched values."""
    findings: list[PHIFinding] = []
    for kind, rx in _PATTERNS.items():
        for m in rx.finditer(text or ""):
            findings.append(PHIFinding(kind=kind, start=m.start(), end=m.end()))
    # De-duplicate overlapping spans, keeping the longest match.
    findings.sort(key=lambda f: (f.start, -(f.end - f.start)))
    deduped: list[PHIFinding] = []
    for f in findings:
        if deduped and f.start < deduped[-1].end:
            continue
        deduped.append(f)
    return deduped


def redact_phi(text: str, findings: list[PHIFinding] | None = None) -> str:
    """Replace detected PHI spans with kind-labeled redaction tokens."""
    findings = findings if findings is not None else scan_phi(text)
    if not findings:
        return text
    out: list[str] = []
    cursor = 0
    for f in sorted(findings, key=lambda x: x.start):
        out.append(text[cursor:f.start])
        out.append(f"[REDACTED-{f.kind.upper()}]")
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)


def phi_kind_counts(findings: list[PHIFinding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return counts
