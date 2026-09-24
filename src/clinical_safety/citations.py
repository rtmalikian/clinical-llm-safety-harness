"""Citation parsing and enforcement.

Every clinical assertion must be traceable to a source the model was given.
Two failure modes are detected:

* ``missing_citation`` — a clinical claim with no citation at all.
* ``dangling_citation`` — a citation id that does not resolve to any
  provided source (a classic hallucination tell: citing phantom references).
"""
from __future__ import annotations

from .models import Claim, Source


def validate_citations(
    claim: Claim, sources: list[Source], requires_citation: bool
) -> list[str]:
    issues: list[str] = []
    source_ids = {s.id for s in sources}
    dangling = sorted({c for c in claim.citations if c not in source_ids})
    if dangling:
        issues.append(
            f"dangling_citation: cites {dangling}, which were not in the provided sources"
        )
    if requires_citation and not claim.citations:
        issues.append("missing_citation: clinical claim carries no source citation")
    return issues
