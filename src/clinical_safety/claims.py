"""Atomic clinical claim extraction from assistant messages.

The core idea: never score a whole response at once. Split it into atomic
claims so each assertion gets its own verdict, severity, and citation check.
A response can then be *partially* right — the unit startups actually need
when deciding what a clinician must re-check.
"""
from __future__ import annotations

import re

from .models import Claim

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\(\"'\[])")
_CITATION = re.compile(r"\[(\d+)\]")
DOSAGE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|µg|g|ml|l|units?|iu|tablets?|capsules?|drops|puffs|%)\b",
    re.IGNORECASE,
)

# Boilerplate that carries no clinical assertion — never becomes a claim.
_NON_CLAIM_PREFIXES = (
    "as an ai",
    "i am an ai",
    "i'm an ai",
    "please consult",
    "this is not medical advice",
    "talk to your doctor",
    "i understand you're",
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_claims(assistant_text: str) -> list[Claim]:
    """Split assistant text into atomic claims with parsed citations."""
    text = _clean(assistant_text)
    if not text:
        return []
    claims: list[Claim] = []
    for part in _SENTENCE_SPLIT.split(text):
        p = part.strip()
        if len(p) < 4:
            continue
        if p.lower().startswith(_NON_CLAIM_PREFIXES):
            continue
        citations = [int(m) for m in _CITATION.findall(p)]
        dosage_hits = [m.group(0) for m in DOSAGE_RE.finditer(p)]
        claims.append(
            Claim(
                index=len(claims),
                text=p,
                citations=citations,
                has_dosage=bool(dosage_hits),
                dosage_strings=dosage_hits,
            )
        )
    return claims
