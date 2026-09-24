"""Clinical severity classification and review triage.

Severity answers "how bad if this claim is wrong?" — mapped to clinical
risk classes a physician would recognize:

* ``critical`` — dosing, contraindications, diagnosis, emergency guidance.
  Wrong here harms patients directly.
* ``high`` — treatment recommendations, dose changes, monitoring advice.
* ``medium`` — general medical information, explanations, risk factors.
* ``low`` — administrative / logistical content with no clinical assertion.

Triage answers "what must happen now?":

* ``escalate_immediate`` (P0) — a clinician must review before the output
  reaches a patient. Contradictions, unsupported critical/high claims, and
  missing citations on clinical claims always escalate.
* ``flag_review`` (P1) — queued for routine human review.
* ``auto_pass`` — supported and fully cited; logged, no review needed.
"""
from __future__ import annotations

import re

from .models import Claim

_CRITICAL = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bprescrib",
        r"\bcontraindicat",
        r"\boverdose\b",
        r"\bemergency\b",
        r"\bcall\s+911\b",
        r"\byou\s+have\b",
        r"\bdiagnos(?:is|ed|e)\b",
        r"\bstop\s+taking\b",
        r"\bdrug\s+interaction\b",
        r"\ballerg",
    ]
]
_HIGH = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\brecommend",
        r"\bshould\s+(?:take|start|use|increase|decrease|stop)\b",
        r"\bstart\s+(?:taking|on)\b",
        r"\bincrease\s+(?:the\s+)?dose",
        r"\bdecrease\s+(?:the\s+)?dose",
        r"\bside\s+effect",
        r"\bmonitor\s+(?:your|for)\b",
        r"\bseek\s+(?:care|help)\b",
    ]
]
_MEDIUM = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bmay\s+(?:cause|lead\s+to|result\s+in|increase)\b",
        r"\btypically\b",
        r"\boften\b",
        r"\bstud(?:y|ies)\s+show\b",
        r"\bguideline",
        r"\brisk\s+factor",
    ]
]
_ADMIN = re.compile(
    r"\b(appointment|schedul|hours|billing|insurance|referral|parking|directions| copay)\b",
    re.IGNORECASE,
)


def classify_severity(claim: Claim) -> str:
    t = claim.text
    if claim.has_dosage or any(p.search(t) for p in _CRITICAL):
        return "critical"
    if any(p.search(t) for p in _HIGH):
        return "high"
    if _ADMIN.search(t) and len(t) < 140:
        return "low"
    if any(p.search(t) for p in _MEDIUM):
        return "medium"
    # Default: substantive sentences are treated as clinical information;
    # short fragments are treated as conversational filler.
    return "medium" if len(t.split()) > 6 else "low"


def priority_for(action: str) -> str:
    return {"escalate_immediate": "P0", "flag_review": "P1"}.get(action, "P2")


def triage_decision(
    verdict: str, severity: str, citation_issues: list[str]
) -> tuple[str, list[str]]:
    """Return (action, reasons) for a verified claim."""
    reasons: list[str] = []
    clinical = severity in ("critical", "high")

    if verdict == "contradicted":
        return (
            "escalate_immediate",
            ["Model output contradicts the cited source — highest patient-safety risk."],
        )

    missing = any(i.startswith("missing_citation") for i in citation_issues)
    dangling = any(i.startswith("dangling_citation") for i in citation_issues)

    if missing and severity in ("critical", "high", "medium"):
        if clinical:
            return (
                "escalate_immediate",
                ["High-stakes clinical claim with no source citation."],
            )
        reasons.append("Clinical information claim carries no source citation.")

    if verdict == "unverifiable":
        if clinical:
            return (
                "escalate_immediate",
                reasons + ["High-stakes claim could not be grounded in any provided source."],
            )
        reasons.append("Claim could not be grounded in the provided sources.")

    if dangling:
        reasons.append("Citation references a source id that was not provided.")

    if reasons:
        return ("flag_review", reasons)
    return ("auto_pass", [])
