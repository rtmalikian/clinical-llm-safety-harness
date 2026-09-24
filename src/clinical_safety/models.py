"""Shared data models for the clinical safety harness."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

VERDICTS = ("supported", "contradicted", "unverifiable")
SEVERITIES = ("critical", "high", "medium", "low")
ACTIONS = ("auto_pass", "flag_review", "escalate_immediate")
# Severities that describe clinical assertions and therefore require citations.
CLINICAL_SEVERITIES = ("critical", "high", "medium")


@dataclass
class Source:
    """A source document the model was allowed to rely on."""

    id: int
    title: str
    text: str

    def to_dict(self):
        return asdict(self)


@dataclass
class Claim:
    """One atomic assertion extracted from an assistant message."""

    index: int
    text: str
    citations: list[int] = field(default_factory=list)
    has_dosage: bool = False
    dosage_strings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class ClaimVerdict:
    """The harness verdict for a single claim."""

    claim: Claim
    verdict: str  # supported | contradicted | unverifiable
    confidence: float
    severity: str  # critical | high | medium | low
    citation_issues: list[str] = field(default_factory=list)
    action: str = "auto_pass"  # auto_pass | flag_review | escalate_immediate
    reasons: list[str] = field(default_factory=list)
    evidence: Optional[str] = None  # best-matching source sentence, if any

    def to_dict(self):
        return asdict(self)


@dataclass
class EvalSummary:
    eval_id: str
    conversation_id: str
    total_claims: int
    supported: int
    contradicted: int
    unverifiable: int
    escalated: int
    flagged: int
    passed: int
    safeguarding_findings: int = 0
    safeguarding_escalated: int = 0
    phi_findings: int = 0
    phi_redacted: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class SafeguardingReport:
    """Wire format for a safeguarding finding inside API responses."""

    category: str
    severity: str
    message_role: str
    message_index: int
    matched_text: str
    guidance: str
    action: str
    priority: str

    def to_dict(self):
        return asdict(self)
