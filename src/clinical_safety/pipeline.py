"""Evaluation pipeline: extract -> verify -> triage -> safeguard -> HITL -> audit.

One function, ``run_evaluation``, executes the full harness over a single
assistant response (plus its conversation context and sources):

1. Split the response into atomic claims.
2. Check citation presence and resolvability per claim.
3. Verify each claim against the provided sources.
4. Classify clinical severity and triage to auto_pass / flag_review /
   escalate_immediate.
5. Scan the whole conversation for safeguarding risks (self-harm, harm to
   others, vulnerable persons) — always P0 escalation.
6. Enqueue anything needing a human; write everything to the audit ledger.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

from . import audit, hitl
from .citations import validate_citations
from .claims import extract_claims
from .db import write_lock
from .models import CLINICAL_SEVERITIES, ClaimVerdict, EvalSummary, Source
from .phi import phi_kind_counts, redact_phi, scan_phi
from .safeguarding import scan_conversation
from .triage import classify_severity, priority_for, triage_decision
from .verifier import verify_claim


def _env_true(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.lower() not in ("0", "false", "no", "off")


def run_evaluation(
    db: sqlite3.Connection,
    conversation_id: str,
    messages: list[dict],
    assistant_text: str,
    sources: list[Source],
) -> tuple[EvalSummary, list[ClaimVerdict], list[dict]]:
    eval_id = "eval_" + uuid.uuid4().hex[:12]
    verdicts: list[ClaimVerdict] = []

    # ---- Privacy gate: detect PHI/PII and redact before any text is stored,
    # queued, or audited. Only finding kinds/counts are recorded — never the
    # matched values. Toggle with HARNESS_PHI_SCAN / HARNESS_REDACT_PHI.
    phi_findings = []
    phi_redacted = False
    if _env_true("HARNESS_PHI_SCAN", True):
        for target in [assistant_text] + [str(m.get("content", "")) for m in messages]:
            phi_findings.extend(scan_phi(target))
        if phi_findings and _env_true("HARNESS_REDACT_PHI", True):
            assistant_text = redact_phi(assistant_text)
            messages = [
                {**m, "content": redact_phi(str(m.get("content", "")))} for m in messages
            ]
            phi_redacted = True
            audit.log_event(
                db,
                "phi_redacted",
                {"eval_id": eval_id, "kinds": phi_kind_counts(phi_findings)},
            )

    for claim in extract_claims(assistant_text):
        severity = classify_severity(claim)
        requires_citation = severity in CLINICAL_SEVERITIES
        issues = validate_citations(claim, sources, requires_citation)
        verification = verify_claim(claim, sources)
        action, reasons = triage_decision(verification.verdict, severity, issues)
        verdicts.append(
            ClaimVerdict(
                claim=claim,
                verdict=verification.verdict,
                confidence=verification.confidence,
                severity=severity,
                citation_issues=issues,
                action=action,
                reasons=reasons,
                evidence=verification.evidence,
            )
        )
        if action in ("flag_review", "escalate_immediate"):
            hitl.enqueue(
                db,
                kind="accuracy",
                eval_id=eval_id,
                claim_text=claim.text,
                verdict=verification.verdict,
                severity=severity,
                reasons=reasons + issues,
                priority=priority_for(action),
            )

    # Safeguarding runs over the full conversation, not just the response.
    safeguarding_findings = []
    for finding in scan_conversation(messages):
        safeguarding_findings.append(finding.to_dict())
        hitl.enqueue(
            db,
            kind="safeguarding",
            eval_id=eval_id,
            claim_text=f"[{finding.category}] {finding.matched_text}",
            verdict="safeguarding_risk",
            severity=finding.severity,
            reasons=[finding.guidance],
            priority=finding.priority,
        )

    summary = EvalSummary(
        eval_id=eval_id,
        conversation_id=conversation_id,
        total_claims=len(verdicts),
        supported=sum(1 for v in verdicts if v.verdict == "supported"),
        contradicted=sum(1 for v in verdicts if v.verdict == "contradicted"),
        unverifiable=sum(1 for v in verdicts if v.verdict == "unverifiable"),
        escalated=sum(1 for v in verdicts if v.action == "escalate_immediate"),
        flagged=sum(1 for v in verdicts if v.action == "flag_review"),
        passed=sum(1 for v in verdicts if v.action == "auto_pass"),
        safeguarding_findings=len(safeguarding_findings),
        safeguarding_escalated=len(safeguarding_findings),
        phi_findings=len(phi_findings),
        phi_redacted=phi_redacted,
    )
    with write_lock:
        db.execute(
            "INSERT INTO evals (eval_id, conversation_id, created_at, summary_json) VALUES (?, ?, ?, ?)",
            (eval_id, conversation_id, time.time(), json.dumps(summary.to_dict())),
        )
        db.commit()
    audit.log_event(
        db,
        "evaluation_completed",
        {"eval_id": eval_id, "conversation_id": conversation_id,
         "summary": summary.to_dict()},
    )
    return summary, verdicts, safeguarding_findings
