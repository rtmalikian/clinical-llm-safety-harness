# Security & HIPAA posture

This document describes the threat model of the Clinical LLM Safety Harness,
the controls implemented, and — just as important — what is **not** covered.
It is written for the security reviewers and compliance teams at the
health systems and startups that would deploy this.

## Threat model

**Assets:** evaluated clinical text, reviewer notes and identities,
the audit ledger (whose integrity is the product's trust anchor).

**Adversaries considered:**
- Network attackers intercepting or replaying API traffic.
- Abusers turning a public demo endpoint into a free compute oracle.
- Curious or malicious reviewers / operators with DB access.
- Attackers tampering with the audit trail to hide a missed escalation.
- Prompt-injection content inside evaluated conversations attempting to
  influence the harness itself.

**Explicitly out of scope:** the harness evaluates text; it does not provide
end-to-end HIPAA compliance, encryption at rest beyond file permissions, key
management, or network segmentation. Those belong to the deployment layer.

## Implemented controls

| Control | Where | Notes |
|---|---|---|
| PHI/PII detection + redaction gate | `phi.py`, `pipeline.py` | Scans all inputs for SSN, phone, email, MRN, DOB, payment cards, street addresses; redacts before storage/queue/audit. Only finding *kinds* and counts are recorded, never matched values. Toggle: `HARNESS_PHI_SCAN`, `HARNESS_REDACT_PHI`. |
| Optional API-key auth | `security.py`, `api.py` | Set `HARNESS_API_KEY`; all `/api/*` except `/api/health` then require `X-API-Key`. The demo UI has a key field (session-scoped, never in cookies). |
| Rate limiting | `security.py` | Per-IP sliding window, default 120 req/min (`HARNESS_RATE_LIMIT`); 429 on excess. |
| Request size limits | `api.py` | 20k chars per text field, ≤50 messages, ≤20 sources, role allow-list. |
| Security headers | `security.py` | `nosniff`, `DENY` framing, `no-referrer`, baseline CSP. |
| DB file permissions | `db.py` | SQLite file created `0600` (owner-only). |
| Thread-safe writes | `db.py`, `audit.py`, `hitl.py` | Reentrant write lock; audit read-prev-hash + insert is atomic so concurrent writers can't fork the hash chain. |
| Tamper-evident audit | `audit.py` | SHA-256 hash-chained ledger; `/api/audit/verify` detects any historical edit. |
| No eval-time code execution | whole codebase | Evaluated text is data: it is split, pattern-matched, and stored — never executed, templated, or interpolated into commands. |

## HIPAA considerations for deployers

- **De-identification is a pipeline, not a regex.** The built-in `phi.py`
  scanner is a first-pass safety net. Deployments handling real PHI must add
  a proper de-identification stage (Presidio/Philter — tracked as a GitHub
  issue) *before* text reaches this service, run a re-identification-risk
  assessment, and execute a BAA with any infrastructure provider that stores
  or processes the data.
- **Minimum necessary.** Flagged claim text is stored because human
  reviewers need it to do their job — that is the design trade-off. Unflagged
  evaluations persist only aggregate summaries. Retention policies and
  encrypted backups are deployment responsibilities.
- **Access control.** The API key is a single shared secret suitable for
  demos and internal pilots. Multi-user deployments need RBAC + SSO for the
  reviewer UI (tracked as a GitHub issue).
- **This is not a medical device** and not a substitute for your
  organization's security review, penetration testing, or compliance counsel.

## Reporting a vulnerability

Please report security issues privately to **rtmalikian@gmail.com** rather
than opening a public issue. Include a minimal reproduction and the affected
version/commit. Aim: acknowledge within 48 hours.
