"""Claim verification against provided sources.

Deterministic, dependency-free textual entailment: for each claim, find the
source sentence with the highest token coverage and decide:

* ``supported`` — the claim's content is substantially covered by a source.
* ``contradicted`` — high overlap but a negation or dosage mismatch flips the
  meaning (the most dangerous failure mode in clinical text).
* ``unverifiable`` — no source covers the claim; a clinician must check it.

Why deterministic-first: a startup can run this in CI on every model or
prompt change with zero GPU cost and fully reproducible results. The
``verify_claim`` function is the seam where a heavier NLI model
(e.g. a DeBERTa-v3 MNLI cross-encoder) can be plugged in later without
changing the pipeline, triage, or HITL layers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .claims import DOSAGE_RE
from .models import Claim, Source

_STOPWORDS = frozenset(
    """a an the and or of to in on for with is are was were be been being it its
    this that these those as at by from we you they he she his her their our your
    my than then so such or nor yet""".split()
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\(\"'\[])")
_NEGATIONS = {
    "no", "not", "never", "n't", "none", "neither", "without", "cannot",
    "can't", "won't", "don't", "doesn't", "isn't", "aren't", "wasn't",
    "contraindicated", "avoid", "discontinue", "stop", "stopped",
}

SUPPORT_THRESHOLD = 0.50
PARTIAL_THRESHOLD = 0.25
CONTRADICT_THRESHOLD = 0.35


def _tokens(s: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-z0-9']+", s.lower())
        if t not in _STOPWORDS and len(t) > 1
    }


def _raw_words(s: str) -> set[str]:
    return set(re.findall(r"[a-z']+", s.lower()))


def _source_sentences(sources: list[Source]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for s in sources:
        for sent in _SENT_SPLIT.split(s.text):
            sent = sent.strip()
            if len(sent) >= 4:
                out.append((s.id, sent))
    return out


def _normalize_dosage(d: str) -> str:
    return re.sub(r"\s+", "", d.lower())


# Dosage ranges ("200 to 400 mg", "200-400 mg") and single amounts, parsed
# with units so a claim dose inside a stated range is not misread as a
# contradiction.
_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:to|-|–|—)\s*(\d+(?:\.\d+)?)\s*(mg|mcg|µg|g|ml|l|units?|iu)\b",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mg|mcg|µg|g|ml|l|units?|iu|tablets?|capsules?)\b",
    re.IGNORECASE,
)


def _dosage_amounts(text: str) -> list[tuple[float, str]]:
    return [(float(m.group(1)), m.group(2).lower()) for m in _AMOUNT_RE.finditer(text)]


def _dosage_ranges(text: str) -> list[tuple[float, float, str]]:
    return [
        (float(m.group(1)), float(m.group(2)), m.group(3).lower())
        for m in _RANGE_RE.finditer(text)
    ]


def _dose_within_range(claim_text: str, source_sent: str) -> bool:
    """True if every claim dosage amount falls inside a source-stated range."""
    amounts = _dosage_amounts(claim_text)
    if not amounts:
        return False
    ranges = _dosage_ranges(source_sent)
    return all(
        any(lo <= val <= hi and unit == u for lo, hi, u in ranges)
        for val, unit in amounts
    )


@dataclass
class Verification:
    verdict: str
    confidence: float
    evidence: Optional[str]
    evidence_source_id: Optional[int]


def verify_claim(claim: Claim, sources: list[Source]) -> Verification:
    claim_toks = _tokens(claim.text)
    if not claim_toks or not sources:
        return Verification("unverifiable", 0.2, None, None)

    best: Optional[tuple[float, int, str]] = None
    for sid, sent in _source_sentences(sources):
        st = _tokens(sent)
        if not st:
            continue
        coverage = len(claim_toks & st) / len(claim_toks)
        if best is None or coverage > best[0]:
            best = (coverage, sid, sent)
    assert best is not None
    coverage, sid, sent = best
    sent_toks = _tokens(sent)

    # Dosage mismatch against the best-matching source sentence: the claim
    # talks about the same thing but states a different dose -> contradiction.
    # Range-aware: a dose inside a stated source range (e.g. 200 mg within
    # "200 to 400 mg") is grounding, not contradiction.
    if claim.has_dosage:
        sent_dosages = {_normalize_dosage(m.group(0)) for m in DOSAGE_RE.finditer(sent)}
        claim_dosages = {_normalize_dosage(d) for d in claim.dosage_strings}
        if (
            sent_dosages
            and claim_dosages.isdisjoint(sent_dosages)
            and not _dose_within_range(claim.text, sent)
            and coverage >= 0.30
        ):
            return Verification("contradicted", 0.85, sent, sid)

    # Negation flip: high overlap but opposite polarity ("is indicated" vs
    # "is contraindicated") -> contradiction.
    claim_neg = bool(_raw_words(claim.text) & _NEGATIONS)
    sent_neg = bool(_raw_words(sent) & _NEGATIONS)
    if claim_neg != sent_neg and coverage >= CONTRADICT_THRESHOLD:
        return Verification("contradicted", 0.75, sent, sid)

    if coverage >= SUPPORT_THRESHOLD:
        return Verification("supported", round(min(0.95, coverage), 3), sent, sid)
    if coverage >= PARTIAL_THRESHOLD:
        return Verification("unverifiable", 0.5, sent, sid)
    return Verification("unverifiable", 0.3, None, None)
